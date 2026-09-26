"""Import every ORM model here so Base.metadata is complete for Alembic.

Example, once modules have models:
    from pmagent_backend.modules.workspaces import models as _workspaces  # noqa: F401
"""
from .base import Base

__all__ = ["Base"]
