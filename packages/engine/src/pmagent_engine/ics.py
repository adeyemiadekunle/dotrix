"""Calendar export: .pmagent/calendar.ics generated from task dates.

There is no separate calendar file to maintain. `due` and `scheduled` live
on each task; this module renders them as standard iCalendar (RFC 5545) so
the same tasks show up in any calendar app (subscribe to the file, or import
it) and in the desktop app's calendar view.

  - `due`       -> an all-day event "Due: <title>" on that date
  - `scheduled` -> an event "<title>" (all-day for a date, 1h slot for a datetime)

UIDs are stable per task + kind, so re-exporting updates events in place
instead of duplicating them. The file is a derived artifact: regenerate it,
don't edit it.
"""
from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from .config import ProjectConfig
from .tasks import Task, _atomic_write, list_tasks

CALENDAR_FILENAME = "calendar.ics"


def _escape(text: str) -> str:
    return (
        text.replace("\\", "\\\\").replace(";", "\\;")
        .replace(",", "\\,").replace("\r\n", "\\n").replace("\n", "\\n")
    )


def _fold(line: str) -> str:
    """RFC 5545: lines longer than 75 octets are folded with CRLF + space."""
    out, current = [], b""
    for ch in line:
        b = ch.encode("utf-8")
        limit = 75 if not out else 74  # continuation lines lose 1 to the space
        if len(current) + len(b) > limit:
            out.append(current.decode("utf-8"))
            current = b""
        current += b
    out.append(current.decode("utf-8"))
    return "\r\n ".join(out)


def _utc_stamp(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


def _time_props(value: str) -> list[str]:
    if "T" in value:
        start = datetime.fromisoformat(value)
        return [f"DTSTART:{_utc_stamp(start)}", f"DTEND:{_utc_stamp(start + timedelta(hours=1))}"]
    d = date.fromisoformat(value)
    return [
        f"DTSTART;VALUE=DATE:{d.strftime('%Y%m%d')}",
        f"DTEND;VALUE=DATE:{(d + timedelta(days=1)).strftime('%Y%m%d')}",
    ]


def _event(task: Task, kind: str, when: str, project: str, stamp: str) -> list[str]:
    summary = f"Due: {task.title}" if kind == "due" else task.title
    if task.status == "done":
        summary = f"✓ {summary}"  # done tasks stay visible as history
    desc_bits = [f"{task.id} · {task.status} · {task.priority}"]
    if task.assignee:
        desc_bits.append(f"Assignee: {task.assignee}")
    if task.description:
        desc_bits.append("")
        desc_bits.append(task.description)
    lines = [
        "BEGIN:VEVENT",
        f"UID:{task.id}-{kind}@pmagent.{project}",
        f"DTSTAMP:{stamp}",
        *_time_props(when),
        f"SUMMARY:{_escape(summary)}",
        f"DESCRIPTION:{_escape(chr(10).join(desc_bits))}",
        f"CATEGORIES:{_escape(','.join([project, *task.labels]))}",
        "STATUS:CONFIRMED",
        "TRANSP:TRANSPARENT",  # don't block time as "busy"
    ]
    lines.append("END:VEVENT")
    return lines


def render_ics(tasks: Iterable[Task], project_name: str) -> str:
    slug = "".join(c if c.isalnum() else "-" for c in project_name.lower()).strip("-") or "project"
    stamp = _utc_stamp(datetime.now(UTC))
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//pmagent//tasks//EN",
        "CALSCALE:GREGORIAN",
        f"X-WR-CALNAME:{_escape(project_name)} tasks",
    ]
    for t in tasks:
        if t.due:
            lines += _event(t, "due", t.due, slug, stamp)
        if t.scheduled:
            lines += _event(t, "scheduled", t.scheduled, slug, stamp)
    lines.append("END:VCALENDAR")
    return "\r\n".join(_fold(line) for line in lines) + "\r\n"


def export_calendar(
    config: ProjectConfig, out_path: str | None = None, include_done: bool = True,
) -> tuple[Path, int]:
    tasks = [t for t in list_tasks(config, include_done=include_done) if t.due or t.scheduled]
    path = Path(out_path) if out_path else Path(config.pmagent_dir) / CALENDAR_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(path, render_ics(tasks, config.name))
    return path, len(tasks)
