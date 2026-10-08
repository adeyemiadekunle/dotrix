// Gr8r's small render helpers (gr8r-studio/src/ui/helpers.js) as components, same markup.
import type { CSSProperties, ReactNode } from "react";
import { Fragment } from "react";

import { LB, PR, PSTAT, ST, TY, type IssueType, type PriorityId, type ProjectStatusId, type StatusId } from "../core/constants";
import { Ic } from "../core/icons";
import { TODAY, diffD, initials, parse, relDate } from "../core/utils";
import { AGENTS } from "../data/seed-dotrix";
import { D, pColor, who } from "../data/store";
import type { FileItem, Project, Task } from "../data/types";

const css = (o: Record<string, string | number>) => o as CSSProperties;

/** A person's (or an agent's) avatar; nobody: the dashed "unassigned" circle. */
export function Av({ id, cls = "", tip = true }: { id: string | null | undefined; cls?: string; tip?: boolean }) {
  const w = who(id);
  if (!w) {
    return (
      <span className={`av empty ${cls}`} data-tip={tip ? "Unassigned" : undefined}>
        <Ic n="user" s={11} />
      </span>
    );
  }
  const agent = AGENTS.find((a) => a.handle === w.id);
  return (
    <span className={`av ${cls}`} style={css({ "--c": w.c })} data-tip={tip ? w.name : undefined} aria-label={w.name}>
      {agent ? <Ic n={agent.icon} s={11} /> : w.agent ? <Ic n="bot" s={11} /> : initials(w.name)}
    </span>
  );
}
export function AvStack({ ids, max = 4, cls = "sm" }: { ids: string[]; max?: number; cls?: string }) {
  return (
    <span className="avs">
      {ids.slice(0, max).map((i) => (
        <Av key={i} id={i} cls={cls} />
      ))}
      {ids.length > max && (
        <span className={`av ${cls} more`} style={css({ "--c": "var(--gray)" })}>
          +{ids.length - max}
        </span>
      )}
    </span>
  );
}

