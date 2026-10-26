import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, isAbortError } from "../api/client";

export interface ApiState<T> {
  data: T | null;
  error: ApiError | null;
  loading: boolean;
  reload: () => void;
}

/**
 * Fetch data for the given inputs.
 * - When `deps` change, the previous request is aborted and its data cleared,
 *   so a slow response for runner A can never be shown while runner B is selected.
 * - Late responses from superseded requests are ignored even if abort is not honoured.
 * - Pass `null` as the fetcher to stay idle (e.g. no participant selected yet).
 */
export function useApi<T>(
  fetcher: ((signal: AbortSignal) => Promise<T>) | null,
  deps: readonly unknown[],
): ApiState<T> {
  // `key` records which inputs the stored result belongs to (see the return statement)
  const key = JSON.stringify([fetcher !== null, ...deps]);
  const [state, setState] = useState<{ data: T | null; error: ApiError | null; loading: boolean; key: string }>(
    { data: null, error: null, loading: fetcher !== null, key },
  );
  const [nonce, setNonce] = useState(0);
  const seq = useRef(0);
  const lastNonce = useRef(nonce);
  const fetcherRef = useRef(fetcher);
  fetcherRef.current = fetcher;

  const enabled = fetcher !== null;

  useEffect(() => {
    const f = fetcherRef.current;
    const id = ++seq.current;
    const isReload = lastNonce.current !== nonce;
    lastNonce.current = nonce;
    if (!f) {
      setState({ data: null, error: null, loading: false, key });
      return;
    }
    const controller = new AbortController();
    // A reload keeps showing the current data; changed inputs clear it.
    setState((s) => ({ data: isReload ? s.data : null, error: null, loading: true, key }));
    f(controller.signal).then(
      (data) => {
        if (id !== seq.current || controller.signal.aborted) return;
        setState({ data, error: null, loading: false, key });
      },
      (e: unknown) => {
        if (id !== seq.current || controller.signal.aborted || isAbortError(e)) return;
        const err =
          e instanceof ApiError
            ? e
            : new ApiError("unknown", e instanceof Error ? e.message : String(e), 0);
        setState({ data: null, error: err, loading: false, key });
      },
    );
    return () => controller.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, nonce, ...deps]);

  const reload = useCallback(() => setNonce((n) => n + 1), []);
  // Until the effect for new inputs has run, the stored result belongs to the old inputs: never expose it
  // (prevents one frame of runner A's data rendering under runner B's name).
  if (state.key !== key) return { data: null, error: null, loading: true, reload };
  return { data: state.data, error: state.error, loading: state.loading, reload };
}
