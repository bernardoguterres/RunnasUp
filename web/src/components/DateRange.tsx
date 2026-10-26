import { useId } from "react";

/** Two labelled UTC date inputs (inclusive). Empty string means "open". */
export function DateRange({
  from,
  to,
  onChange,
  legend = "Date range (UTC)",
}: {
  from: string;
  to: string;
  onChange: (from: string, to: string) => void;
  legend?: string;
}) {
  const id = useId();
  const invalid = from && to && from > to;
  return (
    <fieldset className="daterange">
      <legend className="field__label">{legend}</legend>
      <div className="daterange__inputs">
        <label className="field field--inline" htmlFor={`${id}-from`}>
          <span>From</span>
          <input
            id={`${id}-from`}
            type="date"
            value={from}
            max={to || undefined}
            onChange={(e) => onChange(e.target.value, to)}
          />
        </label>
        <label className="field field--inline" htmlFor={`${id}-to`}>
          <span>To</span>
          <input
            id={`${id}-to`}
            type="date"
            value={to}
            min={from || undefined}
            onChange={(e) => onChange(from, e.target.value)}
          />
        </label>
      </div>
      {invalid ? (
        <p className="field__error" role="alert">
          "From" is after "To".
        </p>
      ) : null}
    </fieldset>
  );
}
