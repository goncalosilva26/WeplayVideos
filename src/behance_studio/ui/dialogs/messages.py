"""Friendly dialogs. Technical details go to the diagnostics log, never to
ordinary users as raw tracebacks."""

from __future__ import annotations

from PySide6.QtWidgets import QMessageBox, QWidget

from behance_studio.core.errors import UserFacingError
from behance_studio.core.logging_setup import get_logger, log_file_path

log = get_logger(__name__)


def show_error(parent: QWidget | None, exc: BaseException | str, title: str = "Something went wrong") -> None:
    if isinstance(exc, UserFacingError):
        text = exc.message
        if exc.detail:
            log.info("Error detail: %s", exc.detail)
    elif isinstance(exc, str):
        text = exc
    else:
        log.error("Unexpected error shown to user: %r", exc)
        text = "An unexpected problem occurred. Your work has not been lost."
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Warning)
    box.setWindowTitle(title)
    box.setText(text)
    box.setInformativeText(f"Technical details are recorded in the diagnostics log:\n{log_file_path()}")
    box.setStandardButtons(QMessageBox.StandardButton.Ok)
    box.exec()


def confirm(parent: QWidget | None, title: str, text: str, ok: str = "Continue", destructive: bool = False, detail: str = "") -> bool:
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Warning if destructive else QMessageBox.Icon.Question)
    box.setWindowTitle(title)
    box.setText(text)
    if detail:
        box.setInformativeText(detail)
    ok_button = box.addButton(ok, QMessageBox.ButtonRole.DestructiveRole if destructive else QMessageBox.ButtonRole.AcceptRole)
    if destructive:
        ok_button.setObjectName("Danger")
    cancel = box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
    box.setEscapeButton(cancel)
    box.setDefaultButton(cancel if destructive else ok_button)
    box.exec()
    return box.clickedButton() is ok_button


def info(parent: QWidget | None, title: str, text: str, detail: str = "") -> None:
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Information)
    box.setWindowTitle(title)
    box.setText(text)
    if detail:
        box.setInformativeText(detail)
    box.exec()


def choose(parent: QWidget | None, title: str, text: str, buttons: list[str], detail: str = "") -> int | None:
    """Ask with several labelled choices; returns the index clicked (None when closed).

    The last button is treated as "Cancel" (Escape)."""
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Question)
    box.setWindowTitle(title)
    box.setText(text)
    if detail:
        box.setInformativeText(detail)
    made = []
    for i, label in enumerate(buttons):
        role = QMessageBox.ButtonRole.RejectRole if i == len(buttons) - 1 else QMessageBox.ButtonRole.AcceptRole
        made.append(box.addButton(label, role))
    box.setEscapeButton(made[-1])
    box.setDefaultButton(made[0])
    box.exec()
    clicked = box.clickedButton()
    return made.index(clicked) if clicked in made else None
