"""Approval modes: the lowest of what's asked, the workspace's cap, and the person's own right."""
from types import SimpleNamespace

from dotrix_backend.modules.agents.unattended import accepting, audit_action
from dotrix_backend.modules.workspaces.approval_modes import (
    ApprovalMode,
    cap_of,
    default_of,
    effective,
)
from dotrix_backend.modules.workspaces.models import Role, WorkspaceKind
from dotrix_engine.builtins import builtin_specs

M, A, X = ApprovalMode.MANUAL, ApprovalMode.ACCEPT_EDITS, ApprovalMode.AUTO


def _ws(kind=WorkspaceKind.ORGANIZATION, cap=None, paused=False, grants=()):
    return SimpleNamespace(kind=kind, approval_mode_cap=cap, unattended_paused=paused, member_permissions=list(grants))


def _member(role=Role.OWNER, **ws):
    return SimpleNamespace(role=role, workspace=_ws(**ws))


def test_caps_and_defaults_by_kind() -> None:
    assert (cap_of(_ws()), default_of(_ws())) == (M, M)  # an organisation: Manual until its owners say
    personal = _ws(kind=WorkspaceKind.PERSONAL)
    assert (cap_of(personal), default_of(personal)) == (X, A)  # yours: Accept edits, Auto allowed
    assert cap_of(_ws(cap="accept_edits")) == A and default_of(_ws(cap="auto")) == M
    assert cap_of(_ws(kind=WorkspaceKind.PERSONAL, paused=True)) == M  # paused: everyone back on Manual


def test_the_mode_in_effect_is_the_lowest() -> None:
    assert effective(None, _member(cap="auto")) == M  # not asked: Manual, as before
    assert effective(X, _member(cap="accept_edits")) == A  # the workspace's cap
    assert effective(A, _member(cap="auto")) == A
    assert effective(X, _member(role=Role.MEMBER, cap="auto")) == M  # may not approve agent changes
    assert effective(X, _member(role=Role.MEMBER, cap="auto", grants=["agents:approve"])) == X
    assert effective(A, _member(cap="auto", paused=True)) == M


def test_accepting_turns_ask_into_allow_but_never_lifts_a_block() -> None:
    pm, *rest = builtin_specs()
    blocked = pm.model_copy(update={"autonomy": {"issues.update": "block"}})
    specs, turned = accepting([blocked, *rest], _member())
    assert specs[0].rule("issues.update") == "block" and specs[0].rule("issues.create") == "allow"
    assert "issues.update" not in turned[pm.handle] and "knowledge.write" in turned[pm.handle]
    # What the person can't do themselves stays asking (a member can't edit documents by default).
    member_specs, _ = accepting([pm], _member(role=Role.MEMBER))
    assert member_specs[0].rule("knowledge.write") == "ask" and member_specs[0].rule("issues.create") == "allow"


def test_changes_through_a_mode_are_audited_apart_from_standing_rules() -> None:
    assert audit_action("issues.create", {"mode": "accept_edits"}) == "issues.create.accepted"
    assert audit_action("issues.create", {"agent": "x", "version": 1}) == "issues.create.allowed"
