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


def local_ai_status(settings):
    """Ollama status when Ollama is the configured provider, else None."""
    if (settings.ai.provider or "").lower() != "ollama":
        return None
    from behance_studio.ai.ollama import DEFAULT_MODEL, DEFAULT_URL, detect

    return detect(settings.ai.base_url or DEFAULT_URL, settings.ai.model or DEFAULT_MODEL)
