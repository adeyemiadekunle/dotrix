// The console's building blocks, on the design's tokens (design.css) and admin.css.
import { useEffect, useState, type ReactNode } from "react";

/** Sentence case for a snake_case value: "model_limit" → "Model limit". */
export const words = (v: string) => {
  const t = v.replaceAll("_", " ");
  return t.charAt(0).toUpperCase() + t.slice(1);
};

export const num = (n: number | null | undefined) => (n ?? 0).toLocaleString();

export const compact = (n: number) =>
  n >= 1e9 ? `${(n / 1e9).toFixed(1)}B` : n >= 1e6 ? `${(n / 1e6).toFixed(1)}M` : n >= 1e4 ? `${Math.round(n / 1e3)}k` : n.toLocaleString();

export const usd = (n: number | null | undefined) => (n == null ? "—" : n >= 100 ? `$${Math.round(n).toLocaleString()}` : `$${n.toFixed(2)}`);

export const bytes = (n: number) =>
  n >= 1 << 30 ? `${(n / (1 << 30)).toFixed(1)} GB` : n >= 1 << 20 ? `${(n / (1 << 20)).toFixed(1)} MB` : `${Math.max(0, Math.round(n / 1024))} KB`;

export const pct = (part: number, whole: number) => (whole ? `${((part / whole) * 100).toFixed(part / whole < 0.1 && part ? 1 : 0)}%` : "—");

export function duration(seconds: number | null | undefined): string {
  if (seconds == null) return "—";
  if (seconds < 60) return `${Math.round(seconds)}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${Math.round(seconds % 60)}s`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ${Math.round((seconds % 3600) / 60)}m`;
  return `${Math.floor(seconds / 86400)}d ${Math.round((seconds % 86400) / 3600)}h`;
}

export function ago(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return "never";
  const s = Math.max(0, (now - new Date(iso).getTime()) / 1000);
  if (s < 45) return "just now";
  if (s < 3600) return `${Math.round(s / 60)}m ago`;
  if (s < 86400) return `${Math.round(s / 3600)}h ago`;
  return `${Math.round(s / 86400)}d ago`;
}

export const when = (iso: string) => new Date(iso).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });

/** Re-render every `ms`, so "3m ago" stays true without refetching. */
export function useTick(ms = 15_000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), ms);
    return () => clearInterval(id);
  }, [ms]);
  return now;
}

export function PageHead({ title, sub, children }: { title: string; sub?: ReactNode; children?: ReactNode }) {
  return (
    <header className="page-head">
      <div>
        <h1>{title}</h1>
        {sub && <p>{sub}</p>}
      </div>
      {children && <div className="page-tools">{children}</div>}
    </header>
  );
}

export function Card({ title, aside, children, flush }: { title?: ReactNode; aside?: ReactNode; children: ReactNode; flush?: boolean }) {
  return (
    <section className={`card${flush ? " flush" : ""}`}>
      {(title || aside) && (
        <div className="card-head">
          {title && <h2>{title}</h2>}
          {aside}
        </div>
      )}
      {children}
    </section>
  );
}

export type Tone = "good" | "warn" | "bad" | "info" | "muted";

export function Pill({ tone, children }: { tone: Tone; children: ReactNode }) {
  return <span className={`pill ${tone}`}>{children}</span>;
}

const STATUS_TONE: Record<string, Tone> = {
  completed: "good",
  pr_opened: "good",
  no_changes: "good",
  changes_ready: "info",
  running: "info",
  queued: "info",
  waiting_children: "info",
  waiting_dependency: "info",
  awaiting_approval: "warn",
  blocked: "warn",
  recovery_required: "bad",
  failed: "bad",
  stopped: "muted",
  cancelled: "muted",
  rejected: "muted",
};

export function Status({ status }: { status: string }) {
  return <Pill tone={STATUS_TONE[status] ?? "muted"}>{words(status)}</Pill>;
}

export function Tile({ label, value, foot, tone }: { label: string; value: ReactNode; foot?: ReactNode; tone?: Tone }) {
  return (
    <div className={`tile${tone ? ` ${tone}` : ""}`}>
      <span className="tile-label">{label}</span>
      <span className="tile-value">{value}</span>
      {foot && <span className="tile-foot">{foot}</span>}
    </div>
  );
}

export function Segmented<T extends string | number>({
  value,
  options,
  onChange,
  label,
}: {
  value: T;
  options: { value: T; label: string }[];
  onChange: (v: T) => void;
  label: string;
}) {
  return (
    <div className="seg" role="radiogroup" aria-label={label}>
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          role="radio"
          aria-checked={o.value === value}
          className={o.value === value ? "on" : ""}
          onClick={() => onChange(o.value)}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

export const DAYS = [
  { value: 7, label: "7 days" },
  { value: 14, label: "14 days" },
  { value: 30, label: "30 days" },
];

export function Loading({ what = "Loading" }: { what?: string }) {
  return <p className="state">{what}…</p>;
}

export function Failed({ error }: { error: Error }) {
  return <p className="state bad">{error.message}</p>;
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="state">{children}</p>;
}

/** A meter: the share of a whole, with the number beside it. */
export function Meter({ part, whole, tone = "info" }: { part: number; whole: number; tone?: Tone }) {
  const share = whole ? Math.min(1, part / whole) : 0;
  return (
    <span className="meter">
      <span className={`meter-bar ${tone}`}>
        <i style={{ width: `${share * 100}%` }} />
      </span>
      <span className="meter-n">{pct(part, whole)}</span>
    </span>
  );
}
