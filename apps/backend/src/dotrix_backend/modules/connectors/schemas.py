from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class InstallationRead(BaseModel):
    """The GitHub App installed on a GitHub account, added to this workspace."""

    id: uuid.UUID = Field(description="This workspace's reference to it (not GitHub's id)")
    installation_id: int = Field(description="GitHub's id for the installation")
    account_login: str = Field(description="The GitHub user or organisation it's installed on")
    account_type: str = Field(description="`User` or `Organization`")
    suspended: bool
    created_at: datetime


class GitHubStatus(BaseModel):
    configured: bool = Field(description="The GitHub App is set up on this server")
    install_url: str | None = Field(description="GitHub's page to install the app (add `?state=`)")
    installations: list[InstallationRead]


class InstallationAdd(BaseModel):
    """Add an installation the person just made (or can manage): GitHub's `installation_id`, and
    the `code` from a GitHub sign-in right after, which proves they can manage it."""

    installation_id: int = Field(gt=0)
    code: str = Field(min_length=1, max_length=200)


class RepoOption(BaseModel):
    """A repo one of the workspace's installations can see, and which project uses it, if any."""

    installation_ref: uuid.UUID
    github_repo_id: int
    full_name: str
    private: bool
    default_branch: str
    html_url: str
    project_key: str | None = Field(description="The project here it's connected to, if any")


class RepoConnect(BaseModel):
    installation_ref: uuid.UUID = Field(description="Which of the workspace's installations reaches it")
    github_repo_id: int = Field(gt=0)


class ConnectedRepoRead(BaseModel):
    """The repository a project's code lives in, connected through the GitHub App."""

    full_name: str
    html_url: str
    private: bool
    default_branch: str
    account_login: str = Field(description="The GitHub account whose installation reaches it")
    connected_at: datetime
    connected_by_id: uuid.UUID | None
    last_push_sha: str | None = Field(description="The default branch's latest commit we heard of")
    last_push_at: datetime | None
    checkout_sha: str | None = Field(description="The commit agents read (null until the first sync)")
    checked_out_at: datetime | None
    checkout_error: str | None = Field(description="Why the last sync didn't work (null when it did)")


class RepoCreate(BaseModel):
    installation_ref: uuid.UUID = Field(description="The organisation's installation to create it in")
    name: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9._-]+$")
    private: bool = True
    description: str = Field(default="", max_length=350)
