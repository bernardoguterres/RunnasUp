/**
 * Running MMR pages. Fixtures are real API responses for the SYNTHETIC histories
 * (tools/export_fixtures.py), not hand-written mocks.
 */
import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import type { Participant } from "../api/types";
import fx from "../test/fixtures/mmr.json";
import { health, json, mockFetch, participant, renderApp } from "../test/utils";
import type { Handler } from "../test/utils";

const people = fx.participants as Participant[];
const pid = fx.overview.participant.id;

function base(list: Participant[] = people, demo = true): Handler {
  return (url, init) => {
    if (url.pathname === "/api/health") return json({ ...health, demo_mode: demo, database: demo ? "demo" : "personal" });
    if (url.pathname === "/api/participants" && (init.method ?? "GET") === "GET") return json(list);
    return undefined;
  };
}

function mmrHandlers(overview: unknown = fx.overview): Handler {
  return (url) => {
    if (url.pathname === `/api/mmr/participants/${pid}`) return json(overview);
    if (url.pathname === `/api/mmr/participants/${pid}/history`) return json(fx.history);
    return undefined;
  };
}

describe("Running MMR", () => {
  it("is the home page: estimate, evidence coverage, evidence, data quality, volume kept separate", async () => {
    window.localStorage.setItem("runrank.participant", String(pid));
    mockFetch(base(), mmrHandlers());
    renderApp("/");
    expect(await screen.findByRole("heading", { name: /Running MMR\s*High evidence coverage/ })).toBeTruthy();
    const card = screen.getByRole("region", { name: /^Running MMR (High|Medium|Low|Insufficient)/ });
    expect(within(card).getByText("1,869")).toBeTruthy();               // 1868.7 rounded for display
    expect(within(card).getByText(/unvalidated estimate/)).toBeTruthy();
    const behind = screen.getByRole("region", { name: "Behind your score" });
    expect(within(behind).getByText(/Production method mmr-envelope-v2/)).toBeTruthy();  // in Calculation details
    const t10 = screen.getByRole("region", { name: "10 km-equivalent estimate" });
    expect(within(t10).getByText("46:17")).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Data quality" })).toBeTruthy();
    const vol = screen.getByRole("region", { name: "Training summary" });
    expect(within(vol).getByText("Distance · last 28 days")).toBeTruthy();   // each metric names its period
    expect(within(vol).getByText(/more or longer runs never add points/)).toBeTruthy();
    expect(screen.getByRole("region", { name: "Behind your score" })).toBeTruthy();
    expect(screen.getByRole("group", { name: "History range" })).toBeTruthy();
    const bands = screen.getByRole("table", { name: "Evidence by distance" });
    expect(within(bands).getByText("over 42.5 km (ultra; not converted)")).toBeTruthy();
    const changes = screen.getByRole("table", { name: "Recent MMR changes" });
    expect(within(changes).getAllByRole("link", { name: "Explain" }).length).toBeGreaterThan(0);
    expect(screen.getByRole("link", { name: "Overview" }).getAttribute("aria-current")).toBe("page");
    expect(screen.queryByLabelText("Mode")).toBeNull();                 // legacy 5K mode not on the MMR page
  });

  it("shows insufficient evidence instead of a misleading score", async () => {
    window.localStorage.setItem("runrank.participant", String(pid));
    mockFetch(base(), mmrHandlers(fx.insufficient));
    renderApp("/");
    const card = await screen.findByRole("region", { name: /^Running MMR (High|Medium|Low|Insufficient)/ });
    expect(within(card).getAllByText("Insufficient evidence").length).toBeGreaterThan(0);
    expect(within(card).getByText("—")).toBeTruthy();                   // no number, never a zero
    expect(within(card).getByText(/missing evidence, not low ability/)).toBeTruthy();
  });

  it("first-time demo user can load the synthetic histories", async () => {
    const user = userEvent.setup();
    window.localStorage.setItem("runrank.participant", String(pid));
    let loaded = false;
    mockFetch(
      (url, init) => {
        if (url.pathname === "/api/demo/histories" && init.method === "POST") {
          loaded = true;
          return json({ messages: ["ok"] });
        }
        if (url.pathname === "/api/participants") return json(loaded ? people : []);
        return undefined;
      },
      base([]),
      mmrHandlers(),
    );
    renderApp("/");
    await user.click(await screen.findByRole("button", { name: "Load synthetic histories" }));
    expect(await screen.findByRole("heading", { name: /Running MMR\s*High evidence coverage/ })).toBeTruthy();
  });

  it("explains a change", async () => {
    mockFetch(base(), (url) => (url.pathname.endsWith("/explain") ? json(fx.explain) : undefined));
    renderApp(`/mmr/explain?runner=${pid}&at=${encodeURIComponent(fx.explain.at_utc)}`);
    expect(await screen.findByText(/New best evidence: activity 750213/)).toBeTruthy();
    expect(screen.getByText("+5.55")).toBeTruthy();
  });

  it("comparison is absolute, ranks only medium/high evidence coverage, separate per data kind", async () => {
    mockFetch(base(), (url) => (url.pathname === "/api/mmr/comparison" ? json(fx.comparison) : undefined));
    renderApp("/mmr/compare");
    const table = await screen.findByRole("table", { name: /Synthetic demo runners: Running MMR/ });
    const rows = within(table).getAllByRole("row").slice(1);
    const endurance = rows.find((r) => within(r).queryByText(/Endurance specialist/))!;
    expect(within(endurance).getByText("unranked")).toBeTruthy();
    expect(within(endurance).getByText("Low evidence coverage")).toBeTruthy();
    expect(screen.getByText(/adding a runner never changes anyone else's number/)).toBeTruthy();
  });

  it("activity detail explains why an easy run did not change MMR", async () => {
    const aid = fx.effect_easy.activity.activity_id;
    mockFetch(base([participant(pid, fx.overview.participant.label, "synthetic")]), (url) => {
      if (url.pathname === `/api/participants/${pid}/activities/${aid}`)
        return json({ participant: { id: pid, label: "x", data_kind: "synthetic" }, activity: {
          id: aid, start_utc: fx.effect_easy.activity.start_utc, name: "SYNTHETIC Run", type: "Run",
          distance_m: fx.effect_easy.activity.distance_m, elapsed_s: fx.effect_easy.activity.elapsed_s, moving_s: null,
          pace_s_per_km: 300, moving_pace_s_per_km: null, avg_hr: null, perceived_exertion: null, elevation_gain_m: null,
          effort: "unknown", counts: false, reasons: [], t5_s: null, points: null, source: "strava_activities_csv",
          first_import_id: 1, first_imported_utc: "2025-01-01T00:00:00Z", first_import_file: "a.csv", last_import_id: 1 },
          annotation: { exclude: false, exclude_note: null, not_duplicate: false, effort: "unknown", updated_utc: null },
          annotation_log: [], contributions: {
            baseline: { version: "best5k-90d-v1", eligible: false, reasons: ["distance"], t5_s: 1, points: 1, best_periods: [] },
            experimental: { version: "riegel-3to21k-90d-exp2", eligible: false, reasons: ["x"], t5_s: 1, points: 1, best_periods: [] } },
          mmr: { version: "mmr-envelope-v2", informative: true, reasons: [], flags: [], t10_s: 3000, points: 1717 } });
      if (url.pathname.endsWith("/effect")) return json(fx.effect_easy);
      return undefined;
    });
    renderApp(`/activities/${aid}?runner=${pid}`);
    expect(await screen.findByText(/an easier or slower run is not read as lower ability/)).toBeTruthy();
  });

  it("the navigation lists the Running MMR pages, the Lab and the method only", async () => {
    mockFetch(base());
    renderApp("/method");
    const nav = await screen.findByRole("navigation", { name: "Main" });
    await waitFor(() => expect(within(nav).getAllByRole("link").length).toBeGreaterThan(0));
    expect(within(nav).getAllByRole("link").map((l) => l.textContent)).toEqual(
      ["Overview", "Activities", "Compare", "Import history", "Ratings Lab Experimental", "How Running MMR works"]);
  });

  it("states that ultras are kept but do not contribute to MMR", async () => {
    const ultra = fx.overview_ultra;
    window.localStorage.setItem("runrank.participant", String(ultra.participant.id));
    mockFetch(base(), (url) => {
      if (url.pathname === `/api/mmr/participants/${ultra.participant.id}`) return json(ultra);
      if (url.pathname.endsWith("/history")) return json(fx.history);
      return undefined;
    });
    renderApp("/");
    const note = await screen.findByText(/do not contribute to Running MMR/);
    const box = note.closest(".notice") as HTMLElement;
    expect(within(box).getByText("3")).toBeTruthy();
    expect(box.textContent).toContain("ultra ability is not represented in this number");
    expect(within(box).getByRole("link", { name: "activities over 42.5 km" }).getAttribute("href")).toBe("/activities?min_km=42.5");
  });
});
