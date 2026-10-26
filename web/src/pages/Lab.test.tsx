/** Ratings Lab page. Fixtures are real API responses (tools/export_fixtures.py); SYNTHETIC data only
 * (built-in runners, and a disposable database filled through the importer with a synthetic CSV). */
import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import fx from "../test/fixtures/lab.json";
import { baseHandlers, json, mockFetch, renderApp } from "../test/utils";

function lab(calls: URL[]) {
  return (url: URL) => {
    if (!url.pathname.startsWith("/api/lab")) return undefined;
    calls.push(url);
    if (url.pathname === "/api/lab/meta") return json(fx.meta);
    if (url.pathname === "/api/lab/compare") return json(fx.compare);
    if (url.pathname.includes("/activities/")) return json(fx.explain_8k);
    if (url.pathname === "/api/lab/runners/beginner")
      return json(url.searchParams.get("method") === "C" ? fx.runner_C : fx.runner_B);
    if (url.pathname === "/api/lab/db/runners") return json(fx.db_runners);
    if (url.pathname.startsWith("/api/lab/db/runners/")) {
      const asOf = url.searchParams.get("as_of");
      if (url.searchParams.get("exclude_effort")) return json(fx.db_runner_effort);
      if (url.searchParams.get("exclude")) return json(fx.db_runner_recording);
      if (asOf === "2026-01-20") return json(fx.db_runner_old);
      if (asOf) return json(fx.db_runner);
      // no as_of: the server defaults to today; the fixture was generated with an explicit date
      return json({ ...fx.db_runner, source: { ...fx.db_runner.source, as_of_basis: "today (default)" } });
    }
    return undefined;
  };
}

