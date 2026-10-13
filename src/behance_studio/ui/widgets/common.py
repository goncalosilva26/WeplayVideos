"""Reusable widgets for the Behance Studio interface."""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Iterable

from PySide6.QtCore import (
    QEasingCurve,
    QPoint,
    QPropertyAnimation,
    QRect,
    QRectF,
    QSize,
    Qt,
    QTimer,
    QVariantAnimation,
    Signal,
)
from PySide6.QtGui import QColor, QDragEnterEvent, QDropEvent, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QLabel,
    QLayout,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
    QWidgetItem,
)

from behance_studio.ui.icons import icon, pixmap
from behance_studio.ui.theme import T
from behance_studio.ui.worker import image_loader


# ------------------------------------------------------------- basic helpers
def label(text: str = "", name: str | None = None, wrap: bool = False, selectable: bool = False) -> QLabel:
    lab = QLabel(text)
    if name:
        lab.setObjectName(name)
    lab.setWordWrap(wrap)
    if selectable:
        lab.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return lab


def hline() -> QFrame:
    line = QFrame()
    line.setObjectName("Divider")
    line.setFrameShape(QFrame.Shape.NoFrame)
    return line


def button(text: str, icon_name: str | None = None, kind: str | None = None, tooltip: str = "", on_click: Callable | None = None) -> QPushButton:
    btn = QPushButton(text)
    if kind:
        btn.setObjectName(kind)
    if icon_name:
        color = "#FFFFFF" if kind == "Primary" else T.text2
        btn.setIcon(icon(icon_name, color, "#FFFFFF" if kind == "Primary" else T.text))
        btn.setIconSize(QSize(16, 16))
    if tooltip:
        btn.setToolTip(tooltip)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    if on_click:
        btn.clicked.connect(on_click)
    return btn


def tool_button(icon_name: str, tooltip: str, on_click: Callable | None = None, checkable: bool = False, size: int = 18) -> QToolButton:
    btn = QToolButton()
    btn.setIcon(icon(icon_name))
    btn.setIconSize(QSize(size, size))
    btn.setToolTip(tooltip)
    btn.setCheckable(checkable)
    btn.setCursor(Qt.CursorShape.PointingHandCursor)
    if on_click:
        btn.clicked.connect(on_click)
    return btn


class Card(QFrame):
    clicked = Signal()
    double_clicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

    def set_selected(self, selected: bool) -> None:
        self.setObjectName("CardSelected" if selected else "Card")
        self.style().unpolish(self)
        self.style().polish(self)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        self.double_clicked.emit()
        super().mouseDoubleClickEvent(event)


class Badge(QLabel):
    def __init__(self, text: str, color: str | None = None, fg: str | None = None) -> None:
        super().__init__(text)
        self.setObjectName("Badge")
        if color:
            self.setStyleSheet(f"background:{color};color:{fg or '#0E0F11'};border-radius:9px;padding:2px 8px;font-size:8pt;font-weight:600;")


class PageHeader(QWidget):
    def __init__(self, title: str, subtitle: str = "", eyebrow: str = "") -> None:
        super().__init__()
        self.setObjectName("PageHeader")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)
        texts = QVBoxLayout()
        texts.setSpacing(2)
        if eyebrow:
            self.eyebrow = label(eyebrow.upper(), "Eyebrow")
            texts.addWidget(self.eyebrow)
        self.title = label(title, "H1")
        texts.addWidget(self.title)
        self.subtitle = label(subtitle, "Muted", wrap=True)
        if subtitle:
            texts.addWidget(self.subtitle)
        lay.addLayout(texts, 1)
        self.actions = QHBoxLayout()
        self.actions.setSpacing(8)
        lay.addLayout(self.actions)

    def add_action(self, widget: QWidget) -> QWidget:
        self.actions.addWidget(widget)
        return widget

    def set_subtitle(self, text: str) -> None:
        if self.subtitle.parent() is None or not self.subtitle.isVisible():
            self.layout().itemAt(0).layout().addWidget(self.subtitle)
        self.subtitle.setText(text)
        self.subtitle.setVisible(bool(text))


