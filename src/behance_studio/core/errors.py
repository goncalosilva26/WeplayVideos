"""Exception hierarchy.

``UserFacingError`` carries a message that is safe to show in a dialog. Its
``detail`` holds technical information that goes to the diagnostics log only.
"""

from __future__ import annotations


class BehanceStudioError(Exception):
    """Base class for all application errors."""


class UserFacingError(BehanceStudioError):
    def __init__(self, message: str, detail: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail


class ProjectError(UserFacingError):
    pass


class AssetError(UserFacingError):
    pass


class ScriptError(UserFacingError):
    pass


class RenderError(UserFacingError):
    pass


class ExportError(UserFacingError):
    pass


class ProviderError(UserFacingError):
    pass


class OperationCancelled(BehanceStudioError):
    """Raised inside long-running work when the user cancels it."""
