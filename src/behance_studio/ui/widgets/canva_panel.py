"""Settings → Canva: connect the user's Canva account (Canva Connect API)."""

from __future__ import annotations

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import QFormLayout, QFrame, QHBoxLayout, QLineEdit, QSpinBox, QVBoxLayout

from behance_studio.canva.connect import DEVELOPER_PORTAL, SCOPES, CanvaConnect
from behance_studio.ui.dialogs.messages import show_error
from behance_studio.ui.widgets.common import button, label

SETUP_STEPS = (
    "Optional — exporting a Canva file never needs this. To send designs straight to your Canva account:\n"
    "1. Open the Canva Developer Portal (button above), sign in and create an integration (Connect API).\n"
    "2. Under Scopes, enable: " + ", ".join(SCOPES) + ".\n"
    "3. Under Authentication, add the redirect URL shown here and generate a client secret.\n"
    "4. Paste the Client ID and the Client secret here and press Connect; approve the request in the browser.\n"
    "Canva's API is free to use. The secret and the sign-in are kept in Windows Credential Manager, never in files. "
    "Canva may require your integration to be reviewed before people outside your team can use it."
)


class CanvaPanel(QFrame):
    def __init__(self, state, toast) -> None:
        super().__init__()
        self.state, self.toast = state, toast
        self.setObjectName("Card")
        self._task = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(8)
        self.status = label("", "H3", wrap=True)
        lay.addWidget(self.status)
        form = QFormLayout()
        s = state.settings.canva
        self.client_id = QLineEdit(s.client_id)
        self.client_id.setPlaceholderText("from the Canva Developer Portal")
        form.addRow("Client ID", self.client_id)
        self.secret = QLineEdit()
        self.secret.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("Client secret", self.secret)
        self.port = QSpinBox()
        self.port.setRange(1024, 65535)
        self.port.setValue(s.redirect_port)
        self.port.valueChanged.connect(lambda _v: self._refresh())
        redirect_row = QHBoxLayout()
        self.redirect = QLineEdit()
        self.redirect.setReadOnly(True)
        redirect_row.addWidget(self.redirect, 1)
        redirect_row.addWidget(self.port)
        redirect_row.addWidget(button("Copy", "copy", "Ghost", on_click=lambda: QGuiApplication.clipboard().setText(self.redirect.text())))
        form.addRow("Redirect URL", redirect_row)
        lay.addLayout(form)
        row = QHBoxLayout()
        self.connect_btn = button("Connect to Canva", "external", "Primary", on_click=self._connect)
        self.cancel_btn = button("Cancel", None, "Ghost", on_click=self._cancel)
        self.disconnect_btn = button("Disconnect", "x", "Ghost", on_click=self._disconnect)
        portal = button("Canva Developer Portal", "external", "Ghost", on_click=lambda: QDesktopServices.openUrl(QUrl(DEVELOPER_PORTAL)))
        for b in (self.connect_btn, self.cancel_btn, self.disconnect_btn, portal):
            row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)
        help_text = label(SETUP_STEPS, "Faint", wrap=True)
        help_text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(help_text)
        self._refresh()

    def client(self) -> CanvaConnect:
        return CanvaConnect(self.client_id.text().strip(), port=self.port.value())

    def save(self) -> None:
        s = self.state.settings.canva
        s.client_id = self.client_id.text().strip()
        s.redirect_port = self.port.value()
        if self.secret.text().strip():
            where = CanvaConnect.store_client_secret(self.secret.text().strip())
            self.secret.clear()
            self.secret.setPlaceholderText("•••••••• (stored securely)" if where == "keyring" else "•••••••• (this session only)")
        self._refresh()

    def _refresh(self) -> None:
        c = self.client()
        self.redirect.setText(c.redirect_uri)
        if not self.secret.text():
            self.secret.setPlaceholderText("•••••••• (stored)" if c.client_secret else "from the Canva Developer Portal")
        busy = self._task is not None
        if busy:
            self.status.setText("Waiting for you to approve Behance Studio in the browser…")
        elif c.connected:
            name = self.state.settings.canva.account_name
            self.status.setText(f"Connected to Canva{' as ' + name if name else ''}. Export to Canva opens designs in your account.")
        elif c.configured:
            self.status.setText("Canva is set up but not connected yet. Press Connect to Canva.")
        else:
            self.status.setText("Not connected. Export to Canva saves a file you import in Canva yourself (free, no setup).")
        self.connect_btn.setVisible(not busy)
        self.connect_btn.setText("Reconnect" if c.connected else "Connect to Canva")
        self.cancel_btn.setVisible(busy)
        self.disconnect_btn.setVisible(c.connected and not busy)

    def _connect(self) -> None:
        self.save()
        self.state.save_settings()
        client = self.client()
        if not client.configured:
            show_error(self, "Enter the Client ID and the Client secret of your Canva integration first.")
            return

        def work(token, progress):
            return client.authorize(cancelled=lambda: token.cancelled)

        def done(name) -> None:
            self._task = None
            self.state.settings.canva.account_name = name or ""
            self.state.save_settings()
            self._refresh()
            self.toast(f"Connected to Canva{' as ' + name if name else ''}")

        def failed(exc) -> None:
            self._task = None
            self._refresh()
            show_error(self, exc, "Canva did not connect")

        def cancelled() -> None:
            self._task = None
            self._refresh()

        self._task = self.state.runner.start(work, "canva-connect", on_done=done, on_error=failed, on_cancel=cancelled)
        self._refresh()

    def _cancel(self) -> None:
        if self._task is not None:
            self._task.cancel()

    def _disconnect(self) -> None:
        self.client().disconnect()
        self.state.settings.canva.account_name = ""
        self.state.save_settings()
        self._refresh()
        self.toast("Disconnected from Canva")
