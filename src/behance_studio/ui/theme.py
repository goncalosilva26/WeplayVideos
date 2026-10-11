"""Behance Studio desktop design system: tokens, fonts and the Qt stylesheet."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtGui import QColor, QFont, QFontDatabase, QPalette
from PySide6.QtWidgets import QApplication

from behance_studio.core.logging_setup import get_logger
from behance_studio.core.paths import FONTS_DIR, ICONS_DIR

log = get_logger(__name__)


@dataclass(frozen=True)
class Tokens:
    bg: str = "#0E0F11"  # window
    sidebar: str = "#0B0C0E"
    surface: str = "#15171A"  # panels
    surface2: str = "#1B1E22"  # cards
    surface3: str = "#23272C"  # hover / inputs
    border: str = "#262A30"
    border_strong: str = "#343941"
    text: str = "#ECEDEF"
    text2: str = "#A6ACB4"
    text3: str = "#6E747C"
    accent: str = "#5B7CFA"
    accent_hover: str = "#7491FF"
    accent_press: str = "#4A69E0"
    accent_soft: str = "#1D2440"
    success: str = "#3CCB7F"
    warning: str = "#F2B63D"
    danger: str = "#F2555A"
    danger_soft: str = "#3A1C1E"
    radius: int = 10
    radius_small: int = 7


T = Tokens()

UI_FONT = "Inter"
DISPLAY_FONT = "Instrument Serif"


def load_fonts() -> None:
    for name in ("Inter-VF.ttf", "InstrumentSerif-Regular.ttf", "InstrumentSerif-Italic.ttf", "JetBrainsMono-VF.ttf"):
        path = FONTS_DIR / name
        if path.exists() and QFontDatabase.addApplicationFont(str(path)) < 0:
            log.warning("Could not load UI font %s", name)


def ui_font(size: float = 10.0, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
    font = QFont(UI_FONT)
    font.setPointSizeF(size)
    font.setWeight(weight)
    font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    return font


def display_font(size: float = 24.0, italic: bool = False) -> QFont:
    font = QFont(DISPLAY_FONT)
    font.setPointSizeF(size)
    font.setItalic(italic)
    return font


def stylesheet(t: Tokens = T) -> str:
    check = (ICONS_DIR / "check.svg").as_posix()
    return f"""
* {{ outline: none; }}
QWidget {{ background: {t.bg}; color: {t.text}; font-family: "{UI_FONT}"; font-size: 10pt; }}
QMainWindow, QDialog {{ background: {t.bg}; }}
QToolTip {{ background: {t.surface3}; color: {t.text}; border: 1px solid {t.border_strong}; padding: 6px 8px; border-radius: 6px; }}

/* ---- sidebar ---- */
#Sidebar {{ background: {t.sidebar}; border-right: 1px solid {t.border}; }}
#Sidebar QLabel {{ background: transparent; }}
#NavButton {{ background: transparent; border: none; border-radius: 8px; color: {t.text2}; text-align: left; padding: 9px 12px; font-size: 10pt; }}
#NavButton:hover {{ background: {t.surface}; color: {t.text}; }}
#NavButton:checked {{ background: {t.surface2}; color: {t.text}; font-weight: 600; }}
#NavButton:disabled {{ color: {t.text3}; }}
#NavSection {{ color: {t.text3}; font-size: 8pt; font-weight: 600; letter-spacing: 1px; padding: 14px 12px 4px 12px; background: transparent; }}
#ProjectChip {{ background: {t.surface}; border: 1px solid {t.border}; border-radius: 10px; }}

