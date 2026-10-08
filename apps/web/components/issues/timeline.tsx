import type { Schemas } from "@pmagent/api-client";
import { cn } from "@pmagent/ui/lib/utils";
import { Link } from "@/lib/navigation";
import { useEffect, useMemo, useRef, useState, type KeyboardEvent, type PointerEvent } from "react";

import { StatusIcon, STATUS_META } from "@/components/issues/meta";
import { today } from "@/components/issues/workspace-issue-row";
import { ProjectTile } from "@/components/project-tile";

/** What a timeline needs from an issue (a project's rows and the rows across projects both fit). */
export type TimelineIssue = Pick<
  Schemas["IssueSummary"],
  "key" | "title" | "status" | "type" | "due" | "scheduled" | "created_at"
> & { project_key?: string; project_name?: string; depends_on?: string[] };

/** New dates for an issue dragged on the timeline, as the API takes them. */
export type Reschedule = { scheduled?: string | null; due?: string | null };

export type TimelineZoom = "weeks" | "months";

const DAY_WIDTH: Record<TimelineZoom, number> = { weeks: 28, months: 8 };
const ROW = 36;
const DAY_MS = 86_400_000;

const BAR: Record<TimelineIssue["status"], string> = {
  todo: "bg-primary/35",
  in_progress: "bg-primary",
  blocked: "bg-destructive/80",
  review: "bg-warning",
  done: "bg-muted-foreground/40",
};

/** Days since 1970 for a "YYYY-MM-DD" (or the date part of a timestamp), in UTC so DST can't shift it. */
function dayNumber(isoDate: string): number {
  const [y, m, d] = isoDate.slice(0, 10).split("-").map(Number);
  return Math.floor(Date.UTC(y, m - 1, d) / DAY_MS);
}

function localDay(timestamp: string): string {
  const date = new Date(timestamp);
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
}

function fromDayNumber(day: number): Date {
  return new Date(day * DAY_MS);
}

const isoDay = (day: number) => fromDayNumber(day).toISOString().slice(0, 10);
/** The start of that day where you are, as the issue drawer saves it. */
const startOfDay = (day: number) => new Date(`${isoDay(day)}T00:00:00`).toISOString();

/** The dates after moving a bar by `move` days or stretching its end by `resize`. */
function rescheduled(p: Placed, move: number, resize: number): Reschedule {
  const { issue, start, end } = p;
  if (move) {
    if (!issue.due) return { scheduled: startOfDay(start + move) };
    if (!issue.scheduled && p.milestone) return { due: isoDay(end + move) };
    return { scheduled: startOfDay(start + move), due: isoDay(end + move) };
  }
  return { due: isoDay(Math.max(start, end + resize)) };
}

interface Placed {
  issue: TimelineIssue;
  start: number;
  end: number;
  /** Only a due date (no start): shown as a point on that day. */
  milestone: boolean;
}

/** An issue's span: from when it's scheduled to start (else when it was created) to when it's due. */
function place(issue: TimelineIssue): Placed | null {
  const due = issue.due ? dayNumber(issue.due) : null;
  const scheduled = issue.scheduled ? dayNumber(localDay(issue.scheduled)) : null;
  if (due === null && scheduled === null) return null;
  if (due === null) return { issue, start: scheduled!, end: scheduled!, milestone: false };
  const start = scheduled ?? dayNumber(localDay(issue.created_at));
  return { issue, start: Math.min(start, due), end: due, milestone: scheduled === null && start >= due };
}

/**
 * Issues on a calendar: each a bar from its start to its due date, grouped by project when
 * they come from several. Issues without dates are counted below it. Scrolls sideways; today
 * is marked and in view on load.
 */
