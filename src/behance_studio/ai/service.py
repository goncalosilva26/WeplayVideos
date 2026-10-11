"""Optional AI services used by the generation pipeline (see ai/ providers)."""

from __future__ import annotations


def service_for_project(project, settings):
    """Return an AI service for this project, or None when AI is not
    configured or the project has not authorised it."""
    if settings.ai.provider in ("", "none"):
        return None
    try:
        from behance_studio.ai.orchestrator import AIService
    except ImportError:  # pragma: no cover
        return None
    return AIService.create(project, settings)
