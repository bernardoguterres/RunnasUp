import { Fragment, useMemo, useState } from "react";
import type { ReactNode } from "react";

export interface Column<T> {
  key: string;
  header: ReactNode;
  render: (row: T) => ReactNode;
  /** Provide to make the column sortable. null values always sort last. */
  sortValue?: (row: T) => string | number | null;
  align?: "left" | "right";
  /** Accessible header text when `header` is not plain text. */
  headerLabel?: string;
}

export type SortDir = "asc" | "desc";
export interface SortState {
  key: string;
  dir: SortDir;
}

interface Props<T> {
  caption: ReactNode;
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string | number;
  initialSort?: SortState;
  /** Controlled sort (for server-side sorting). When given, rows are not re-sorted locally. */
  sort?: SortState | null;
  onSortChange?: (s: SortState) => void;
  captionHidden?: boolean;
  empty?: ReactNode;
  rowClassName?: (row: T) => string | undefined;
  /** Optional detail row shown under a row (e.g. an expanded activity); null shows nothing. */
  detail?: (row: T) => ReactNode | null;
  /** id prefix for detail rows, so a toggle can point at them with aria-controls */
  detailId?: (row: T) => string;
}

function compare(a: string | number | null, b: string | number | null): number {
  if (a === null && b === null) return 0;
  if (a === null) return 1;
  if (b === null) return -1;
  if (typeof a === "number" && typeof b === "number") return a - b;
  return String(a).localeCompare(String(b), undefined, { numeric: true, sensitivity: "base" });
}

export function DataTable<T>({
  caption,
  columns,
  rows,
  rowKey,
  initialSort,
  sort: controlled,
  onSortChange,
  captionHidden,
  empty,
  rowClassName,
  detail,
  detailId,
}: Props<T>) {
  const [local, setLocal] = useState<SortState | null>(initialSort ?? null);
  const isControlled = controlled !== undefined;
  const sort = isControlled ? controlled : local;

  const sorted = useMemo(() => {
    if (isControlled || !sort) return rows;
    const col = columns.find((c) => c.key === sort.key);
    if (!col?.sortValue) return rows;
    const get = col.sortValue;
    const out = rows.map((r, i) => ({ r, i }));
    out.sort((x, y) => {
      const va = get(x.r);
      const vb = get(y.r);
      // nulls stay last regardless of direction
      if (va === null || vb === null) return compare(va, vb) || x.i - y.i;
      const c = compare(va, vb);
      return (sort.dir === "asc" ? c : -c) || x.i - y.i;
    });
    return out.map((o) => o.r);
  }, [rows, columns, sort, isControlled]);

  function toggle(key: string) {
    const next: SortState =
      sort && sort.key === key
        ? { key, dir: sort.dir === "asc" ? "desc" : "asc" }
        : { key, dir: "asc" };
    if (!isControlled) setLocal(next);
    onSortChange?.(next);
  }

  return (
    <div className="table-wrap" tabIndex={0} role="region" aria-label={typeof caption === "string" ? caption : undefined}>
      <table className="table">
        <caption className={captionHidden ? "visually-hidden" : "table__caption"}>{caption}</caption>
        <thead>
          <tr>
            {columns.map((c) => {
              const active = sort?.key === c.key;
              const ariaSort = c.sortValue
                ? active
                  ? sort!.dir === "asc"
                    ? "ascending"
                    : "descending"
                  : "none"
                : undefined;
              return (
                <th
                  key={c.key}
                  scope="col"
                  aria-sort={ariaSort}
                  className={c.align === "right" ? "is-right" : undefined}
                >
                  {c.sortValue ? (
                    <button
                      type="button"
                      className="th-sort"
                      onClick={() => toggle(c.key)}
                      aria-label={
                        c.headerLabel
                          ? `${c.headerLabel}, sort ${active && sort!.dir === "asc" ? "descending" : "ascending"}`
                          : undefined
                      }
                    >
                      {c.header}
                      <span aria-hidden="true" className="th-sort__icon">
                        {active ? (sort!.dir === "asc" ? "▲" : "▼") : "↕"}
                      </span>
                    </button>
                  ) : (
                    c.header
                  )}
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {sorted.length === 0 ? (
            <tr>
              <td colSpan={columns.length} className="table__empty">
                {empty ?? "No rows."}
              </td>
            </tr>
          ) : (
            sorted.map((r) => {
              const extra = detail?.(r) ?? null;
              return (
                <Fragment key={rowKey(r)}>
                  <tr className={rowClassName?.(r)}>
                    {columns.map((c) => (
                      <td key={c.key} className={c.align === "right" ? "is-right num" : undefined}>
                        {c.render(r)}
                      </td>
                    ))}
                  </tr>
                  {extra !== null ? (
                    <tr className="table__detail" id={detailId?.(r)}>
                      <td colSpan={columns.length}>{extra}</td>
                    </tr>
                  ) : null}
                </Fragment>
              );
            })
          )}
        </tbody>
      </table>
    </div>
  );
}