# ------------------------------------------------------------------ layouts
class FlowLayout(QLayout):
    """Wrapping layout for card grids."""

    def __init__(self, parent: QWidget | None = None, spacing: int = 16) -> None:
        super().__init__(parent)
        self._items: list = []
        self._spacing = spacing
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item) -> None:  # noqa: N802
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int):  # noqa: N802
        return self._items[index] if 0 <= index < len(self._items) else None

    def takeAt(self, index: int):  # noqa: N802
        return self._items.pop(index) if 0 <= index < len(self._items) else None

    def expandingDirections(self):  # noqa: N802
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802
        return self._do_layout(QRect(0, 0, width, 0), True)

    def setGeometry(self, rect: QRect) -> None:  # noqa: N802
        super().setGeometry(rect)
        self._do_layout(rect, False)

    def sizeHint(self) -> QSize:  # noqa: N802
        return self.minimumSize()

    def minimumSize(self) -> QSize:  # noqa: N802
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        m = self.contentsMargins()
        return size + QSize(m.left() + m.right(), m.top() + m.bottom())

    def _do_layout(self, rect: QRect, test: bool) -> int:
        m = self.contentsMargins()
        x, y = rect.x() + m.left(), rect.y() + m.top()
        line_h = 0
        right = rect.right() - m.right()
        for item in self._items:
            w = item.sizeHint()
            if x + w.width() > right + 1 and line_h > 0:
                x = rect.x() + m.left()
                y += line_h + self._spacing
                line_h = 0
            if not test:
                item.setGeometry(QRect(QPoint(x, y), w))
            x += w.width() + self._spacing
            line_h = max(line_h, w.height())
        return y + line_h - rect.y() + m.bottom()

    def clear(self) -> None:
        while self._items:
            item = self._items.pop()
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()


def clear_layout(layout: QLayout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget is not None:
            widget.setParent(None)
            widget.deleteLater()
        elif item.layout() is not None:
            clear_layout(item.layout())


# ----------------------------------------------------------------- images
class Thumb(QWidget):
    """Rounded image that fills its box (cover), loaded asynchronously."""

    def __init__(self, w: int, h: int, radius: int = 8, mode: str = "cover", placeholder: str = T.surface3) -> None:
        super().__init__()
        self.setFixedSize(w, h)
        self._pix: QPixmap | None = None
        self._radius = radius
        self._mode = mode
        self._placeholder = QColor(placeholder)
        self._overlay_text = ""
        self._path: str | None = None

    def set_path(self, path: Path | str | None) -> None:
        self._path = str(path) if path else None
        self._pix = None
        self.update()
        if path:
            target = QSize(self.width() * 2, self.height() * 2) if self._mode == "cover" else QSize(self.width() * 2, self.height() * 2)
            image_loader().load(path, target, self._loaded)

    def _loaded(self, pix: QPixmap) -> None:
        self._pix = pix
        self._backdrop = _transparent_backdrop(pix)
        self.update()

    def set_overlay(self, text: str) -> None:
        self._overlay_text = text
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()), self._radius, self._radius)
        p.setClipPath(path)
        p.fillRect(self.rect(), self._placeholder)
        if self._pix is not None and not self._pix.isNull():
            pw, ph = self._pix.width(), self._pix.height()
            backdrop = getattr(self, "_backdrop", None)
            if backdrop is not None:  # transparent artwork (logos): whole, on a contrasting ground
                p.fillRect(self.rect(), backdrop)
                scale = min(self.width() / pw, self.height() / ph) * 0.82
            elif self._mode == "cover":
                scale = max(self.width() / pw, self.height() / ph)
            else:
                scale = min(self.width() / pw, self.height() / ph)
            w, h = pw * scale, ph * scale
            x = (self.width() - w) / 2
            y = 0 if self._mode == "cover-top" else (self.height() - h) / 2
            if self._mode == "cover" and ph * scale > self.height() and pw / ph < 1:
                y = 0
            p.drawPixmap(QRectF(x, y, w, h), self._pix, QRectF(0, 0, pw, ph))
        if self._overlay_text:
            p.fillRect(self.rect(), QColor(0, 0, 0, 120))
            p.setPen(QColor("#FFFFFF"))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self._overlay_text)
        p.end()


