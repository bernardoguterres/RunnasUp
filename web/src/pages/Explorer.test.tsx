import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import type { ActivityList } from "../api/types";
import { baseHandlers, json, mockFetch, participant, renderApp } from "../test/utils";

const list: ActivityList = {
  participant_id: 1,
  total: 1,
  offset: 0,
  limit: 50,
  types: ["Run", "Ride"],
  rows: [
    {
      id: "1001",
      start_utc: "2024-03-15T07:00:00Z",
      name: "Morning Run",
      type: "Run",
      distance_m: 5000,
      elapsed_s: 1440,
      moving_s: null,
      pace_s_per_km: 288,
      moving_pace_s_per_km: null,
      avg_hr: null,
      perceived_exertion: null,
      elevation_gain_m: null,
      effort: "unknown",
    },
  ],
};

describe("Activity explorer", () => {
  it("writes filters into the URL and requests the API with the same params", async () => {
    const user = userEvent.setup();
    const { calls } = mockFetch(baseHandlers([participant(1, "Ana")]), (url) =>
      url.pathname === "/api/participants/1/activities" ? json(list) : undefined,
    );
    const { router } = renderApp("/activities");
    await screen.findByText("Morning Run");
    const table = screen.getByRole("table");
    expect(within(table).getAllByRole("columnheader").map((h) => h.textContent)).toEqual(
      ["Activity↕", "Date (UTC)▼", "Distance↕", "Elapsed pace↕", "Elapsed time↕", "Details"]);
    // optional fields live in the row expansion; missing values render as "not recorded", not 0
    expect(screen.queryAllByLabelText("not recorded")).toHaveLength(0);
    const toggle = screen.getByRole("button", { name: "Details for Morning Run" });
    await user.click(toggle);
    expect(toggle.getAttribute("aria-expanded")).toBe("true");
    expect(screen.getAllByLabelText("not recorded").length).toBeGreaterThanOrEqual(3);
    expect(screen.queryByText(/Legacy 5K/)).toBeNull();          // the legacy score was archived

    await user.click(screen.getByRole("button", { name: "Filters" }));
    await user.type(screen.getByLabelText("Min"), "4");
    await user.selectOptions(screen.getByLabelText("Type"), "Run");
    await user.type(screen.getByLabelText("Search name or ID"), "tempo");

    await waitFor(() => expect(router.state.location.search).toContain("q=tempo"));
    const sp = new URLSearchParams(router.state.location.search);
    expect(sp.get("min_km")).toBe("4");
    expect(sp.get("type")).toBe("Run");

    await waitFor(() => {
      const last = calls.filter((c) => c.url.pathname === "/api/participants/1/activities").at(-1)!;
      expect(last.url.searchParams.get("q")).toBe("tempo");
    });
    const last = calls.filter((c) => c.url.pathname === "/api/participants/1/activities").at(-1)!;
    expect(last.url.searchParams.get("min_km")).toBe("4");
    expect(last.url.searchParams.get("type")).toBe("Run");
    expect(last.url.searchParams.has("mode")).toBe(false);
    expect(last.url.searchParams.get("limit")).toBe("50");

    const csv = screen.getByRole("link", { name: /Download CSV/ }).getAttribute("href")!;
    const csvParams = new URL(csv, "http://localhost").searchParams;
    expect(csvParams.get("min_km")).toBe("4");
    expect(csvParams.get("q")).toBe("tempo");
    expect(csvParams.get("type")).toBe("Run");
  });

  it("reads filters from the URL on direct load", async () => {
    const { calls } = mockFetch(baseHandlers([participant(1, "Ana")]), (url) =>
      url.pathname === "/api/participants/1/activities" ? json(list) : undefined,
    );
    renderApp("/activities?min_km=4&max_km=6&sort=pace&order=asc&from=2024-03-01");
    await screen.findByText("Morning Run");
    const req = calls.find((c) => c.url.pathname === "/api/participants/1/activities")!;
    expect(req.url.searchParams.get("min_km")).toBe("4");
    expect(req.url.searchParams.get("max_km")).toBe("6");
    expect(req.url.searchParams.get("sort")).toBe("pace");
    expect(req.url.searchParams.get("order")).toBe("asc");
    expect(req.url.searchParams.get("from")).toBe("2024-03-01");
  });
});
