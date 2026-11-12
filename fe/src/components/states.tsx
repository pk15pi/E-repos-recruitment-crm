import type { ReactNode } from "react";

export function Loading({ label = "Loading" }: { label?: string }) {
  return (
    <p className="text-sm text-muted" role="status">
      {label}…
    </p>
  );
}

export function Empty({ title, body, action }: { title: string; body: string; action?: ReactNode }) {
  return (
    <div className="rounded-lg border border-dashed border-line bg-card px-4 py-8 text-center">
      <h2 className="text-2xl">{title}</h2>
      <p className="mx-auto mt-2 max-w-md text-sm text-muted">{body}</p>
      {action ? <div className="mt-4">{action}</div> : null}
    </div>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div role="alert" className="rounded-lg border border-danger/30 bg-red-50 px-4 py-3 text-sm text-danger">
      <p>{message}</p>
      {onRetry ? (
        <button type="button" className="mt-2 underline" onClick={onRetry}>
          Try again
        </button>
      ) : null}
    </div>
  );
}

export function Missing({ value, hidden = false }: { value: unknown; hidden?: boolean }) {
  if (hidden) return <span className="text-muted">Not shared</span>;
  if (value === null || value === undefined || value === "") return <span className="text-muted">Not provided</span>;
  return <>{String(value)}</>;
}
