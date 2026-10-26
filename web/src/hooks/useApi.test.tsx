import { act, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { deferred } from "../test/utils";
import { useApi } from "./useApi";

describe("useApi", () => {
  it("ignores a stale response after the participant changes", async () => {
    const pending: Record<number, ReturnType<typeof deferred<string>>> = {};
    const aborted: number[] = [];
    function Probe({ pid }: { pid: number }) {
      const r = useApi(
        (signal) => {
          signal.addEventListener("abort", () => aborted.push(pid));
          pending[pid] = deferred<string>();
          return pending[pid].promise; // deliberately ignores the abort signal
        },
        [pid],
      );
      return <p data-testid="out">{r.loading ? "loading" : (r.data ?? "none")}</p>;
    }

    const { rerender } = render(<Probe pid={1} />);
    expect(screen.getByTestId("out").textContent).toBe("loading");

    rerender(<Probe pid={2} />);
    expect(aborted).toContain(1);

    await act(async () => pending[2].resolve("runner 2"));
    expect(screen.getByTestId("out").textContent).toBe("runner 2");

    // The late response for runner 1 must not replace runner 2's data.
    await act(async () => pending[1].resolve("runner 1"));
    expect(screen.getByTestId("out").textContent).toBe("runner 2");
  });

  it("clears data when inputs change so the previous runner is never shown", async () => {
    const pending: Record<number, ReturnType<typeof deferred<string>>> = {};
    function Probe({ pid }: { pid: number }) {
      const r = useApi(() => {
        pending[pid] = deferred<string>();
        return pending[pid].promise;
      }, [pid]);
      return <p data-testid="out">{r.data ?? (r.loading ? "loading" : "none")}</p>;
    }
    const { rerender } = render(<Probe pid={1} />);
    await act(async () => pending[1].resolve("runner 1"));
    expect(screen.getByTestId("out").textContent).toBe("runner 1");
    rerender(<Probe pid={2} />);
    expect(screen.getByTestId("out").textContent).toBe("loading");
  });
});
