"""Import every ORM model here so Base.metadata is complete for Alembic."""
from pmagent_backend.modules.agent_definitions import models as _agent_definitions  # noqa: F401
from pmagent_backend.modules.agents import models as _agents  # noqa: F401
from pmagent_backend.modules.api_tokens import models as _api_tokens  # noqa: F401
from pmagent_backend.modules.audit import models as _audit  # noqa: F401
from pmagent_backend.modules.auth import models as _auth  # noqa: F401
from pmagent_backend.modules.calendar import models as _calendar  # noqa: F401
from pmagent_backend.modules.documents import models as _documents  # noqa: F401
from pmagent_backend.modules.invites import models as _invites  # noqa: F401
from pmagent_backend.modules.issues import models as _issues  # noqa: F401
from pmagent_backend.modules.knowledge import models as _knowledge  # noqa: F401
from pmagent_backend.modules.projects import models as _projects  # noqa: F401
from pmagent_backend.modules.research import models as _research  # noqa: F401
from pmagent_backend.modules.search import models as _search  # noqa: F401
from pmagent_backend.modules.workspaces import models as _workspaces  # noqa: F401

from .base import Base

__all__ = ["Base"]
