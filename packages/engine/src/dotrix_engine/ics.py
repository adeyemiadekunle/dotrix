"""Calendars as standard iCalendar (RFC 5545).

`render_calendar` turns any list of `CalendarEvent`s into a calendar: the platform's
per-user feed of issue dates uses it, and so does the local export below.

Local export: .dotrix/calendar.ics generated from task dates. There is no separate
calendar file to maintain. `due` and `scheduled` live on each task; they render so the
same tasks show up in any calendar app (subscribe to the file, or import it):

  - `due`       -> an all-day event "Due: <title>" on that date
  - `scheduled` -> an event "<title>" (all-day for a date, 1h slot for a datetime)

UIDs are stable per task (or issue) + kind, so re-exporting updates events in place
instead of duplicating them. The file is a derived artifact: regenerate it, don't edit it.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from .config import ProjectConfig
from .tasks import Task, _atomic_write, list_tasks

CALENDAR_FILENAME = "calendar.ics"


@dataclass(frozen=True)
class CalendarEvent:
    uid: str  # stable, so calendar apps update the event instead of duplicating it
    summary: str
    start: date | datetime  # a date is an all-day event; a datetime a one-hour slot
    description: str = ""
    url: str | None = None
    categories: list[str] = field(default_factory=list)


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


def _time_props(start: date | datetime) -> list[str]:
    if isinstance(start, datetime):
        return [f"DTSTART:{_utc_stamp(start)}", f"DTEND:{_utc_stamp(start + timedelta(hours=1))}"]
    return [
        f"DTSTART;VALUE=DATE:{start.strftime('%Y%m%d')}",
        f"DTEND;VALUE=DATE:{(start + timedelta(days=1)).strftime('%Y%m%d')}",
    ]


def render_calendar(name: str, events: Iterable[CalendarEvent], *, product: str = "tasks") -> str:
    stamp = _utc_stamp(datetime.now(UTC))
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:-//dotrix//{product}//EN",
        "CALSCALE:GREGORIAN",
        f"X-WR-CALNAME:{_escape(name)}",
    ]
    for event in events:
        lines += [
            "BEGIN:VEVENT",
            f"UID:{event.uid}",
            f"DTSTAMP:{stamp}",
            *_time_props(event.start),
            f"SUMMARY:{_escape(event.summary)}",
        ]
        if event.description:
            lines.append(f"DESCRIPTION:{_escape(event.description)}")
        if event.url:
            lines.append(f"URL:{event.url}")
        if event.categories:
            lines.append(f"CATEGORIES:{','.join(_escape(c) for c in event.categories)}")
        lines += [
            "STATUS:CONFIRMED",
            "TRANSP:TRANSPARENT",  # don't block time as "busy"
            "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")
    return "\r\n".join(_fold(line) for line in lines) + "\r\n"


# -- local export --------------------------------------------------------------------------


def _parse(value: str) -> date | datetime:
    return datetime.fromisoformat(value) if "T" in value else date.fromisoformat(value)


def _task_event(task: Task, kind: str, when: str, project: str) -> CalendarEvent:
    summary = f"Due: {task.title}" if kind == "due" else task.title
    if task.status == "done":
        summary = f"✓ {summary}"  # done tasks stay visible as history
    desc_bits = [f"{task.id} · {task.status} · {task.priority}"]
    if task.assignee:
        desc_bits.append(f"Assignee: {task.assignee}")
    if task.description:
        desc_bits.append("")
        desc_bits.append(task.description)
    return CalendarEvent(
        uid=f"{task.id}-{kind}@dotrix.{project}",
        summary=summary,
        start=_parse(when),
        description="\n".join(desc_bits),
        categories=[project, *task.labels],
    )


def render_ics(tasks: Iterable[Task], project_name: str) -> str:
    slug = "".join(c if c.isalnum() else "-" for c in project_name.lower()).strip("-") or "project"
    events = []
    for t in tasks:
        if t.due:
            events.append(_task_event(t, "due", t.due, slug))
        if t.scheduled:
            events.append(_task_event(t, "scheduled", t.scheduled, slug))
    return render_calendar(f"{project_name} tasks", events)


def export_calendar(
    config: ProjectConfig, out_path: str | None = None, include_done: bool = True,
) -> tuple[Path, int]:
    tasks = [t for t in list_tasks(config, include_done=include_done) if t.due or t.scheduled]
    path = Path(out_path) if out_path else Path(config.dotrix_dir) / CALENDAR_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(path, render_ics(tasks, config.name))
    return path, len(tasks)
