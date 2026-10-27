"""The fixed product team. Kai executes code through the platform's coding adapter."""
from dataclasses import dataclass
from typing import Literal

from .contracts import PM_HANDLE


@dataclass(frozen=True)
class TeamMember:
    handle: str
    name: str
    role: str
    kind: Literal["coordinator", "specialist", "coding"]


TEAM = (
    TeamMember(PM_HANDLE, "Nova", "Lead adviser", "coordinator"),
    TeamMember("product", "Lyra", "Product", "specialist"),
    TeamMember("architecture", "Orion", "Architecture", "specialist"),
    TeamMember("research", "Vega", "Research", "specialist"),
    TeamMember("reviewer", "Juno", "Review", "specialist"),
    TeamMember("documentation", "Echo", "Documentation", "specialist"),
    TeamMember("coding-agent", "Kai", "Coding", "coding"),
)
THINKING_HANDLES = frozenset(m.handle for m in TEAM if m.kind != "coding")
SPECIALIST_HANDLES = frozenset(m.handle for m in TEAM if m.kind == "specialist")
