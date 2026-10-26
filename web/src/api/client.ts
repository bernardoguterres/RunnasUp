/**
 * Typed fetch wrapper for the RunnasUP local API.
 * Every number shown in the UI comes from these responses; nothing here
 * computes ratings.
 */
import type {
  ActivityDetail,
  ActivityList,
  ActivitySort,
  AnnotationUpdate,
  ApiErrorBody,
  CreateParticipant,
  Health,
  ImportPreview,
  ImportRecord,
  ImportResult,
  LabCompare,
  LabExplanation,
  LabMeta,
  LabMethod,
  LabParams,
  LabRunner,
  LabStoredRunners,
  MmrComparison,
  MmrEffect,
  MmrExplanation,
  MmrHistory,
  MmrMethod,
  MmrObservation,
  MmrOverview,
  Participant,
  SortOrder,
} from "./types";

export type ApiErrorCode = ApiErrorBody["error"]["code"] | "network" | "unknown";

export class ApiError extends Error {
  readonly code: ApiErrorCode;
  readonly status: number;
  readonly field?: string;
  readonly previous_import?: ImportRecord;

  constructor(
    code: ApiErrorCode,
    message: string,
    status: number,
    extra: { field?: string; previous_import?: ImportRecord } = {},
  ) {
    super(message);
    this.name = "ApiError";
    this.code = code;
    this.status = status;
    this.field = extra.field;
    this.previous_import = extra.previous_import;
  }
}

export function isAbortError(e: unknown): boolean {
  return (
    typeof e === "object" &&
    e !== null &&
    "name" in e &&
    (e as { name: unknown }).name === "AbortError"
  );
}

type QueryValue = string | number | boolean | null | undefined;
export type Query = Record<string, QueryValue>;

/** Build "?a=1&b=2", skipping null/undefined/empty-string values. */
export function buildQuery(params: Query): string {
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === null || v === undefined || v === "") continue;
    sp.set(k, String(v));
  }
  const s = sp.toString();
  return s ? `?${s}` : "";
}

interface RequestOptions {
  method?: "GET" | "POST" | "PUT";
  query?: Query;
  json?: unknown;
  form?: FormData;
  signal?: AbortSignal;
}

async function parseError(res: Response): Promise<ApiError> {
  let body: unknown = null;
  try {
    body = await res.json();
  } catch {
    body = null;
  }
  const err =
    body && typeof body === "object" && "error" in body
      ? (body as ApiErrorBody).error
      : null;
  if (err && typeof err.message === "string") {
    return new ApiError(err.code ?? "unknown", err.message, res.status, {
      field: err.field,
      previous_import: err.previous_import,
    });
  }
  return new ApiError(
    "unknown",
    `The server answered ${res.status}${res.statusText ? ` ${res.statusText}` : ""}.`,
    res.status,
  );
}

export async function request<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const url = `/api${path}${opts.query ? buildQuery(opts.query) : ""}`;
  const headers: Record<string, string> = { Accept: "application/json" };
  let body: BodyInit | undefined;
  if (opts.form) {
    body = opts.form; // browser sets the multipart boundary
  } else if (opts.json !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(opts.json);
  }
  let res: Response;
  try {
    res = await fetch(url, {
      method: opts.method ?? "GET",
      headers,
      body,
      signal: opts.signal,
    });
  } catch (e) {
    if (isAbortError(e)) throw e;
    throw new ApiError(
      "network",
      "Could not reach the RunnasUP server at 127.0.0.1:8600. Is it running?",
      0,
    );
  }
  if (!res.ok) throw await parseError(res);
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

// ------------------------------------------------------------------ filters

export interface ActivityFilters {
  q?: string;
  from?: string;
  to?: string;
  min_km?: string | number;
  max_km?: string | number;
  type?: string;
  sort?: ActivitySort;
  order?: SortOrder;
}

export interface ActivityQuery extends ActivityFilters {
  limit?: number;
  offset?: number;
}

const P = (pid: number) => `/participants/${encodeURIComponent(String(pid))}`;

// ------------------------------------------------------------------ endpoints

