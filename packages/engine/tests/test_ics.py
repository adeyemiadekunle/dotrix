from datetime import UTC, date, datetime

from pmagent_engine.ics import CalendarEvent, render_calendar


def _unfold(text: str) -> list[str]:
    return text.replace("\r\n ", "").split("\r\n")


def test_all_day_and_timed_events() -> None:
    body = render_calendar("pmagent", [
        CalendarEvent(uid="a-due@pmagent", summary="Due: KUN-1 Ship", start=date(2026, 10, 2)),
        CalendarEvent(uid="b-scheduled@pmagent", summary="KUN-2 Demo", start=datetime(2026, 10, 1, 14, 0, tzinfo=UTC)),
    ], product="issues")
    lines = _unfold(body)
    assert lines[0] == "BEGIN:VCALENDAR" and "PRODID:-//pmagent//issues//EN" in lines
    assert "DTSTART;VALUE=DATE:20261002" in lines and "DTEND;VALUE=DATE:20261003" in lines
    assert "DTSTART:20261001T140000Z" in lines and "DTEND:20261001T150000Z" in lines
    assert lines.count("BEGIN:VEVENT") == 2 and body.endswith("END:VCALENDAR\r\n")


def test_text_is_escaped_and_long_lines_folded() -> None:
    event = CalendarEvent(
        uid="c@pmagent",
        summary="Fix; parsing, of \\ paths\nnow " + "x" * 120,
        start=date(2026, 10, 2),
        description="Kunemi · task · todo",
        url="http://app.test/w/kunemi/p/KUN/board?issue=KUN-3",
        categories=["KUN"],
    )
    body = render_calendar("pmagent", [event])
    assert all(len(line.encode()) <= 75 for line in body.split("\r\n"))
    summary = next(line for line in _unfold(body) if line.startswith("SUMMARY:"))
    assert summary.startswith("SUMMARY:Fix\\; parsing\\, of \\\\ paths\\nnow xxx")
    assert "URL:http://app.test/w/kunemi/p/KUN/board?issue=KUN-3" in _unfold(body)
    assert "CATEGORIES:KUN" in _unfold(body)
