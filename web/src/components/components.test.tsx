import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { DataTable } from "./DataTable";
import { Missing, Val } from "./Missing";

interface R {
  name: string;
  t: number | null;
}
const rows: R[] = [
  { name: "B", t: 1500 },
  { name: "A", t: null },
  { name: "C", t: 1400 },
];

function names() {
  const body = screen.getAllByRole("rowgroup")[1];
  return within(body)
    .getAllByRole("row")
    .map((r) => within(r).getAllByRole("cell")[0].textContent);
}

describe("DataTable", () => {
  it("sorts by a column and reflects it in aria-sort; nulls stay last", async () => {
    const user = userEvent.setup();
    render(
      <DataTable<R>
        caption="Runners"
        rows={rows}
        rowKey={(r) => r.name}
        columns={[
          { key: "name", header: "Name", sortValue: (r) => r.name, render: (r) => r.name },
          { key: "t", header: "Time", sortValue: (r) => r.t, render: (r) => <Val value={r.t} /> },
        ]}
      />,
    );
    const nameTh = screen.getByRole("columnheader", { name: /Name/ });
    const timeTh = screen.getByRole("columnheader", { name: /Time/ });
    expect(nameTh.getAttribute("aria-sort")).toBe("none");
    expect(names()).toEqual(["B", "A", "C"]);

    await user.click(within(timeTh).getByRole("button"));
    expect(timeTh.getAttribute("aria-sort")).toBe("ascending");
    expect(nameTh.getAttribute("aria-sort")).toBe("none");
    expect(names()).toEqual(["C", "B", "A"]);

    await user.click(within(timeTh).getByRole("button"));
    expect(timeTh.getAttribute("aria-sort")).toBe("descending");
    expect(names()).toEqual(["B", "C", "A"]);

    await user.click(within(nameTh).getByRole("button"));
    expect(nameTh.getAttribute("aria-sort")).toBe("ascending");
    expect(names()).toEqual(["A", "B", "C"]);
  });

  it("header sort buttons are keyboard operable", async () => {
    const user = userEvent.setup();
    render(
      <DataTable<R>
        caption="Runners"
        rows={rows}
        rowKey={(r) => r.name}
        columns={[{ key: "name", header: "Name", sortValue: (r) => r.name, render: (r) => r.name }]}
      />,
    );
    const btn = screen.getByRole("button", { name: /Name/ });
    btn.focus();
    await user.keyboard("{Enter}");
    expect(screen.getByRole("columnheader", { name: /Name/ }).getAttribute("aria-sort")).toBe("ascending");
  });
});

describe("Missing", () => {
  it('renders an em dash labelled "not recorded", never 0', () => {
    render(
      <p>
        HR: <Val value={null} />
      </p>,
    );
    const m = screen.getByLabelText("not recorded");
    expect(m.textContent).toBe("—");
    expect(m.getAttribute("title")).toBe("not recorded");
    expect(screen.queryByText("0")).toBeNull();
  });

  it("renders 0 when the value really is 0", () => {
    render(<Val value={0} />);
    expect(screen.getByText("0")).toBeTruthy();
    expect(screen.queryByLabelText("not recorded")).toBeNull();
  });

  it("accepts a custom label", () => {
    render(<Missing label="no score" />);
    expect(screen.getByLabelText("no score").textContent).toBe("—");
  });
});