describe("Ratings Lab", () => {
  it("is clearly experimental, shows components and the input history, and explains the 8 km run", async () => {
    const user = userEvent.setup();
    const calls: URL[] = [];
    mockFetch(baseHandlers([]), lab(calls));
    renderApp("/lab");
    expect(await screen.findByText("Experimental · changes are not saved.")).toBeTruthy();
    expect(screen.getByText(/Nothing changes your stored activities, Running MMR or race Elo/)).toBeTruthy();
    const table = await screen.findByRole("table", { name: /Input history: Beginner/ });
    const eightRow = within(table).getAllByRole("row").find((r) => within(r).queryAllByText("8.00 km").length > 0)!;
    await user.click(within(eightRow).getByRole("button", { name: /Explain activity/ }));
    expect(await screen.findByText(/Endurance evidence: 8 km recorded × running pace 1.00/)).toBeTruthy();
    expect(screen.getByText(/no method in this lab changes points because of a label/)).toBeTruthy();
  });

  it("switching method or a predeclared parameter re-requests with exactly those values", async () => {
    const user = userEvent.setup();
    const calls: URL[] = [];
    mockFetch(baseHandlers([]), lab(calls));
    renderApp("/lab");
    await screen.findByRole("table", { name: /Input history/ });
    expect(screen.getByRole("option", { name: "25 % performance · 75 % endurance" })).toBeTruthy();
    await user.selectOptions(screen.getByLabelText("Performance weight"), "0.25");
    await waitFor(() => expect(calls.some((u) => u.searchParams.get("speed_weight") === "0.25")).toBe(true));
    await user.selectOptions(screen.getByLabelText("Method"), "C");
    await waitFor(() => expect(calls.some((u) => u.searchParams.get("method") === "C"
      && u.searchParams.get("aggregation") === "specialist")).toBe(true));
    expect(await screen.findByText("short")).toBeTruthy();
  });

  it("compare view lists every runner under every configuration and the computed trade-offs", async () => {
    const user = userEvent.setup();
    mockFetch(baseHandlers([]), lab([]));
    renderApp("/lab");
    await user.click(await screen.findByRole("button", { name: "Compare runners" }));
    const table = await screen.findByRole("table", { name: /Combined scores as of/ });
    expect(within(table).getAllByRole("row")).toHaveLength(8);
    expect(screen.getByText(/Who benefits from more endurance weight/)).toBeTruthy();
    expect(screen.getByText(/ultra runner adds one slow 6 km jog/)).toBeTruthy();
  });

  it("Exclude re-requests the runner with that activity excluded (Lab view only)", async () => {
    const user = userEvent.setup();
    const calls: URL[] = [];
    mockFetch(baseHandlers([]), lab(calls));
    renderApp("/lab");
    const table = await screen.findByRole("table", { name: /Input history/ });
    const first = within(table).getAllByRole("row")[1];
    await user.click(within(first).getByRole("button", { name: /Exclude activity/ }));
    await waitFor(() => expect(calls.some((u) => (u.searchParams.get("exclude") ?? "").length > 0)).toBe(true));
    // the exclusion panel is driven by the server's response (see the recording/effort test)
  });

  it("a flagged activity that sets a component shows a warning next to the score; exclude and restore update it", async () => {
    const user = userEvent.setup();
    mockFetch(baseHandlers([]), (url) => {
      if (url.pathname === "/api/lab/meta") return json(fx.meta);
      if (url.pathname === "/api/lab/runners/marathon")
        return json(url.searchParams.get("exclude") ? fx.marathon_excluded : fx.marathon_bridged);
      if (url.pathname.startsWith("/api/lab/runners/")) return json(fx.runner_B);
      return undefined;
    });
    renderApp("/lab");
    await user.selectOptions(await screen.findByLabelText("Fictional runner"), "marathon");
    await user.click(screen.getByText(/^Advanced settings/));
    await user.selectOptions(screen.getByLabelText("Runs over 42.5 km"), "bridged");
    const warn = await screen.findByRole("note", { name: "Warning for performance" });
    expect(warn.textContent).toContain("set by flagged activity 930265");
    expect(screen.getByRole("heading", { name: "How this score is determined" })).toBeTruthy();
    const table = screen.getByRole("table", { name: /Input history/ });
    await user.click(within(table).getByRole("button", { name: "Exclude activity 930265 in the Lab" }));
    expect(await screen.findByText(/Excluded in this Lab view only/)).toBeTruthy();
    await waitFor(() => expect(screen.queryByRole("note", { name: "Warning for performance" })).toBeNull());
    await user.click(screen.getByRole("button", { name: "Include all again" }));
    expect(await screen.findByRole("note", { name: "Warning for performance" })).toBeTruthy();
  });

  it("starts on the synthetic examples and reads the database only after the user selects it", async () => {
    const user = userEvent.setup();
    const calls: URL[] = [];
    mockFetch(baseHandlers([]), lab(calls));
    renderApp("/lab");
    await screen.findByRole("table", { name: /Input history: Beginner/ });
    expect(calls.some((u) => u.pathname.startsWith("/api/lab/db"))).toBe(false);
    expect((screen.getByRole("radio", { name: /Built-in synthetic examples/ }) as HTMLInputElement).checked).toBe(true);
    await user.click(screen.getByRole("radio", { name: /Histories in the currently selected application database: the personal database/ }));
    const status = await screen.findByRole("status", { name: "Active source" });
    expect(status.textContent).toContain("Histories in the currently selected application database: the personal database");
    expect(status.textContent).toContain("Lab check (synthetic)");
    expect(status.textContent).toContain("today (default)");
    expect(status.textContent).toContain("ratings-lab-exp5");
    expect(status.textContent).toContain("Performance weight: 50 % performance · 50 % endurance");
    expect(status.textContent).toContain("speed_weight=0.5");
    expect(screen.getByRole("option", { name: "Lab check · synthetic, 9 activities" })).toBeTruthy();
    // the first request carries no as_of, so the server's default (today) applies
    expect(calls.find((u) => u.pathname.startsWith("/api/lab/db/runners/"))!.searchParams.get("as_of")).toBeNull();
    const table = await screen.findByRole("table", { name: /Input history: Lab check \(synthetic\) \(9 stored activities/ });
    const rows = within(table).getAllByRole("row");
    const stored = rows.find((r) => r.textContent!.includes("excluded (stored)"))!;
    expect(stored.textContent).toContain("synthetic watch glitch");
    expect(within(stored).queryByRole("button", { name: /Exclude activity/ })).toBeNull();
    expect(rows.find((r) => r.textContent!.includes("id 9007"))!.textContent).toContain("unsupported");
    expect(rows.find((r) => r.textContent!.includes("id 9005"))!.textContent).toContain("stored: not a duplicate");
    expect(rows.find((r) => r.textContent!.includes("id 9002"))!.textContent).toContain("missing: moving time");
    expect(screen.getByText("1790")).toBeTruthy();
  });

  it("an explicit as-of date re-requests with that date and explains old evidence instead of showing zero", async () => {
    const user = userEvent.setup();
    const calls: URL[] = [];
    mockFetch(baseHandlers([]), lab(calls));
    renderApp("/lab");
    await user.click(await screen.findByRole("radio", { name: /Histories in the currently selected application database/ }));
    const date = await screen.findByLabelText("As of (UTC date)");
    await screen.findByRole("status", { name: "Active source" });
    fireEvent.change(date, { target: { value: "2026-01-20" } });   // jsdom: date inputs take a change event
    await waitFor(() => expect(calls.some((u) => u.searchParams.get("as_of") === "2026-01-20")).toBe(true));
    expect(await screen.findByText(/No current score: on or before the as-of date, 1 activity is older than 365 days/)).toBeTruthy();
    expect(screen.getAllByText("missing evidence (not zero)").length).toBeGreaterThan(0);
    expect(screen.getByRole("status", { name: "Active source" }).textContent).toContain("explicit date");
  });

  it("distinguishes excluding a recording from excluding the effort, with ids and score impact", async () => {
    const user = userEvent.setup();
    const calls: URL[] = [];
    mockFetch(baseHandlers([]), lab(calls));
    renderApp("/lab");
    await user.click(await screen.findByRole("radio", { name: /Histories in the currently selected application database/ }));
    const table = await screen.findByRole("table", { name: /stored activities/ });
    const row = within(table).getAllByRole("row").find((r) => r.textContent!.includes("id 9001"))!;
    // 9001 and 9003 are one effort recorded twice (db ids 1 and 3); 9004 is stored as separate, so no effort button
    const nine004 = within(table).getAllByRole("row").find((r) => r.textContent!.includes("id 9004"))!;
    expect(within(nine004).queryByRole("button", { name: /Exclude the effort/ })).toBeNull();
    await user.click(within(row).getByRole("button", { name: "Exclude activity 1 in the Lab" }));
    const panel = await screen.findByRole("region", { name: "Lab exclusions" });
    expect(panel.textContent).toContain("recording 1");
    expect(panel.textContent).toContain("Removed activity ids: 1.");
    expect(panel.textContent).toMatch(/speed 1924 → 1917/);
    await user.click(within(panel).getByRole("button", { name: "Include all again" }));
    await waitFor(() => expect(screen.queryByRole("region", { name: "Lab exclusions" })).toBeNull());
    const row2 = within(screen.getByRole("table", { name: /stored activities/ })).getAllByRole("row")
      .find((r) => r.textContent!.includes("id 9001"))!;
    await user.click(within(row2).getByRole("button", { name: "Exclude the effort of activity 1 (recordings 1, 3)" }));
    await waitFor(() => expect(calls.some((u) => u.searchParams.get("exclude_effort") === "1")).toBe(true));
    const p2 = await screen.findByRole("region", { name: "Lab exclusions" });
    expect(p2.textContent).toContain("effort of 1 (recordings 1, 3)");
    expect(p2.textContent).toContain("Removed activity ids: 1, 3.");
    expect(p2.textContent).toMatch(/speed 1924 → 1814/);
  });
});
