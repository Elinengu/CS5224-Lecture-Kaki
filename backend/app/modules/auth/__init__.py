"""Public authentication interface for the application and other modules."""

from .api import router
from .dependencies import get_current_user
from .schemas import CurrentUser

__all__ = ["CurrentUser", "get_current_user", "router"]
