"""Import every ORM model here so Base.metadata is complete for Alembic."""
from pmagent_backend.modules.api_tokens import models as _api_tokens  # noqa: F401
from pmagent_backend.modules.auth import models as _auth  # noqa: F401
from pmagent_backend.modules.invites import models as _invites  # noqa: F401
from pmagent_backend.modules.workspaces import models as _workspaces  # noqa: F401

from .base import Base

__all__ = ["Base"]