export const api = {
  health: (signal?: AbortSignal) => request<Health>("/health", { signal }),

  participants: (signal?: AbortSignal) => request<Participant[]>("/participants", { signal }),

  createParticipant: (body: CreateParticipant, signal?: AbortSignal) =>
    request<Participant>("/participants", { method: "POST", json: body, signal }),

  activities: (pid: number, q: ActivityQuery, signal?: AbortSignal) =>
    request<ActivityList>(`${P(pid)}/activities`, { query: { ...q }, signal }),

  activity: (pid: number, id: string, signal?: AbortSignal) =>
    request<ActivityDetail>(`${P(pid)}/activities/${encodeURIComponent(id)}`, { signal }),

  putAnnotation: (pid: number, id: string, body: AnnotationUpdate, signal?: AbortSignal) =>
    request<ActivityDetail>(`${P(pid)}/activities/${encodeURIComponent(id)}/annotation`, {
      method: "PUT",
      json: body,
      signal,
    }),

  previewImport: (pid: number, file: File, applyCorrections = false, signal?: AbortSignal) => {
    const form = new FormData();
    form.append("file", file, file.name);
    form.append("apply_corrections", applyCorrections ? "true" : "false");
    return request<ImportPreview>(`${P(pid)}/imports/preview`, {
      method: "POST",
      form,
      signal,
    });
  },

  importFile: (
    pid: number,
    file: File,
    opts: { apply_corrections: boolean; confirm_repeat: boolean },
    signal?: AbortSignal,
  ) => {
    const form = new FormData();
    form.append("file", file, file.name);
    form.append("apply_corrections", opts.apply_corrections ? "true" : "false");
    form.append("confirm_repeat", opts.confirm_repeat ? "true" : "false");
    return request<ImportResult>(`${P(pid)}/imports`, { method: "POST", form, signal });
  },

  imports: (pid: number, signal?: AbortSignal) =>
    request<ImportRecord[]>(`${P(pid)}/imports`, { signal }),

  importDetail: (id: number, signal?: AbortSignal) =>
    request<ImportResult>(`/imports/${encodeURIComponent(String(id))}`, { signal }),

  // ---------------------------------------------------------------- Ratings Lab (experimental; synthetic or stored, read-only)
  labMeta: (signal?: AbortSignal) => request<LabMeta>("/lab/meta", { signal }),

  labRunner: (key: string, method: LabMethod, params: LabParams, signal?: AbortSignal) =>
    request<LabRunner>(`/lab/runners/${encodeURIComponent(key)}`, { query: { method, ...params }, signal }),

  labActivity: (key: string, aid: string, method: LabMethod, params: LabParams, signal?: AbortSignal) =>
    request<LabExplanation>(`/lab/runners/${encodeURIComponent(key)}/activities/${encodeURIComponent(aid)}`, {
      query: { method, ...params },
      signal,
    }),

  labCompare: (signal?: AbortSignal) => request<LabCompare>("/lab/compare", { signal }),

  /** stored histories in the database this app was started with (read-only connection on the server) */
  labDbRunners: (signal?: AbortSignal) => request<LabStoredRunners>("/lab/db/runners", { signal }),

  labDbRunner: (pid: number, method: LabMethod, params: LabParams, signal?: AbortSignal) =>
    request<LabRunner>(`/lab/db/runners/${encodeURIComponent(String(pid))}`, { query: { method, ...params }, signal }),

  labDbActivity: (pid: number, aid: string, method: LabMethod, params: LabParams, signal?: AbortSignal) =>
    request<LabExplanation>(
      `/lab/db/runners/${encodeURIComponent(String(pid))}/activities/${encodeURIComponent(aid)}`,
      { query: { method, ...params }, signal },
    ),

  // ---------------------------------------------------------------- Running MMR
  mmr: (pid: number, asOf: string | undefined, signal?: AbortSignal) =>
    request<MmrOverview>(`/mmr/participants/${encodeURIComponent(String(pid))}`, { query: { as_of: asOf }, signal }),

  mmrHistory: (pid: number, signal?: AbortSignal) =>
    request<MmrHistory>(`/mmr/participants/${encodeURIComponent(String(pid))}/history`, { signal }),

  mmrObservations: (pid: number, signal?: AbortSignal) =>
    request<MmrObservation[]>(`/mmr/participants/${encodeURIComponent(String(pid))}/observations`, { signal }),

  mmrExplain: (pid: number, at: string, signal?: AbortSignal) =>
    request<MmrExplanation>(`/mmr/participants/${encodeURIComponent(String(pid))}/explain`, { query: { at }, signal }),

  mmrEffect: (pid: number, aid: string, signal?: AbortSignal) =>
    request<MmrEffect>(
      `/mmr/participants/${encodeURIComponent(String(pid))}/activities/${encodeURIComponent(aid)}/effect`,
      { signal },
    ),

  mmrComparison: (asOf: string | undefined, signal?: AbortSignal) =>
    request<MmrComparison>("/mmr/comparison", { query: { as_of: asOf }, signal }),

  mmrMethod: (signal?: AbortSignal) => request<MmrMethod>("/mmr/method", { signal }),

  loadDemoHistories: (signal?: AbortSignal) =>
    request<{ messages: string[] }>("/demo/histories", { method: "POST", signal }),

};

// ------------------------------------------------------------------ CSV links

export const csvUrl = {
  activities: (pid: number, q: ActivityFilters) => `/api${P(pid)}/activities.csv${buildQuery({ ...q })}`,
};
