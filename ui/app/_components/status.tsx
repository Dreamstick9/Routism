// Shared dashboard primitives: loading skeleton, status dot/badge, empty/error
// states. Pure presentational (no hooks).

export function Skeleton({ className = "" }: { className?: string }) {
  return (
    <div
      className={`animate-pulse rounded-[var(--radius-sm)] bg-[var(--border)] ${className}`}
      aria-hidden="true"
    />
  );
}

export function StatusDot({ status }: { status: "up" | "down" | "unknown" }) {
  const color =
    status === "up"
      ? "bg-[var(--good)] shadow-[0_0_0_3px_var(--good-bg)]"
      : status === "down"
        ? "bg-[var(--bad)] shadow-[0_0_0_3px_var(--bad-bg)]"
        : "bg-[var(--muted-soft)]";
  return (
    <span
      className={`inline-block h-2 w-2 shrink-0 rounded-full ${color}`}
      title={status}
      aria-label={status}
    />
  );
}

export function Badge({
  tone = "neutral",
  children,
}: {
  tone?: "neutral" | "good" | "bad" | "warn";
  children: React.ReactNode;
}) {
  const toneClass =
    tone === "good"
      ? "border-[var(--good-border)] bg-[var(--good-bg)] text-[var(--good)]"
      : tone === "bad"
        ? "border-[var(--bad-border)] bg-[var(--bad-bg)] text-[var(--bad)]"
        : tone === "warn"
          ? "border-[var(--warn-border)] bg-[var(--warn-bg)] text-[var(--warn)]"
          : "border-[var(--border)] bg-[var(--background-elevated)] text-[var(--muted)]";
  return (
    <span
      className={`inline-flex items-center rounded-[var(--radius-pill)] border px-2 py-0.5 text-[0.7rem] font-medium tracking-wide ${toneClass}`}
    >
      {children}
    </span>
  );
}

export function EmptyState({
  title,
  children,
}: {
  title: string;
  children?: React.ReactNode;
}) {
  return (
    <div className="card rounded-[var(--radius)] border-dashed p-10 text-center">
      <div className="mx-auto mb-3 flex h-10 w-10 items-center justify-center rounded-full bg-[var(--accent-soft)] text-[var(--accent)]">
        <span className="text-lg" aria-hidden>
          ◌
        </span>
      </div>
      <p className="font-medium text-[var(--foreground)]">{title}</p>
      {children && (
        <div className="mx-auto mt-1.5 max-w-md text-sm leading-relaxed text-[var(--muted)]">
          {children}
        </div>
      )}
    </div>
  );
}

export function ErrorState({ message }: { message: string }) {
  return (
    <p className="rounded-[var(--radius-sm)] border border-[var(--bad-border)] bg-[var(--bad-bg)] px-4 py-3 text-sm leading-relaxed text-[var(--bad)]">
      {message}
    </p>
  );
}

export function PageHeader({
  title,
  description,
  action,
}: {
  title: string;
  description?: React.ReactNode;
  action?: React.ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-3">
      <div className="min-w-0">
        <h1 className="page-title">{title}</h1>
        {description && <div className="page-sub max-w-2xl">{description}</div>}
      </div>
      {action && <div className="shrink-0 pt-1">{action}</div>}
    </div>
  );
}
