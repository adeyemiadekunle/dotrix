"""Host-selected model tiers, independent of any particular runtime or provider."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class ModelSelection:
    model: str
    effort: str | None = None

    def __post_init__(self) -> None:
        if not self.model.strip() or (self.effort is not None and not self.effort.strip()):
            raise ValueError("Model and optional effort must be nonempty")


@dataclass(frozen=True)
class ModelPolicy:
    """Resolve host-configured tiers. Authorization and budget enforcement belong to the caller."""

    tiers: Mapping[str, ModelSelection]
    agents: Mapping[str, str]
    default: str

    def __post_init__(self) -> None:
        if self.default not in self.tiers or any(tier not in self.tiers for tier in self.agents.values()):
            raise ValueError("Every agent and the default must refer to a configured model tier")
        if any(not key for key in self.tiers) or any(not key for key in self.agents):
            raise ValueError("Tier and agent names must be nonempty")

    def resolve(self, agent: str, *, task_tier: str | None = None) -> ModelSelection:
        tier = task_tier if task_tier is not None else self.agents.get(agent, self.default)
        if tier not in self.tiers:
            raise ValueError(f"Unknown model tier: {tier}")
        return self.tiers[tier]
