import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import type { ImportPreview } from "../api/types";
import { baseHandlers, deferred, importRecord, json, mockFetch, participant, renderApp } from "../test/utils";

const preview: ImportPreview = {
  filename: "activities.csv",
  file_error: null,
  rows_total: 3,
  would_insert: 2,
  duplicates: 0,
  conflicts: 0,
  corrected: 0,
  rejected: 1,
  warnings: 0,
  identical_previous_import: null,
  rows: [
    { line: 2, activity_id: "1001", outcome: "inserted", detail: "new", warning: false },
    { line: 3, activity_id: "1002", outcome: "inserted", detail: "new", warning: false },
    { line: 4, activity_id: null, outcome: "rejected", detail: "missing Activity ID", warning: false },
  ],
};

describe("Import page", () => {
  it("previews before importing, disables Import while submitting, and handles duplicate_file", async () => {
    const user = userEvent.setup();
    const prev = importRecord({ id: 3, imported_utc: "2024-03-01T09:00:00Z" });
    const firstPost = deferred<Response>();
    const posts: FormData[] = [];
    const { calls } = mockFetch(baseHandlers([participant(1, "Ana")]), (url, init) => {
      if (url.pathname === "/api/participants/1/imports" && init.method === "POST") {
        posts.push(init.body as FormData);
        if (posts.length === 1) return firstPost.promise;
        return json({ import: importRecord({ id: 8, inserted: 2, rejected: 1 }), rows: preview.rows }, 201);
      }
      if (url.pathname === "/api/participants/1/imports/preview") return json(preview);
      if (url.pathname === "/api/participants/1/imports") return json([]);
      return undefined;
    });

    renderApp("/import");
    await screen.findByLabelText("Import into");
    const importBtn = screen.getByRole("button", { name: "Import" });
    expect((importBtn as HTMLButtonElement).disabled).toBe(true);

    const file = new File(["Activity ID,Activity Date\n"], "activities.csv", { type: "text/csv" });
    await user.upload(screen.getByLabelText(/activities\.csv/), file);

    await screen.findByText("Preview: nothing stored yet");
    expect(screen.getByText("missing Activity ID")).toBeTruthy();
    expect(posts.length).toBe(0);
    expect(calls.some((c) => c.url.pathname.endsWith("/imports/preview"))).toBe(true);

    await waitFor(() => expect((screen.getByRole("button", { name: "Import" }) as HTMLButtonElement).disabled).toBe(false));
    await user.click(screen.getByRole("button", { name: "Import" }));

    const busy = await screen.findByRole("button", { name: "Importing…" });
    expect((busy as HTMLButtonElement).disabled).toBe(true);
    expect(posts.length).toBe(1);
    expect(posts[0].get("confirm_repeat")).toBe("false");

    firstPost.resolve(
      json(
        {
          error: {
            code: "duplicate_file",
            message: "This file was already imported.",
            previous_import: prev,
          },
        },
        409,
      ),
    );

    await screen.findByText("This exact file was already imported");
    expect(screen.getByText(/Import #3/)).toBeTruthy();
    const again = screen.getByRole("checkbox", { name: "Import again anyway" });
    expect((screen.getByRole("button", { name: "Import" }) as HTMLButtonElement).disabled).toBe(true);

    await user.click(again);
    await user.click(screen.getByRole("button", { name: "Import" }));

    await screen.findByText("Imported with issues");
    expect(posts.length).toBe(2);
    expect(posts[1].get("confirm_repeat")).toBe("true");
    expect(posts[1].get("file")).toBeInstanceOf(File);
    // Same file cannot be submitted twice by accident.
    expect((screen.getByRole("button", { name: "Import" }) as HTMLButtonElement).disabled).toBe(true);
  });
});

describe("Import page when the backend is unavailable", () => {
  it("shows an error and never a success message if the import request fails at the network level", async () => {
    const user = userEvent.setup();
    mockFetch(baseHandlers([participant(1, "Ana")]), (url, init) => {
      if (url.pathname === "/api/participants/1/imports/preview") return json(preview);
      if (url.pathname === "/api/participants/1/imports" && init.method === "POST") {
        throw new TypeError("Failed to fetch"); // server stopped between preview and import
      }
      if (url.pathname === "/api/participants/1/imports") return json([]);
      return undefined;
    });
    renderApp("/import");
    await screen.findByLabelText("Import into");
    const file = new File(["Activity ID,Activity Date\n"], "activities.csv", { type: "text/csv" });
    await user.upload(screen.getByLabelText(/activities\.csv/), file);
    await screen.findByText("Preview: nothing stored yet");
    await waitFor(() => expect((screen.getByRole("button", { name: "Import" }) as HTMLButtonElement).disabled).toBe(false));
    await user.click(screen.getByRole("button", { name: "Import" }));
    const alert = await screen.findByRole("alert");
    expect(alert.textContent ?? "").toMatch(/server|network|reach|connect/i);
    // none of the four outcome banners may appear after a failed request
    for (const title of ["Import complete", "Imported with issues", "No new activities", "File rejected: nothing was stored"]) {
      expect(screen.queryByText(title)).toBeNull();
    }
    // the user can retry: the button is usable again, not stuck on "Importing…"
    await waitFor(() => expect((screen.getByRole("button", { name: "Import" }) as HTMLButtonElement).disabled).toBe(false));
  });
});
