import { render } from "@testing-library/react";
import { createMemoryRouter, RouterProvider } from "react-router";
import { vi } from "vitest";
import type { Health, ImportRecord, Participant } from "../api/types";
import { routes } from "../routes";
import { AppStateProvider } from "../state/AppState";

export type Handler = (url: URL, init: RequestInit) => Response | Promise<Response> | undefined;

export function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

export interface Call {
  url: URL;
  init: RequestInit;
}

/** Install a fetch mock. Handlers are tried in order; unmatched requests fail the test loudly. */
export function mockFetch(...handlers: Handler[]) {
  const calls: Call[] = [];
  const fn = vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
    const url = new URL(String(input), "http://localhost");
    calls.push({ url, init });
    for (const h of handlers) {
      const r = await h(url, init);
      if (r) return r;
    }
    return json({ error: { code: "not_found", message: `unmocked ${init.method ?? "GET"} ${url.pathname}` } }, 404);
  });
  vi.stubGlobal("fetch", fn);
  return { fn, calls };
}

export const health: Health = {
  ok: true,
  database: "personal",
  demo_mode: false,
  schema_version: "5",
  reference_date: "2024-03-31",
  mmr_version: "mmr-envelope-v2",
};

export function participant(id: number, label: string, kind: Participant["data_kind"] = "real"): Participant {
  return {
    id,
    label,
    data_kind: kind,
    created_utc: "2024-01-01T00:00:00Z",
    activity_count: 3,
    first_activity_utc: "2024-03-01T07:00:00Z",
    last_activity_utc: "2024-03-20T07:00:00Z",
    last_import_utc: "2024-03-21T10:00:00Z",
  };
}

export function importRecord(over: Partial<ImportRecord> = {}): ImportRecord {
  return {
    id: 7,
    participant_id: 1,
    filename: "activities.csv",
    imported_utc: "2024-03-21T10:00:00Z",
    status: "completed",
    message: null,
    rows_total: 3,
    inserted: 3,
    duplicates: 0,
    conflicts: 0,
    corrected: 0,
    rejected: 0,
    warnings: 0,
    ...over,
  };
}

/** Basic app handlers: health and the participant list. */
export function baseHandlers(participants: Participant[]): Handler {
  return (url, init) => {
    if (url.pathname === "/api/health") return json(health);
    if (url.pathname === "/api/participants" && (init.method ?? "GET") === "GET") return json(participants);
    return undefined;
  };
}

export function renderApp(path: string) {
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  const utils = render(
    <AppStateProvider>
      <RouterProvider router={router} />
    </AppStateProvider>,
  );
  return { router, ...utils };
}

export function deferred<T>() {
  let resolve!: (v: T) => void;
  let reject!: (e: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}
