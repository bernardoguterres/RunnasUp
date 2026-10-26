import type { ReactNode } from "react";

export function Metric({
  label,
  value,
  unit,
  hint,
}: {
  label: string;
  value: ReactNode;
  unit?: string;
  hint?: ReactNode;
}) {
  return (
    <div className="metric">
      <dt className="metric__label">{label}</dt>
      <dd className="metric__value">
        <span className="num">{value}</span>
        {unit ? <span className="metric__unit"> {unit}</span> : null}
      </dd>
      {hint ? <dd className="metric__hint">{hint}</dd> : null}
    </div>
  );
}