def _transparent_backdrop(pix: QPixmap) -> QColor | None:
    """A ground that contrasts with a transparent image's own ink, or None
    when the image has no transparent area."""
    if pix is None or pix.isNull() or not pix.hasAlphaChannel():
        return None
    img = pix.toImage().scaled(48, 48)
    total = lum = 0.0
    clear = 0
    for y in range(img.height()):
        for x in range(img.width()):
            c = img.pixelColor(x, y)
            a = c.alphaF()
            if a < 0.05:
                clear += 1
            total += a
            lum += a * (0.2126 * c.redF() + 0.7152 * c.greenF() + 0.0722 * c.blueF())
    if clear < img.width() * img.height() * 0.05 or total <= 0:
        return None  # practically opaque
    return QColor("#ECE9E3") if lum / total < 0.6 else QColor("#2B2A28")


class StripPreview(QWidget):
    """Shows the top of a full-length presentation strip; scrolls through the
    whole presentation while hovered, so differences are visible at a glance."""

    def __init__(self, w: int, h: int, radius: int = 10) -> None:
        super().__init__()
        self.setFixedSize(w, h)
        self._pix: QPixmap | None = None
        self._offset = 0.0
        self._radius = radius
        self.placeholder = ""  # shown while there is no image (e.g. "Preparing preview…")
        self._anim = QVariantAnimation(self)
        self._anim.valueChanged.connect(self._set_offset)
        self.setMouseTracking(True)

    def set_path(self, path: Path | str | None) -> None:
        self._pix = None
        self._offset = 0.0
        self.update()
        if path:
            image_loader().load(path, QSize(self.width() * 2, 20000), self._loaded)

    def _loaded(self, pix: QPixmap) -> None:
        self._pix = pix
        self.update()

    def _set_offset(self, value) -> None:
        self._offset = float(value)
        self.update()

    def _max_offset(self) -> float:
        if not self._pix or self._pix.isNull():
            return 0.0
        scaled_h = self._pix.height() * self.width() / self._pix.width()
        return max(0.0, scaled_h - self.height())

    def enterEvent(self, _event) -> None:  # noqa: N802
        end = self._max_offset()
        if end <= 0:
            return
        self._anim.stop()
        self._anim.setStartValue(self._offset)
        self._anim.setEndValue(end)
        self._anim.setDuration(int(max(1200, (end - self._offset) * 2.2)))
        self._anim.setEasingCurve(QEasingCurve.Type.InOutSine)
        self._anim.start()

    def leaveEvent(self, _event) -> None:  # noqa: N802
        self._anim.stop()
        self._anim.setStartValue(self._offset)
        self._anim.setEndValue(0.0)
        self._anim.setDuration(450)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.start()

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()), self._radius, self._radius)
        p.setClipPath(path)
        p.fillRect(self.rect(), QColor(T.surface3))
        if self._pix is not None and not self._pix.isNull():
            scale = self.width() / self._pix.width()
            src = QRectF(0, self._offset / scale, self._pix.width(), self.height() / scale)
            p.drawPixmap(QRectF(self.rect()), self._pix, src)
        elif self.placeholder:
            p.setPen(QColor(T.text2))
            p.drawText(self.rect(), int(Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap), self.placeholder)
        p.end()


# ---------------------------------------------------------------- states
class EmptyState(QWidget):
    def __init__(self, icon_name: str, title: str, text: str, action_text: str = "", on_action: Callable | None = None) -> None:
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.setSpacing(10)
        badge = QLabel()
        badge.setPixmap(pixmap(icon_name, T.text2, 30))
        badge.setFixedSize(64, 64)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setStyleSheet(f"background:{T.surface2};border:1px solid {T.border};border-radius:32px;")
        lay.addWidget(badge, 0, Qt.AlignmentFlag.AlignHCenter)
        t = label(title, "H2")
        t.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(t)
        body = label(text, "Muted", wrap=True)
        body.setAlignment(Qt.AlignmentFlag.AlignCenter)
        body.setMaximumWidth(460)
        lay.addWidget(body, 0, Qt.AlignmentFlag.AlignHCenter)
        if action_text and on_action:
            btn = button(action_text, "plus", "Primary", on_click=on_action)
            lay.addSpacing(6)
            lay.addWidget(btn, 0, Qt.AlignmentFlag.AlignHCenter)