export function IssueTimeline({
  issues,
  href,
  zoom,
  groupByProject = false,
  onReschedule,
}: {
  issues: TimelineIssue[];
  href: (issue: TimelineIssue) => string;
  zoom: TimelineZoom;
  groupByProject?: boolean;
  /** Given: bars can be dragged (or moved with Alt+arrows) to change an issue's dates. */
  onReschedule?: (issue: TimelineIssue, dates: Reschedule) => void;
}) {
  const scroller = useRef<HTMLDivElement>(null);
  const dayWidth = DAY_WIDTH[zoom];
  const now = dayNumber(today());

  const { rows, undated, first, days } = useMemo(() => {
    const placed: Placed[] = [];
    let undated = 0;
    for (const issue of issues) {
      const p = place(issue);
      if (p) placed.push(p);
      else undated += 1;
    }
    placed.sort((a, b) => a.start - b.start || a.end - b.end || a.issue.key.localeCompare(b.issue.key));
    const starts = placed.map((p) => p.start);
    const ends = placed.map((p) => p.end);
    // From the Monday before the earliest date (or today) to well after the latest.
    let first = Math.min(now, ...starts) - 7;
    first -= (fromDayNumber(first).getUTCDay() + 6) % 7;
    const last = Math.max(now + 28, ...ends) + 14;
    const rows: ({ kind: "group"; key: string; name: string } | { kind: "issue"; placed: Placed })[] = [];
    if (groupByProject) {
      const byProject = new Map<string, Placed[]>();
      for (const p of placed) {
        const key = p.issue.project_key ?? "";
        byProject.set(key, [...(byProject.get(key) ?? []), p]);
      }
      for (const [key, list] of [...byProject].sort((a, b) => a[0].localeCompare(b[0]))) {
        rows.push({ kind: "group", key, name: list[0].issue.project_name ?? key });
        for (const p of list) rows.push({ kind: "issue", placed: p });
      }
    } else {
      for (const p of placed) rows.push({ kind: "issue", placed: p });
    }
    return { rows, undated, first, days: last - first + 1 };
  }, [issues, groupByProject, now]);

  // Today in view on load and when the zoom changes (a little after the left edge).
  useEffect(() => {
    if (scroller.current) scroller.current.scrollLeft = Math.max(0, (now - first - 7) * dayWidth);
  }, [now, first, dayWidth]);

  // Header marks: months on top; weeks (Mondays) or nothing finer below.
  const months: { left: number; label: string }[] = [];
  const weeks: { left: number; label: string }[] = [];
  for (let d = 0; d < days; d++) {
    const date = fromDayNumber(first + d);
    if (d === 0 || date.getUTCDate() === 1) {
      months.push({
        left: d * dayWidth,
        label: date.toLocaleDateString(undefined, { month: "long", year: "numeric", timeZone: "UTC" }),
      });
    }
    if (date.getUTCDay() === 1) weeks.push({ left: d * dayWidth, label: String(date.getUTCDate()) });
  }
  const width = days * dayWidth;
  const todayLeft = (now - first) * dayWidth;

  // Dependency arrows: from the end of what an issue waits for to its start.
  const arrows = useMemo(() => {
    const at = new Map<string, { index: number; placed: Placed }>();
    rows.forEach((row, index) => {
      if (row.kind === "issue") at.set(row.placed.issue.key, { index, placed: row.placed });
    });
    const found: { id: string; d: string; late: boolean }[] = [];
    for (const { index, placed } of at.values()) {
      for (const key of placed.issue.depends_on ?? []) {
        const from = at.get(key);
        if (!from) continue;
        const x1 = (from.placed.end - first + 1) * dayWidth;
        const y1 = from.index * ROW + ROW / 2;
        const x2 = (placed.start - first) * dayWidth;
        const y2 = index * ROW + ROW / 2;
        const turn = y2 > y1 ? y2 - ROW / 2 + 4 : y2 + ROW / 2 - 4;
        const d =
          x2 - x1 >= 14
            ? `M${x1} ${y1} H${x1 + 6} V${y2} H${x2 - 2}`
            : `M${x1} ${y1} H${x1 + 6} V${turn} H${x2 - 8} V${y2} H${x2 - 2}`;
        found.push({ id: `${key}-${placed.issue.key}`, d, late: from.placed.end >= placed.start });
      }
    }
    return found;
  }, [rows, first, dayWidth]);

  return (
    <div className="grid gap-2">
      <div className="bg-card overflow-hidden rounded-xl border">
        <div ref={scroller} className="relative overflow-x-auto" role="region" aria-label="Timeline">
          <div className="relative" style={{ width: width + 260 }}>
            {/* Header */}
            <div className="bg-card sticky top-0 z-20 flex border-b">
              <div className="bg-card sticky left-0 z-10 w-[260px] shrink-0 border-r px-3 py-2 text-xs font-medium">
                Issue
              </div>
              <div className="relative h-12" style={{ width }}>
                {months.map((m) => (
                  <span
                    key={m.left}
                    className="text-foreground absolute top-1 border-l pl-1.5 text-xs font-medium whitespace-nowrap"
                    style={{ left: m.left }}
                  >
                    {m.label}
                  </span>
                ))}
                {zoom === "weeks" &&
                  weeks.map((w) => (
                    <span
                      key={w.left}
                      className="text-muted-foreground absolute bottom-1 pl-1 text-[10px]"
                      style={{ left: w.left }}
                    >
                      {w.label}
                    </span>
                  ))}
              </div>
            </div>
            {/* Rows */}
            <div className="relative">
              {arrows.length > 0 && (
                <svg
                  aria-hidden
                  className="pointer-events-none absolute top-0"
                  style={{ left: 260, width, height: rows.length * ROW }}
                >
                  <defs>
                    <marker id="timeline-arrow" viewBox="0 0 6 6" refX="5" refY="3" markerWidth="6" markerHeight="6" orient="auto">
                      <path d="M0,0 L6,3 L0,6 z" className="fill-muted-foreground" />
                    </marker>
                    <marker id="timeline-arrow-late" viewBox="0 0 6 6" refX="5" refY="3" markerWidth="6" markerHeight="6" orient="auto">
                      <path d="M0,0 L6,3 L0,6 z" className="fill-destructive" />
                    </marker>
                  </defs>
                  {arrows.map((a) => (
                    <path
                      key={a.id}
                      d={a.d}
                      fill="none"
                      strokeWidth={1.25}
                      className={a.late ? "stroke-destructive" : "stroke-muted-foreground/70"}
                      markerEnd={`url(#${a.late ? "timeline-arrow-late" : "timeline-arrow"})`}
                    />
                  ))}
                </svg>
              )}
              <div
                aria-hidden
                className="bg-primary pointer-events-none absolute top-0 bottom-0 z-10 w-px"
                style={{ left: 260 + todayLeft + dayWidth / 2 }}
              />
              {rows.map((row) =>
                row.kind === "group" ? (
                  <div key={`g-${row.key}`} className="bg-muted/50 flex border-b" style={{ height: ROW }}>
                    <div className="bg-muted sticky left-0 z-10 flex w-[260px] shrink-0 items-center gap-2 border-r px-3 text-xs font-semibold">
                      <ProjectTile projectKey={row.key} className="size-4 text-[8px]" />
                      <span className="truncate">{row.name}</span>
                    </div>
                  </div>
                ) : (
                  <TimelineRow
                    key={`${row.placed.issue.project_key ?? ""}-${row.placed.issue.key}`}
                    placed={row.placed}
                    first={first}
                    dayWidth={dayWidth}
                    weeks={zoom === "weeks" ? weeks : []}
                    href={href(row.placed.issue)}
                    overdue={row.placed.issue.status !== "done" && row.placed.issue.due !== null && row.placed.end < now}
                    onReschedule={onReschedule ? (dates) => onReschedule(row.placed.issue, dates) : undefined}
                  />
                ),
              )}
              {rows.length === 0 && (
                <p className="text-muted-foreground sticky left-0 w-max px-4 py-6 text-sm">
                  No issue has a start or due date yet. Give issues a due date (and a start, in the issue drawer) to see them here.
                </p>
              )}
            </div>
          </div>
        </div>
      </div>
      {onReschedule && rows.length > 0 && (
        <p className="text-muted-foreground text-xs">
          Drag a bar to move it, or its right end to change the due date (Alt+arrows on a focused bar; add Shift for the
          end). Arrows run from what an issue waits for; red ones start before it ends.
        </p>
      )}
      {undated > 0 && (
        <p className="text-muted-foreground text-xs">
          {undated} {undated === 1 ? "issue has" : "issues have"} no dates and {undated === 1 ? "isn't" : "aren't"} shown.
        </p>
      )}
    </div>
  );
}

