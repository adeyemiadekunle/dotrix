"""Calendar feed (FR-32): your issue dates in any calendar app, from a secret URL."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Response, status

from pmagent_backend.api.deps import CurrentUser, SessionDep, SessionUser, SettingsDep
from pmagent_backend.core.errors import NotFound
from pmagent_backend.core.openapi import errors

from .schemas import CalendarFeedCreate, CalendarFeedCreated, CalendarFeedRead, CalendarFeedUpdate
from .service import CalendarService


def get_calendar_service(session: SessionDep, settings: SettingsDep) -> CalendarService:
    return CalendarService(session, settings)


Calendars = Annotated[CalendarService, Depends(get_calendar_service)]

me_router = APIRouter(prefix="/me/calendar", tags=["calendar"], responses=errors(401))
feed_router = APIRouter(prefix="/calendar", tags=["calendar"])


@me_router.get("", responses=errors(404))
async def get_calendar_feed(user: CurrentUser, calendars: Calendars) -> CalendarFeedRead:
    """Your calendar feed's settings; 404 if it's off. The URL itself is shown only when
    the feed is turned on."""
    return await calendars.get(user)


@me_router.post("", status_code=status.HTTP_201_CREATED, responses=errors(403, 422))
async def create_calendar_feed(data: CalendarFeedCreate, user: SessionUser, calendars: Calendars) -> CalendarFeedCreated:
    """Turn your calendar feed on and get its secret URL (in this response only). If it was
    already on, the old URL stops working. Needs a login session (403 for API tokens)."""
    return await calendars.create(user, data)


@me_router.patch("", responses=errors(404, 422))
async def update_calendar_feed(data: CalendarFeedUpdate, user: CurrentUser, calendars: Calendars) -> CalendarFeedRead:
    """Change what the feed includes; the URL stays the same."""
    return await calendars.update(user, data)


@me_router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def delete_calendar_feed(user: CurrentUser, calendars: Calendars) -> None:
    """Turn your calendar feed off: its URL stops working."""
    await calendars.delete(user)


@feed_router.get(
    "/{feed}",
    responses={
        200: {"content": {"text/calendar": {}}, "description": "An iCalendar (RFC 5545) file"},
        **errors(404),
    },
)
async def calendar_feed(feed: str, calendars: Calendars) -> Response:
    """The calendar itself, for calendar apps: `{secret}.ics`, from the URL you got when
    turning the feed on. No sign-in: the secret is the credential. Due dates are all-day
    events, scheduled times one-hour slots; each links to the issue in the web app."""
    if not feed.endswith(".ics"):
        raise NotFound("No such calendar")
    body = await calendars.render(feed.removesuffix(".ics"))
    return Response(
        body,
        media_type="text/calendar; charset=utf-8",
        headers={"Cache-Control": "private, max-age=300", "Content-Disposition": 'inline; filename="pmagent.ics"'},
    )