class DropZone(QFrame):
    paths_dropped = Signal(list)
    clicked = Signal()

    def __init__(self, title: str = "Drop files or folders here", subtitle: str = "Folders, ZIP archives, images, SVG, GIF, MP4/MOV/WebM, brief.txt and GUIAO_PROJETO.txt · a \"References\" folder holds inspiration that is never shown", height: int = 150) -> None:
        super().__init__()
        self.setAcceptDrops(True)
        self.setMinimumHeight(height)
        self._hover = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        lay = QVBoxLayout(self)
        lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ic = QLabel()
        ic.setPixmap(pixmap("upload", T.text2, 26))
        ic.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(ic)
        t = label(title, "H3")
        t.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(t)
        s = label(subtitle, "Faint", wrap=True)
        s.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(s)

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        p.setBrush(QColor(T.accent_soft if self._hover else T.surface))
        pen = QPen(QColor(T.accent if self._hover else T.border_strong), 1.4, Qt.PenStyle.DashLine)
        pen.setDashPattern([4, 4])
        p.setPen(pen)
        p.drawRoundedRect(rect, 12, 12)
        p.end()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self._hover = True
            self.update()

    def dragLeaveEvent(self, _event) -> None:  # noqa: N802
        self._hover = False
        self.update()

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        self._hover = False
        self.update()
        paths = [u.toLocalFile() for u in event.mimeData().urls() if u.isLocalFile()]
        if paths:
            self.paths_dropped.emit(paths)
            event.acceptProposedAction()


class Swatches(QWidget):
    def __init__(self, colors: Iterable[str] = (), size: int = 22) -> None:
        super().__init__()
        self._colors = list(colors)
        self._size = size
        self.setFixedHeight(size)

    def set_colors(self, colors: Iterable[str]) -> None:
        self._colors = list(colors)
        self.setMinimumWidth(len(self._colors) * (self._size + 6))
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        for i, c in enumerate(self._colors):
            p.setBrush(QColor(c))
            p.setPen(QPen(QColor(T.border_strong), 1))
            p.drawRoundedRect(QRectF(i * (self._size + 6) + 0.5, 0.5, self._size - 1, self._size - 1), 6, 6)
        p.end()


class Toast(QLabel):
    """Transient confirmation message in the bottom-right corner."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setStyleSheet(f"background:{T.surface3};color:{T.text};border:1px solid {T.border_strong};border-radius:10px;padding:10px 16px;")
        self.setWordWrap(True)
        self.setMaximumWidth(440)
        self.hide()
        self._effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._effect)
        self._anim = QPropertyAnimation(self._effect, b"opacity", self)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._fade)
        self._anim.finished.connect(self._faded)

    def reposition(self) -> None:
        parent = self.parentWidget()
        if parent is not None:
            self.move(parent.width() - self.width() - 24, parent.height() - self.height() - 24)

    def show_message(self, text: str, ms: int = 3200) -> None:
        self.setText(text)
        natural = self.fontMetrics().horizontalAdvance(text) + 36
        self.setFixedWidth(min(440, max(160, natural)))
        self.setFixedHeight(self.heightForWidth(self.width()) if natural > 440 else self.sizeHint().height())
        self.reposition()
        self._anim.stop()
        self._effect.setOpacity(1.0)
        self.show()
        self.raise_()
        self._timer.start(ms)

    def _fade(self) -> None:
        self._anim.setStartValue(1.0)
        self._anim.setEndValue(0.0)
        self._anim.setDuration(400)
        self._anim.start()

    def _faded(self) -> None:
        if self._effect.opacity() < 0.05:
            self.hide()


def section_title(text: str) -> QLabel:
    return label(text.upper(), "Eyebrow")


def expanding() -> QWidget:
    w = QWidget()
    w.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
    return w


__all__ = [
    "label", "hline", "button", "tool_button", "Card", "Badge", "PageHeader", "FlowLayout", "clear_layout",
    "Thumb", "StripPreview", "EmptyState", "DropZone", "Swatches", "Toast", "section_title", "expanding", "QWidgetItem",
]