function TimelineRow({
  placed,
  first,
  dayWidth,
  weeks,
  href,
  overdue,
  onReschedule,
}: {
  placed: Placed;
  first: number;
  dayWidth: number;
  weeks: { left: number }[];
  href: string;
  overdue: boolean;
  onReschedule?: (dates: Reschedule) => void;
}) {
  const { issue, milestone } = placed;
  const [shift, setShift] = useState({ move: 0, resize: 0 });
  const drag = useRef<{ x: number; mode: "move" | "resize" } | null>(null);
  const dragged = useRef(false);
  const start = placed.start + shift.move;
  const end = Math.max(start, placed.end + shift.move + shift.resize);
  const left = (start - first) * dayWidth;
  const barWidth = Math.max(dayWidth, (end - start + 1) * dayWidth);

  function down(event: PointerEvent<HTMLElement>, mode: "move" | "resize") {
    if (!onReschedule || event.button !== 0) return;
    event.preventDefault();
    event.stopPropagation();
    event.currentTarget.setPointerCapture(event.pointerId);
    drag.current = { x: event.clientX, mode };
    dragged.current = false;
  }
  function moved(event: PointerEvent<HTMLElement>) {
    const d = drag.current;
    if (!d) return;
    if (Math.abs(event.clientX - d.x) > 3) dragged.current = true;
    const days = Math.round((event.clientX - d.x) / dayWidth);
    setShift(d.mode === "move" ? { move: days, resize: 0 } : { move: 0, resize: days });
  }
  function up() {
    if (!drag.current) return;
    drag.current = null;
    if (onReschedule && (shift.move || shift.resize)) onReschedule(rescheduled(placed, shift.move, shift.resize));
    setShift({ move: 0, resize: 0 });
  }
  function key(event: KeyboardEvent<HTMLElement>) {
    if (!onReschedule || !event.altKey || (event.key !== "ArrowLeft" && event.key !== "ArrowRight")) return;
    event.preventDefault();
    const days = event.key === "ArrowLeft" ? -1 : 1;
    onReschedule(event.shiftKey ? rescheduled(placed, 0, days) : rescheduled(placed, days, 0));
  }
  const range = `${fromDayNumber(start).toLocaleDateString(undefined, { month: "short", day: "numeric", timeZone: "UTC" })}${
    end !== start ? ` – ${fromDayNumber(end).toLocaleDateString(undefined, { month: "short", day: "numeric", timeZone: "UTC" })}` : ""
  }`;
  return (
    <div className="group flex border-b last:border-b-0" style={{ height: ROW }}>
      <Link
        href={href}
        className="bg-card group-hover:bg-muted sticky left-0 z-10 flex w-[260px] shrink-0 items-center gap-2 border-r px-3 text-sm"
      >
        <StatusIcon status={issue.status} />
        <span className="text-muted-foreground w-14 shrink-0 font-mono text-xs">{issue.key}</span>
        <span className="truncate">{issue.title}</span>
      </Link>
      <div className="group-hover:bg-muted/40 relative flex-1">
        {weeks.map((w) => (
          <span key={w.left} aria-hidden className="bg-border/60 absolute top-0 bottom-0 w-px" style={{ left: w.left }} />
        ))}
        <Link
          href={href}
          title={`${issue.key} ${issue.title}: ${STATUS_META[issue.status].label}, ${range}${overdue ? " (overdue)" : ""}`}
          aria-label={`${issue.key}: ${range}`}
          className={cn(
            "absolute top-1/2 h-5 -translate-y-1/2 rounded-md",
            milestone ? "w-3! rotate-45 rounded-sm" : "",
            BAR[issue.status],
            overdue && "ring-destructive ring-2",
            onReschedule && "cursor-grab touch-none active:cursor-grabbing",
          )}
          style={{ left: milestone ? left + dayWidth / 2 - 6 : left, width: barWidth }}
          onPointerDown={(e) => down(e, "move")}
          onPointerMove={moved}
          onPointerUp={up}
          onPointerCancel={() => {
            drag.current = null;
            setShift({ move: 0, resize: 0 });
          }}
          onKeyDown={key}
          onClick={(e) => {
            if (dragged.current) {
              e.preventDefault();
              dragged.current = false;
            }
          }}
        >
          {onReschedule && !milestone && (
            <span
              aria-hidden
              className="absolute top-0 right-0 bottom-0 w-2 cursor-ew-resize"
              onPointerDown={(e) => down(e, "resize")}
              onPointerMove={moved}
              onPointerUp={up}
            />
          )}
        </Link>
      </div>
    </div>
  );
}

/** Weeks / Months, kept in the URL by the page. */
export function ZoomToggle({ zoom, onZoom }: { zoom: TimelineZoom; onZoom: (zoom: TimelineZoom) => void }) {
  return (
    <div role="group" aria-label="Zoom" className="bg-muted flex gap-0.5 rounded-lg p-0.5 text-xs font-medium">
      {(["weeks", "months"] as const).map((id) => (
        <button
          key={id}
          type="button"
          aria-pressed={zoom === id}
          onClick={() => onZoom(id)}
          className={cn(
            "rounded-md px-2.5 py-1",
            zoom === id ? "bg-background text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground",
          )}
        >
          {id === "weeks" ? "Weeks" : "Months"}
        </button>
      ))}
    </div>
  );
}
