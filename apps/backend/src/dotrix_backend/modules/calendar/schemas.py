from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from .models import FeedScope


class CalendarFeedRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    scope: FeedScope = Field(
        description="`mine`: issues assigned to you or that you watch; `all`: every dated issue in your projects"
    )
    created_at: datetime
    last_used_at: datetime | None = Field(description="When a calendar app last fetched the feed")


class CalendarFeedCreated(CalendarFeedRead):
    url: str = Field(description="The feed's secret address. Shown only now; turn the feed on again for a new one.")


class CalendarFeedCreate(BaseModel):
    scope: FeedScope = FeedScope.MINE


class CalendarFeedUpdate(BaseModel):
    scope: FeedScope