export function StIcon({ st, s = 14 }: { st: StatusId; s?: number }) {
  const c = `var(--st-${st})`;
  const r = 5.4;
  let inner: ReactNode;
  if (st === "backlog") inner = <circle cx="7" cy="7" r={r} fill="none" stroke={c} strokeWidth="1.5" strokeDasharray="1.9 2.1" />;
  else if (st === "todo") inner = <circle cx="7" cy="7" r={r} fill="none" stroke={c} strokeWidth="1.5" />;
  else if (st === "progress")
    inner = (
      <>
        <circle cx="7" cy="7" r={r} fill="none" stroke={c} strokeWidth="1.5" />
        <path d="M7 3.4A3.6 3.6 0 0 1 7 10.6Z" fill={c} />
      </>
    );
  else if (st === "blocked")
    inner = (
      <>
        <circle cx="7" cy="7" r={r} fill="none" stroke={c} strokeWidth="1.5" />
        <path d="M4.6 9.4 9.4 4.6" stroke={c} strokeWidth="1.5" strokeLinecap="round" />
      </>
    );
  else if (st === "review")
    inner = (
      <>
        <circle cx="7" cy="7" r={r} fill="none" stroke={c} strokeWidth="1.5" />
        <path d="M7 3.4A3.6 3.6 0 1 1 3.4 7L7 7Z" fill={c} />
      </>
    );
  else
    inner = (
      <>
        <circle cx="7" cy="7" r="6.2" fill={c} />
        <path d="M4.4 7.2 6.2 9 9.7 5.3" fill="none" stroke="var(--surface)" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" />
      </>
    );
  return (
    <svg width={s} height={s} viewBox="0 0 14 14" aria-hidden="true" style={{ flexShrink: 0 }}>
      {inner}
    </svg>
  );
}
export function PrIcon({ p, s = 14 }: { p: PriorityId | null | undefined; s?: number }) {
  if (p === "urgent")
    return (
      <svg width={s} height={s} viewBox="0 0 14 14" aria-hidden="true" style={{ flexShrink: 0 }}>
        <rect x="1" y="1" width="12" height="12" rx="3" fill="var(--red)" />
        <path d="M7 3.8v4" stroke="#fff" strokeWidth="1.7" strokeLinecap="round" />
        <circle cx="7" cy="10.1" r=".95" fill="#fff" />
      </svg>
    );
  if (!p || p === "none")
    return (
      <svg width={s} height={s} viewBox="0 0 14 14" aria-hidden="true" style={{ flexShrink: 0 }}>
        <path d="M2.5 7h2M6 7h2M9.5 7h2" stroke="var(--text-3)" strokeWidth="1.5" strokeLinecap="round" />
      </svg>
    );
  const w = PR[p].w;
  const bar = (x: number, h: number, on: boolean) => (
    <rect x={x} y={12 - h} width="2.6" height={h} rx="1" fill={on ? "var(--text-2)" : "var(--border-strong)"} />
  );
  return (
    <svg width={s} height={s} viewBox="0 0 14 14" aria-hidden="true" style={{ flexShrink: 0 }}>
      {bar(1.8, 4.5, w >= 1)}
      {bar(5.7, 7.5, w >= 2)}
      {bar(9.6, 10.5, w >= 3)}
    </svg>
  );
}
export const StPill = ({ st }: { st: StatusId }) => (
  <>
    <StIcon st={st} />
    <span>{ST[st].name}</span>
  </>
);
export const PrPill = ({ p }: { p: PriorityId | null }) => (
  <>
    <PrIcon p={p} />
    <span>{PR[p || "none"].name}</span>
  </>
);
/** dotrix: an issue's type, as a small coloured icon. */
export function TypeIcon({ type, s = 13 }: { type: IssueType; s?: number }) {
  const t = TY[type];
  return (
    <span data-tip={t.name} style={{ color: t.c, display: "inline-flex" }}>
      <Ic n={t.icon} s={s} />
    </span>
  );
}
export function Lbl({ id }: { id: string }) {
  const l = LB[id];
  if (!l) return null;
  return (
    <span className="lbl" style={css({ "--c": l.c })}>
      <i />
      {l.name}
    </span>
  );
}
export function PIcon({ p, cls = "", s = 15 }: { p: Project; cls?: string; s?: number }) {
  return (
    <span className={`picon ${cls}`} style={css({ "--c": pColor(p) })}>
      <Ic n={p.icon} s={s} />
    </span>
  );
}
export function PStatus({ s }: { s: ProjectStatusId }) {
  return (
    <span className="pstatus" style={css({ "--c": PSTAT[s].c })}>
      <i />
      {PSTAT[s].name}
    </span>
  );
}
export function Due({ t, icon = true }: { t: Task; icon?: boolean }) {
  if (!t.due) return null;
  const n = diffD(parse(t.due)!, TODAY);
  const cls = t.status === "done" ? "" : n < 0 ? "over" : n <= 1 ? "soon" : "";
  return (
    <span className={`due ${cls}`}>
      {icon && <Ic n="calendar" s={12} />}
      {relDate(t.due)}
    </span>
  );
}
export function ProgBar({ v, cls = "" }: { v: number; cls?: string }) {
  return (
    <span className={`prog ${cls}`} role="progressbar" aria-valuenow={v} aria-valuemin={0} aria-valuemax={100}>
      <i style={css({ "--p": v / 100 })} />
    </span>
  );
}
export function Empty({
  icon,
  title,
  text,
  children,
  cls = "",
}: {
  icon: string;
  title: string;
  text: string;
  children?: ReactNode;
  cls?: string;
}) {
  return (
    <div className={`empty-state ${cls}`}>
      <div className="glyph">
        <Ic n={icon} s={20} />
      </div>
      <h2 className="es-h">{title}</h2>
      <p>{text}</p>
      {children}
    </div>
  );
}
/** Highlights the first match of `q` in `text`. */
export function Hl({ text, q }: { text: string; q: string }) {
  if (!q) return <>{text}</>;
  const i = text.toLowerCase().indexOf(q.toLowerCase());
  if (i < 0) return <>{text}</>;
  return (
    <>
      {text.slice(0, i)}
      <mark>{text.slice(i, i + q.length)}</mark>
      {text.slice(i + q.length)}
    </>
  );
}
/** A comment's text with @mentions marked. */
export function CommentText({ text }: { text: string }) {
  const names = D().members.map((m) => "@" + m.name);
  const parts: ReactNode[] = [];
  let rest = text;
  let k = 0;
  while (rest) {
    const hits = names.map((n) => [rest.indexOf(n), n] as const).filter(([i]) => i >= 0);
    if (!hits.length) {
      parts.push(rest);
      break;
    }
    const [i, n] = hits.sort((a, b) => a[0] - b[0])[0]!;
    parts.push(rest.slice(0, i), <span key={k++} className="mention">{n}</span>);
    rest = rest.slice(i + n.length);
  }
  return (
    <>
      {parts.map((p, i) => (
        <Fragment key={i}>{p}</Fragment>
      ))}
    </>
  );
}
export const FT: Record<string, { c: string; i: string; n: string }> = {
  fig: { c: "#8662C9", i: "pen-tool", n: "Figma" },
  pdf: { c: "#C4473A", i: "file-text", n: "PDF" },
  zip: { c: "#6B7280", i: "folder-archive", n: "Archive" },
  img: { c: "#23918A", i: "image", n: "Image" },
  sheet: { c: "#3D8E5F", i: "file-spreadsheet", n: "Spreadsheet" },
  doc: { c: "#3B82C4", i: "file-text", n: "Document" },
  code: { c: "#C48A1E", i: "file-code", n: "Code" },
  md: { c: "#4B5BD6", i: "file-text", n: "Markdown" },
  other: { c: "#6B7280", i: "file", n: "File" },
};
export function fileType(name: string): string {
  const e = (name.split(".").pop() || "").toLowerCase();
  if (e === "fig") return "fig";
  if (e === "pdf") return "pdf";
  if (["zip", "rar", "7z"].includes(e)) return "zip";
  if (["png", "jpg", "jpeg", "gif", "webp", "svg", "heic"].includes(e)) return "img";
  if (["xlsx", "xls", "csv", "numbers"].includes(e)) return "sheet";
  if (e === "md") return "md";
  if (["doc", "docx", "txt", "pages", "rtf"].includes(e)) return "doc";
  if (["js", "ts", "json", "html", "css", "py"].includes(e)) return "code";
  return "other";
}
export function fsize(b: number): string {
  if (b < 1024) return b + " B";
  if (b < 1048576) return Math.round(b / 1024) + " KB";
  return (b / 1048576).toFixed(1) + " MB";
}
export function FilePrev({ f }: { f: Pick<FileItem, "type" | "name"> }) {
  const t = FT[f.type] || FT.other!;
  let art: ReactNode;
  if (f.type === "img")
    art = (
      <div
        className="art"
        style={{
          padding: 0,
          overflow: "hidden",
          background: `linear-gradient(135deg,color-mix(in srgb,${t.c} 35%,var(--surface)),color-mix(in srgb,${t.c} 10%,var(--surface)))`,
        }}
      >
        <svg viewBox="0 0 100 60" preserveAspectRatio="none" style={{ width: "100%", height: "100%" }}>
          <path d="M0 60 L30 28 L52 46 L70 32 L100 58 L100 60Z" fill={`color-mix(in srgb,${t.c} 45%,var(--surface))`} />
          <circle cx="76" cy="16" r="7" fill={`color-mix(in srgb,${t.c} 30%,var(--surface))`} />
        </svg>
      </div>
    );
  else if (f.type === "sheet")
    art = (
      <div className="art" style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 3 }}>
        {Array.from({ length: 20 }, (_, i) => (
          <i key={i} />
        ))}
      </div>
    );
  else if (f.type === "fig")
    art = (
      <div className="art" style={{ flexDirection: "row", gap: 6 }}>
        <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 5 }}>
          <i className="h" />
          <i />
          <i style={{ width: "70%" }} />
          <i style={{ height: 18, background: `color-mix(in srgb,${t.c} 20%,var(--surface))` }} />
        </div>
        <div style={{ width: "34%", borderRadius: 3, background: `color-mix(in srgb,${t.c} 14%,var(--surface))` }} />
      </div>
    );
  else if (f.type === "zip")
    art = (
      <div style={{ color: t.c }}>
        <Ic n="folder-archive" s={30} />
      </div>
    );
  else
    art = (
      <div className="art">
        <i className="h" />
        <i />
        <i />
        <i style={{ width: "80%" }} />
        <i />
        <i style={{ width: "60%" }} />
      </div>
    );
  const ext = (f.name.split(".").pop() || "").slice(0, 4);
  return (
    <div className="fprev">
      {art}
      <span className="ext" style={css({ "--c": t.c })}>
        {ext}
      </span>
    </div>
  );
}
export const sk = (w: string, h = 10, extra: CSSProperties = {}) => <span className="sk" style={{ width: w, height: h, ...extra }} />;