/* ---- surfaces ---- */
#Panel {{ background: {t.surface}; border: 1px solid {t.border}; border-radius: {t.radius}px; }}
#Card {{ background: {t.surface2}; border: 1px solid {t.border}; border-radius: {t.radius}px; }}
#Card:hover {{ border-color: {t.border_strong}; }}
#CardSelected {{ background: {t.surface2}; border: 2px solid {t.accent}; border-radius: {t.radius}px; }}
#PageHeader {{ background: transparent; }}
QLabel {{ background: transparent; }}
#H1 {{ font-size: 21pt; font-weight: 600; letter-spacing: -0.3px; }}
#H2 {{ font-size: 13pt; font-weight: 600; }}
#H3 {{ font-size: 10.5pt; font-weight: 600; }}
#Muted {{ color: {t.text2}; }}
#Faint {{ color: {t.text3}; font-size: 9pt; }}
#Eyebrow {{ color: {t.text3}; font-size: 8pt; font-weight: 600; letter-spacing: 1.2px; }}
#Display {{ font-family: "{DISPLAY_FONT}"; font-size: 34pt; color: {t.text}; }}
#Badge {{ background: {t.surface3}; color: {t.text2}; border-radius: 9px; padding: 2px 8px; font-size: 8pt; font-weight: 600; }}
#Divider {{ background: {t.border}; max-height: 1px; min-height: 1px; }}

