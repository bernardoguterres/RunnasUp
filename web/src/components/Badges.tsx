import type { DataKind, Participant } from "../api/types";
import { runnerName } from "../format";

export const KIND_LABEL: Record<DataKind, string> = {
  real: "Real",
  synthetic: "Synthetic demo data",
  unlabelled: "Data kind not recorded",
};

export function KindBadge({ kind }: { kind: DataKind }) {
  const glyph = kind === "real" ? "✓" : kind === "synthetic" ? "◇" : "?";
  const cls = kind === "real" ? "badge--neutral" : kind === "synthetic" ? "badge--synthetic" : "badge--neutral";
  return (
    <span className={`badge ${cls}`}>
      <span aria-hidden="true" className="badge__glyph">
        {glyph}
      </span>
      {KIND_LABEL[kind]}
    </span>
  );
}

const GROUPS: { kind: DataKind; label: string }[] = [
  { kind: "real", label: "Real runners" },
  { kind: "synthetic", label: "Synthetic demo runners" },
  { kind: "unlabelled", label: "Data kind not recorded" },
];

/** <option>s for a runner <select>, grouped by data kind so the kind is stated once per group. */
export function RunnerOptions({ participants }: { participants: Pick<Participant, "id" | "label" | "data_kind">[] }) {
  return (
    <>
      {GROUPS.map(({ kind, label }) => {
        const list = participants.filter((p) => p.data_kind === kind);
        return list.length ? (
          <optgroup key={kind} label={label}>
            {list.map((p) => (
              <option key={p.id} value={p.id}>
                {runnerName(p.label, p.data_kind)}
              </option>
            ))}
          </optgroup>
        ) : null;
      })}
    </>
  );
}

/** Compact "Synthetic" marker used next to runner names in selectors and tables. */
export function SyntheticBadge() {
  return (
    <span className="badge badge--synthetic badge--small" title="Synthetic demo data">
      <span aria-hidden="true" className="badge__glyph">
        ◇
      </span>
      Synthetic
    </span>
  );
}

/** The selected runner's data kind, shown once next to a runner selector. */
export function KindTag({ kind }: { kind: DataKind }) {
  return kind === "synthetic" ? <SyntheticBadge /> : (
    <span className="badge badge--neutral badge--small">{kind === "real" ? "Real data" : "Kind not recorded"}</span>
  );
}
