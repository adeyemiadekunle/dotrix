"""Calendar feeds (FR-32): each person's issue dates as iCalendar, at a secret URL.

The feed is rendered when a calendar app fetches it, from the workspaces the person can
see *at that moment*: leave a workspace and its issues drop out of the feed. It carries
only what a calendar needs (key, title, dates, status, a link); never descriptions, so a
leaked URL gives away as little as possible. Turn the feed on again to get a new URL.
"""
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from urllib.parse import quote

from sqlalchemy import and_, delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from pmagent_backend.core import security
from pmagent_backend.core.errors import NotFound
from pmagent_backend.core.settings import Settings
from pmagent_backend.modules.auth.models import User
from pmagent_backend.modules.issues.models import Issue, IssueStatus, IssueWatcher
from pmagent_backend.modules.projects.models import Project
from pmagent_backend.modules.projects.repository import visible_to
from pmagent_backend.modules.workspaces.models import Role, Workspace
from pmagent_backend.modules.workspaces.repository import WorkspaceRepository
from pmagent_engine.ics import CalendarEvent, render_calendar

from .models import CalendarFeed, FeedScope
from .schemas import CalendarFeedCreate, CalendarFeedCreated, CalendarFeedRead, CalendarFeedUpdate

LOOKBACK = timedelta(days=90)  # older dates drop out of the feed
MAX_EVENTS = 2000
TOUCH_EVERY = timedelta(hours=1)  # how often a fetch updates last_used_at


def _now() -> datetime:
    return datetime.now(UTC)


class CalendarService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    # -- your feed ---------------------------------------------------------------------

    async def get(self, user: User) -> CalendarFeedRead:
        return CalendarFeedRead.model_validate(await self._feed(user))

    async def create(self, user: User, data: CalendarFeedCreate) -> CalendarFeedCreated:
        """Turn the feed on, replacing any earlier URL (which stops working)."""
        await self.session.execute(delete(CalendarFeed).where(CalendarFeed.user_id == user.id))
        token = security.generate_token()
        feed = CalendarFeed(
            user_id=user.id, token_hash=security.hash_token(token), scope=data.scope, created_at=_now()
        )
        self.session.add(feed)
        await self.session.commit()
        return CalendarFeedCreated(
            scope=feed.scope, created_at=feed.created_at, last_used_at=None, url=self.feed_url(token)
        )

    async def update(self, user: User, data: CalendarFeedUpdate) -> CalendarFeedRead:
        feed = await self._feed(user)
        feed.scope = data.scope
        await self.session.commit()
        return CalendarFeedRead.model_validate(feed)

    async def delete(self, user: User) -> None:
        await self.session.execute(delete(CalendarFeed).where(CalendarFeed.user_id == user.id))
        await self.session.commit()

    def feed_url(self, token: str) -> str:
        # On the web app's address, which forwards /v1 to the API: the public entry point,
        # whether or not the API is.
        return f"{self.settings.app_url.rstrip('/')}/v1/calendar/{quote(token)}.ics"

    async def _feed(self, user: User) -> CalendarFeed:
        feed = await self.session.scalar(select(CalendarFeed).where(CalendarFeed.user_id == user.id))
        if feed is None:
            raise NotFound("Your calendar feed is off")
        return feed

    # -- the feed itself ------------------------------------------------------------------

    async def render(self, token: str) -> str:
        feed = await self.session.scalar(
            select(CalendarFeed).where(CalendarFeed.token_hash == security.hash_token(token))
        )
        user = await self.session.get(User, feed.user_id) if feed else None
        if feed is None or user is None or not user.is_active:
            raise NotFound("No such calendar")
        now = _now()
        if feed.last_used_at is None or now - feed.last_used_at > TOUCH_EVERY:
            feed.last_used_at = now
            await self.session.commit()
        return render_calendar("dotrix", await self._events(user, feed.scope, now), product="issues")

    async def _events(self, user: User, scope: FeedScope, now: datetime) -> list[CalendarEvent]:
        # Only workspaces you can see projects in (guests see none), checked on every fetch.
        visible = [(ws, role) for ws, role in await WorkspaceRepository(self.session).list_for_user(user.id)
                   if role is not Role.GUEST]
        if not visible:
            return []
        since = now - LOOKBACK
        stmt = (
            select(Issue, Project, Workspace.slug)
            .join(Project, Project.id == Issue.project_id)
            .join(Workspace, Workspace.id == Issue.workspace_id)
            .where(
                or_(*(and_(Issue.workspace_id == ws.id, visible_to(user.id, role)) for ws, role in visible)),
                or_(Issue.due >= since.date(), Issue.scheduled >= since),
            )
            .order_by(Issue.created_at)
            .limit(MAX_EVENTS)
        )
        if scope is FeedScope.MINE:
            watching = select(IssueWatcher.issue_id).where(IssueWatcher.user_id == user.id)
            stmt = stmt.where(or_(Issue.assignee_user_id == user.id, Issue.id.in_(watching)))
        events: list[CalendarEvent] = []
        for issue, project, slug in (await self.session.execute(stmt)).all():
            if issue.due and issue.due >= since.date():
                events.append(self._event(issue, project, slug, "due", issue.due))
            if issue.scheduled and issue.scheduled >= since:
                events.append(self._event(issue, project, slug, "scheduled", issue.scheduled))
        return events

    def _event(self, issue: Issue, project: Project, slug: str, kind: str, start: date | datetime) -> CalendarEvent:
        title = f"{issue.key} {issue.title}"
        summary = f"Due: {title}" if kind == "due" else title
        if issue.status is IssueStatus.DONE:
            summary = f"✓ {summary}"  # done issues stay visible as history
        app = self.settings.app_url.rstrip("/")
        return CalendarEvent(
            uid=f"{issue.id}-{kind}@pmagent",
            summary=summary,
            start=start,
            description=f"{project.name} · {issue.type} · {issue.status.value.replace('_', ' ')} · {issue.priority}",
            url=f"{app}/w/{slug}/p/{project.key}/board?issue={issue.key}",
            categories=[project.key],
        )
