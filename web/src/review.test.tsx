/** Regressions for the critical-review findings (frontend side). */
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import type { ActivityDetail, ImportPreview, MmrComparison, Participant } from "./api/types";
import { baseHandlers, json, mockFetch, participant, renderApp } from "./test/utils";

function detail(p: Participant, id: string): ActivityDetail {
  return {
    participant: { id: p.id, label: p.label, data_kind: p.data_kind },
    activity: {
      id, start_utc: "2024-03-01T07:00:00Z", name: `Run of ${p.label}`, type: "Run", distance_m: 5000,
      elapsed_s: 1500, moving_s: null, pace_s_per_km: 300, moving_pace_s_per_km: null, avg_hr: null,
      perceived_exertion: null, elevation_gain_m: null, effort: "unknown", source: "strava_activities_csv", first_import_id: 1, first_imported_utc: "2024-03-02T00:00:00Z",
      first_import_file: "a.csv", last_import_id: 1,
    },
    annotation: { exclude: false, exclude_note: null, not_duplicate: false, effort: "unknown", updated_utc: null },
    annotation_log: [],
    mmr: { version: "mmr-envelope-v2", informative: true, reasons: [], flags: [], t10_s: 3127.0, points: 1631.8 },
  };
}

describe("critical-review regressions", () => {
  it("D2: a ?runner= link switches runner once, then the selector can change runner again", async () => {
    const user = userEvent.setup();
    window.localStorage.setItem("runrank.participant", "1");
    const ana = participant(1, "Ana");
    const ben = participant(2, "Ben");
    mockFetch(baseHandlers([ana, ben]), (url) => {
      const m = url.pathname.match(/^\/api\/participants\/(\d)\/activities\/(\w+)$/);
      if (m) return json(detail(m[1] === "1" ? ana : ben, m[2]));
      return undefined;
    });
    renderApp("/activities/7001?runner=2");
    const select = (await screen.findByLabelText("Runner")) as HTMLSelectElement;
    await waitFor(() => expect(select.value).toBe("2"));
    await screen.findAllByText("Run of Ben");
    await user.selectOptions(select, "1");
    await screen.findAllByText("Run of Ana");
    expect(select.value).toBe("1"); // previously snapped back to the linked runner
  });

  it("D3: the preview is re-run with apply_corrections when the box is ticked", async () => {
    const user = userEvent.setup();
    const sent: string[] = [];
    const preview: ImportPreview = {
      filename: "a.csv", file_error: null, rows_total: 1, would_insert: 0, duplicates: 0, conflicts: 1,
      corrected: 0, rejected: 0, warnings: 0, identical_previous_import: null,
      rows: [{ line: 2, activity_id: "1003", outcome: "conflict", detail: "differs", warning: false }],
    };
    mockFetch(baseHandlers([participant(1, "Ana")]), (url, init) => {
      if (url.pathname === "/api/participants/1/imports/preview") {
        const flag = String((init.body as FormData).get("apply_corrections"));
        sent.push(flag);
        return json(flag === "true" ? { ...preview, conflicts: 0, corrected: 1 } : preview);
      }
      if (url.pathname === "/api/participants/1/imports") return json([]);
      return undefined;
    });
    renderApp("/import");
    await screen.findByLabelText("Import into");
    await user.upload(screen.getByLabelText(/activities\.csv/), new File(["x"], "a.csv", { type: "text/csv" }));
    await screen.findByText("Preview: nothing stored yet");
    await user.click(screen.getByRole("checkbox", { name: /Apply corrections/ }));
    await waitFor(() => expect(sent).toEqual(["false", "true"]));
  });

  it("D9: navigation updates the document title and moves focus to the main region", async () => {
    const user = userEvent.setup();
    const cmp: MmrComparison = { version: "mmr-envelope-v2", scale_version: "mmr-scale-v1", as_of: null,
      ranking_rule: "rule", rows: [] };
    mockFetch(baseHandlers([participant(1, "Ana")]), (url) =>
      url.pathname === "/api/mmr/comparison" ? json(cmp) : undefined,
    );
    renderApp("/method");
    await waitFor(() => expect(document.title).toBe("How Running MMR works · RunnasUP"));
    await user.click(screen.getByRole("link", { name: "Compare" }));
    await waitFor(() => expect(document.title).toBe("Compare Running MMR · RunnasUP"));
    expect(document.activeElement?.id).toBe("main");
  });
});
