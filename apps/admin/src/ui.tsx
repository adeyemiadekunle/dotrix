// The console's building blocks, on the design's tokens (design.css) and admin.css.
import { useEffect, useRef, useState, type ReactNode } from "react";

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

export type Series = { key: string; label: string; color: string };

/**
 * Columns per day, stacked when there are several series. Thin bars (at most 24px) with a rounded top,
 * a 2px gap between stacked segments, three recessive gridlines, a legend for two or more series, a
 * tooltip per day, and a table view.
 */
export function Columns({
  days,
  series,
  value,
  format = compact,
  height = 180,
}: {
  days: string[];
  series: Series[];
  value: (day: number, key: string) => number;
  format?: (n: number) => string;
  height?: number;
}) {
  const [hover, setHover] = useState<number | null>(null);
  const [asTable, setAsTable] = useState(false);
  // Drawn at the plot's real width, so text and bars keep their size at any width.
  const plot = useRef<HTMLDivElement>(null);
  const [W, setW] = useState(640);
  useEffect(() => {
    const el = plot.current;
    if (!el) return;
    const ro = new ResizeObserver(([entry]) => setW(Math.max(240, Math.round(entry.contentRect.width))));
    ro.observe(el);
    return () => ro.disconnect();
  }, [asTable]);
  const totals = days.map((_, i) => series.reduce((sum, s) => sum + value(i, s.key), 0));
  const max = niceMax(Math.max(1, ...totals));
  const pad = { l: 40, r: 8, t: 8, b: 22 };
  const plotH = height - pad.t - pad.b;
  const band = (W - pad.l - pad.r) / days.length;
  const bar = Math.min(24, band * 0.62);
  const y = (v: number) => pad.t + plotH - (v / max) * plotH;
  const label = (d: string) => new Date(`${d}T00:00:00Z`).toLocaleDateString(undefined, { month: "short", day: "numeric", timeZone: "UTC" });
  const every = Math.ceil(days.length / Math.max(2, Math.floor((W - pad.l) / 70)));

  return (
    <div className="chart">
      <div className="chart-bar">
        {series.length > 1 ? (
          <ul className="legend">
            {series.map((s) => (
              <li key={s.key}>
                <i style={{ background: s.color }} />
                {s.label}
              </li>
            ))}
          </ul>
        ) : (
          <span />
        )}
        <button type="button" className="link" onClick={() => setAsTable(!asTable)}>
          {asTable ? "Chart" : "Table"}
        </button>
      </div>
      {asTable ? (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Day (UTC)</th>
                {series.map((s) => (
                  <th key={s.key} className="r">
                    {s.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {days.map((d, i) => (
                <tr key={d}>
                  <td>{label(d)}</td>
                  {series.map((s) => (
                    <td key={s.key} className="r num">
                      {format(value(i, s.key))}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="chart-plot" ref={plot} onMouseLeave={() => setHover(null)}>
          <svg width={W} height={height} viewBox={`0 0 ${W} ${height}`} role="img" aria-label={`${series.map((s) => s.label).join(" and ")} per day`}>
            {[0, 0.5, 1].map((f) => (
              <g key={f}>
                <line className="grid" x1={pad.l} x2={W - pad.r} y1={y(max * f)} y2={y(max * f)} />
                <text className="axis" x={pad.l - 8} y={y(max * f) + 4} textAnchor="end">
                  {format(max * f)}
                </text>
              </g>
            ))}
            {days.map((d, i) => {
              const cx = pad.l + band * i + band / 2;
              let top = pad.t + plotH;
              const parts = series
                .map((s) => ({ s, v: value(i, s.key) }))
                .filter((p) => p.v > 0)
                .map((p, j, all) => {
                  const h = (p.v / max) * plotH;
                  const gap = j > 0 ? 2 : 0;
                  const rect = { s: p.s, x: cx - bar / 2, y: top - h, h: Math.max(1, h - gap), last: j === all.length - 1 };
                  top -= h;
                  return rect;
                });
              return (
                <g key={d} className={hover === i ? "col on" : "col"}>
                  <rect className="hit" x={pad.l + band * i} y={pad.t} width={band} height={plotH} onMouseEnter={() => setHover(i)} />
                  {parts.map((p) => (
                    <path key={p.s.key} d={columnPath(p.x, p.y, bar, p.h, p.last ? Math.min(4, p.h) : 0)} fill={p.s.color} />
                  ))}
                  {i % every === (days.length - 1) % every && (
                    <text className="axis" x={cx} y={height - 6} textAnchor="middle">
                      {label(d)}
                    </text>
                  )}
                </g>
              );
            })}
          </svg>
          {hover !== null && (
            <div className="tip" style={{ left: Math.min(W - 80, Math.max(80, pad.l + band * hover + band / 2)) }}>
              <b>{label(days[hover])}</b>
              {series.map((s) => (
                <span key={s.key}>
                  <i style={{ background: s.color }} />
                  {s.label}
                  <em>{format(value(hover, s.key))}</em>
                </span>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/** A column with a rounded top and a square foot on the baseline. */
function columnPath(x: number, y: number, w: number, h: number, r: number): string {
  const b = y + h;
  return `M${x},${b}V${y + r}Q${x},${y} ${x + r},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${b}Z`;
}

function niceMax(v: number): number {
  const pow = 10 ** Math.floor(Math.log10(v));
  const step = [1, 2, 2.5, 5, 10].find((s) => s * pow >= v) ?? 10;
  return step * pow;
}