/* ---- buttons ---- */
QPushButton {{ background: {t.surface3}; color: {t.text}; border: 1px solid {t.border_strong}; border-radius: 8px; padding: 7px 14px; font-weight: 500; }}
QPushButton:hover {{ background: #2B3036; border-color: #414750; }}
QPushButton:pressed {{ background: #20242A; }}
QPushButton:disabled {{ color: {t.text3}; background: {t.surface}; border-color: {t.border}; }}
QPushButton#Primary {{ background: {t.accent}; border: 1px solid {t.accent}; color: white; font-weight: 600; }}
QPushButton#Primary:hover {{ background: {t.accent_hover}; border-color: {t.accent_hover}; }}
QPushButton#Primary:pressed {{ background: {t.accent_press}; }}
QPushButton#Primary:disabled {{ background: #2A3352; border-color: #2A3352; color: #8C96B8; }}
QPushButton#Ghost {{ background: transparent; border: 1px solid transparent; color: {t.text2}; }}
QPushButton#Ghost:hover {{ background: {t.surface3}; color: {t.text}; }}
QPushButton#Danger {{ background: {t.danger_soft}; border: 1px solid #5A2A2D; color: #FFB3B5; }}
QPushButton#Danger:hover {{ background: #4A2225; }}
QPushButton#Chip {{ background: {t.surface}; border: 1px solid {t.border}; border-radius: 14px; padding: 4px 12px; color: {t.text2}; font-size: 9pt; }}
QPushButton#Chip:hover {{ color: {t.text}; border-color: {t.border_strong}; }}
QPushButton#Chip:checked {{ background: {t.accent_soft}; border-color: {t.accent}; color: {t.text}; }}
QToolButton {{ background: transparent; border: none; border-radius: 7px; padding: 5px; color: {t.text2}; }}
QToolButton:hover {{ background: {t.surface3}; color: {t.text}; }}
QToolButton:checked {{ background: {t.accent_soft}; color: {t.text}; }}
QToolButton::menu-indicator {{ image: none; }}

/* ---- inputs ---- */
QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {{
  background: {t.surface}; border: 1px solid {t.border_strong}; border-radius: 8px; padding: 6px 9px; color: {t.text};
  selection-background-color: {t.accent}; selection-color: white; }}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{ border-color: {t.accent}; }}
QPlainTextEdit, QTextEdit {{ padding: 8px; }}
QSpinBox, QDoubleSpinBox {{ padding: 4px 9px; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{ background: {t.surface2}; border: 1px solid {t.border_strong}; selection-background-color: {t.accent_soft}; padding: 4px; }}
QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{ width: 16px; border: none; background: transparent; }}
QCheckBox, QRadioButton {{ spacing: 8px; background: transparent; }}
QCheckBox::indicator, QRadioButton::indicator {{ width: 16px; height: 16px; border: 1px solid {t.border_strong}; background: {t.surface}; }}
QCheckBox::indicator {{ border-radius: 4px; }}
QRadioButton::indicator {{ border-radius: 8px; }}
QCheckBox::indicator:checked, QRadioButton::indicator:checked {{ background: {t.accent}; border-color: {t.accent}; }}
QCheckBox::indicator:checked {{ image: url("{check}"); }}
QSlider::groove:horizontal {{ height: 4px; background: {t.surface3}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {t.accent}; border-radius: 2px; }}
QSlider::handle:horizontal {{ background: white; width: 14px; height: 14px; margin: -5px 0; border-radius: 7px; }}

/* ---- lists / tables / tabs ---- */
QListWidget, QListView, QTreeWidget, QTableWidget {{ background: {t.surface}; border: 1px solid {t.border}; border-radius: 10px; padding: 4px; }}
QListWidget::item, QListView::item {{ border-radius: 7px; padding: 6px; }}
QListWidget::item:hover, QListView::item:hover {{ background: {t.surface3}; }}
QListWidget::item:selected, QListView::item:selected {{ background: {t.accent_soft}; color: {t.text}; }}
QListView::indicator, QTreeView::indicator, QTableView::indicator {{ width: 15px; height: 15px; border: 1px solid {t.border_strong}; border-radius: 4px; background: {t.surface2}; }}
QListView::indicator:checked, QTreeView::indicator:checked, QTableView::indicator:checked {{ background: {t.accent}; border-color: {t.accent}; image: url("{check}"); }}
QHeaderView::section {{ background: {t.surface}; color: {t.text2}; border: none; border-bottom: 1px solid {t.border}; padding: 6px; font-weight: 600; }}
QTableWidget {{ gridline-color: {t.border}; }}
QTabWidget::pane {{ border: none; background: transparent; }}
QTabBar::tab {{ background: transparent; color: {t.text2}; padding: 8px 12px; border-bottom: 2px solid transparent; font-weight: 500; }}
QTabBar::tab:selected {{ color: {t.text}; border-bottom-color: {t.accent}; }}
QTabBar::tab:hover {{ color: {t.text}; }}

/* ---- scrollbars ---- */
QScrollArea {{ background: transparent; border: none; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: #31363D; border-radius: 4px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: #434952; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: #31363D; border-radius: 4px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

/* ---- progress / menus ---- */
QProgressBar {{ background: {t.surface3}; border: none; border-radius: 4px; height: 8px; text-align: center; color: transparent; }}
QProgressBar::chunk {{ background: {t.accent}; border-radius: 4px; }}
QMenu {{ background: {t.surface2}; border: 1px solid {t.border_strong}; border-radius: 10px; padding: 6px; }}
QMenu::item {{ padding: 7px 26px 7px 12px; border-radius: 6px; }}
QMenu::item:selected {{ background: {t.surface3}; }}
QMenu::item:disabled {{ color: {t.text3}; }}
QMenu::separator {{ height: 1px; background: {t.border}; margin: 5px 4px; }}
QSplitter::handle {{ background: {t.border}; }}
QSplitter::handle:horizontal {{ width: 1px; }}
QStatusBar {{ background: {t.sidebar}; color: {t.text3}; border-top: 1px solid {t.border}; }}
QMessageBox {{ background: {t.surface}; }}
QMessageBox QLabel {{ color: {t.text}; }}
"""


def apply_theme(app: QApplication) -> None:
    load_fonts()
    app.setFont(ui_font(10))
    palette = QPalette()
    roles = {
        QPalette.ColorRole.Window: T.bg,
        QPalette.ColorRole.WindowText: T.text,
        QPalette.ColorRole.Base: T.surface,
        QPalette.ColorRole.AlternateBase: T.surface2,
        QPalette.ColorRole.Text: T.text,
        QPalette.ColorRole.Button: T.surface3,
        QPalette.ColorRole.ButtonText: T.text,
        QPalette.ColorRole.Highlight: T.accent,
        QPalette.ColorRole.HighlightedText: "#FFFFFF",
        QPalette.ColorRole.ToolTipBase: T.surface3,
        QPalette.ColorRole.ToolTipText: T.text,
        QPalette.ColorRole.PlaceholderText: T.text3,
        QPalette.ColorRole.Link: T.accent_hover,
    }
    for role, value in roles.items():
        palette.setColor(role, QColor(value))
    app.setPalette(palette)
    app.setStyleSheet(stylesheet())


FAMILY_COLORS = {
    "editorial": "#C9A46A",
    "cinematic": "#E2574C",
    "split": "#5B8DEF",
    "posters": "#F2B63D",
    "gallery": "#9AA5A0",
    "modular": "#7C6CF0",
}
