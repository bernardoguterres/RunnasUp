import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { baseHandlers, mockFetch, participant, renderApp } from "../test/utils";

describe("App shell", () => {
  it("has no legacy mode selector, archive section or race pages", async () => {
    mockFetch(baseHandlers([participant(1, "Ana")]));
    renderApp("/activities");
    await screen.findByLabelText("Runner");
    expect(screen.queryByLabelText("Mode")).toBeNull();
    expect(screen.queryByRole("button", { name: "Archive" })).toBeNull();
    expect(screen.queryByRole("link", { name: /Race ratings|5K/ })).toBeNull();
    expect(screen.queryByText(/Experimental, unvalidated/)).toBeNull();
  });

  it("falls back to the first participant when the stored id is unknown", async () => {
    window.localStorage.setItem("runrank.participant", "99");
    mockFetch(baseHandlers([participant(1, "Ana"), participant(2, "Ben")]));
    renderApp("/method");
    const select = (await screen.findByLabelText("Runner")) as HTMLSelectElement;
    expect(select.value).toBe("1");
  });

  it("lets only the Ratings Lab use the full width", async () => {
    mockFetch(baseHandlers([]));
    const { unmount } = renderApp("/lab");
    expect((await screen.findByRole("main")).classList.contains("main--wide")).toBe(true);
    unmount();
    mockFetch(baseHandlers([]));
    renderApp("/method");
    expect((await screen.findByRole("main")).classList.contains("main--wide")).toBe(false);
  });

  it("toggles the mobile menu with aria-expanded", async () => {
    const user = userEvent.setup();
    mockFetch(baseHandlers([]));
    renderApp("/does-not-exist");
    await screen.findByText("Page not found");
    const btn = screen.getByRole("button", { name: "Menu" });
    expect(btn.getAttribute("aria-expanded")).toBe("false");
    await user.click(btn);
    expect(btn.getAttribute("aria-expanded")).toBe("true");
  });
  it("restores focus to the Menu button when the mobile menu is dismissed with Escape", async () => {
    const user = userEvent.setup();
    mockFetch(baseHandlers([]));
    renderApp("/does-not-exist");
    await screen.findByText("Page not found");
    const btn = screen.getByRole("button", { name: "Menu" });
    await user.click(btn);
    expect(btn.getAttribute("aria-expanded")).toBe("true");
    await user.keyboard("{Escape}");
    expect(btn.getAttribute("aria-expanded")).toBe("false");
    expect(document.activeElement).toBe(btn);
  });
});
