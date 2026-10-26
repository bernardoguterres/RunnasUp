import type { ReactNode } from "react";
import { MISSING_LABEL, MISSING_TEXT } from "../format";

/** Rendering for a null value: an em dash announced as "not recorded". Never 0. */
export function Missing({ label = MISSING_LABEL }: { label?: string }) {
  return (
    <span className="missing" aria-label={label} title={label} role="img">
      {MISSING_TEXT}
    </span>
  );
}

/** Shows `value` (already formatted) or <Missing/> when it is null/undefined. */
export function Val({
  value,
  suffix,
  label,
}: {
  value: ReactNode | null | undefined;
  suffix?: string;
  label?: string;
}) {
  if (value === null || value === undefined || value === "") return <Missing label={label} />;
  return (
    <span className="num">
      {value}
      {suffix ? ` ${suffix}` : ""}
    </span>
  );
}
