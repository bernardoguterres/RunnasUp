import type { ReactNode } from "react";
import type { ApiError } from "../api/client";

export function Loading({ label = "Loading…", rows = 3 }: { label?: string; rows?: number }) {
  return (
    <div className="loading" role="status" aria-live="polite">
      <span className="loading__text">{label}</span>
      <div aria-hidden="true">
        {Array.from({ length: rows }, (_, i) => (
          <div key={i} className="skeleton-row" />
        ))}
      </div>
    </div>
  );
}

export function ErrorState({
  error,
  onRetry,
  title = "Something went wrong",
}: {
  error: ApiError | Error | null;
  onRetry?: () => void;
  title?: string;
}) {
  return (
    <div className="notice notice--danger" role="alert">
      <p className="notice__title">
        <span aria-hidden="true">✕ </span>
        {title}
      </p>
      <p>{error?.message ?? "Unknown error."}</p>
      {onRetry ? (
        <button type="button" className="btn" onClick={onRetry}>
          Retry
        </button>
      ) : null}
    </div>
  );
}

export function EmptyState({
  title,
  children,
  action,
}: {
  title: string;
  children?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <div className="empty">
      <p className="empty__title">{title}</p>
      {children ? <div className="empty__body">{children}</div> : null}
      {action ? <div className="empty__action">{action}</div> : null}
    </div>
  );
}

export function Notice({
  tone,
  title,
  children,
  role,
}: {
  tone: "success" | "warning" | "danger" | "info";
  title?: ReactNode;
  children?: ReactNode;
  role?: "status" | "alert";
}) {
  const glyph = { success: "✓", warning: "!", danger: "✕", info: "i" }[tone];
  return (
    <div className={`notice notice--${tone}`} role={role}>
      {title ? (
        <p className="notice__title">
          <span aria-hidden="true" className="notice__glyph">
            {glyph}
          </span>{" "}
          {title}
        </p>
      ) : null}
      {children}
    </div>
  );
}
