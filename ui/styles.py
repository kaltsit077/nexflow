"""Layout tokens + QSS. Built-in palettes; one visual language per theme."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

# Spacing — only these steps between major zones / lists
GAP = 12
GAP_SM = 8
PAD = 14

DEFAULT_THEME = "nexgen"


@dataclass(frozen=True)
class Palette:
    id: str
    label: str
    dark: bool
    BG: str
    SURFACE: str
    SURFACE_2: str
    SURFACE_HOVER: str
    BUTTON_HOVER: str
    BORDER: str
    BORDER_STRONG: str
    TEXT: str
    TEXT_MUTED: str
    ACCENT: str
    ACCENT_HOVER: str
    ACCENT_PRESSED: str
    ACCENT_SOFT: str
    ACCENT_DIM: str
    ON_ACCENT: str
    DANGER: str
    DANGER_HOVER: str
    DANGER_SOFT: str
    DANGER_BORDER: str
    DANGER_HOVER_BG: str
    PREVIEW_BG: str
    PREVIEW_BORDER: str
    SCROLL: str
    DISABLED: str
    DISABLED_BG: str


PALETTES: dict[str, Palette] = {
    "nexgen": Palette(
        id="nexgen",
        label="次世代 · 电青绿",
        dark=True,
        BG="#0B0F14",
        SURFACE="#12181F",
        SURFACE_2="#1A222D",
        SURFACE_HOVER="#1E2834",
        BUTTON_HOVER="#222C38",
        BORDER="#2A3544",
        BORDER_STRONG="#3D4F63",
        TEXT="#E8EEF6",
        TEXT_MUTED="#8B9BB0",
        ACCENT="#2EE6A6",
        ACCENT_HOVER="#5EF0BC",
        ACCENT_PRESSED="#22C98F",
        ACCENT_SOFT="#143028",
        ACCENT_DIM="#1A3D30",
        ON_ACCENT="#04140E",
        DANGER="#FF6B7A",
        DANGER_HOVER="#FF8A95",
        DANGER_SOFT="#2A1518",
        DANGER_BORDER="#5A2A30",
        DANGER_HOVER_BG="#3A1A20",
        PREVIEW_BG="#070A0E",
        PREVIEW_BORDER="#2A3544",
        SCROLL="#3D4F63",
        DISABLED="#5A6A7C",
        DISABLED_BG="#151B24",
    ),
    "ocean": Palette(
        id="ocean",
        label="深海 · 冰蓝",
        dark=True,
        BG="#070B12",
        SURFACE="#0E1622",
        SURFACE_2="#152233",
        SURFACE_HOVER="#1A2A3E",
        BUTTON_HOVER="#1E3148",
        BORDER="#243447",
        BORDER_STRONG="#35506A",
        TEXT="#E6F1FF",
        TEXT_MUTED="#8AA3BD",
        ACCENT="#3DB8FF",
        ACCENT_HOVER="#6CC9FF",
        ACCENT_PRESSED="#2A9FE6",
        ACCENT_SOFT="#0F2438",
        ACCENT_DIM="#153553",
        ON_ACCENT="#031018",
        DANGER="#FF6B7A",
        DANGER_HOVER="#FF8A95",
        DANGER_SOFT="#2A1518",
        DANGER_BORDER="#5A2A30",
        DANGER_HOVER_BG="#3A1A20",
        PREVIEW_BG="#05080E",
        PREVIEW_BORDER="#243447",
        SCROLL="#35506A",
        DISABLED="#5A7088",
        DISABLED_BG="#101825",
    ),
    "ember": Palette(
        id="ember",
        label="余烬 · 琥珀",
        dark=True,
        BG="#100C0A",
        SURFACE="#1A1410",
        SURFACE_2="#241C16",
        SURFACE_HOVER="#2C221A",
        BUTTON_HOVER="#32281E",
        BORDER="#3A2E24",
        BORDER_STRONG="#564536",
        TEXT="#F5EEE6",
        TEXT_MUTED="#A89888",
        ACCENT="#F0A35A",
        ACCENT_HOVER="#FFB977",
        ACCENT_PRESSED="#D98940",
        ACCENT_SOFT="#2A1C12",
        ACCENT_DIM="#3A2818",
        ON_ACCENT="#1A1008",
        DANGER="#FF6B7A",
        DANGER_HOVER="#FF8A95",
        DANGER_SOFT="#2A1518",
        DANGER_BORDER="#5A2A30",
        DANGER_HOVER_BG="#3A1A20",
        PREVIEW_BG="#0A0806",
        PREVIEW_BORDER="#3A2E24",
        SCROLL="#564536",
        DISABLED="#7A6A5A",
        DISABLED_BG="#181410",
    ),
    "classic": Palette(
        id="classic",
        label="明亮 · 经典绿",
        dark=False,
        BG="#F5F6F8",
        SURFACE="#FFFFFF",
        SURFACE_2="#FFFFFF",
        SURFACE_HOVER="#F0FDF4",
        BUTTON_HOVER="#FAFAFA",
        BORDER="#E5E7EB",
        BORDER_STRONG="#CBD5E1",
        TEXT="#1F2937",
        TEXT_MUTED="#6B7280",
        ACCENT="#22C55E",
        ACCENT_HOVER="#16A34A",
        ACCENT_PRESSED="#15803D",
        ACCENT_SOFT="#DCFCE7",
        ACCENT_DIM="#BBF7D0",
        ON_ACCENT="#FFFFFF",
        DANGER="#EF4444",
        DANGER_HOVER="#DC2626",
        DANGER_SOFT="#FEF2F2",
        DANGER_BORDER="#FECACA",
        DANGER_HOVER_BG="#FEE2E2",
        PREVIEW_BG="#1E1E1E",
        PREVIEW_BORDER="#444444",
        SCROLL="#D1D5DB",
        DISABLED="#9CA3AF",
        DISABLED_BG="#F3F4F6",
    ),
}

# Active palette mirrors (updated by apply_theme)
_current_theme = DEFAULT_THEME
BG = PALETTES[DEFAULT_THEME].BG
SURFACE = PALETTES[DEFAULT_THEME].SURFACE
SURFACE_2 = PALETTES[DEFAULT_THEME].SURFACE_2
SURFACE_HOVER = PALETTES[DEFAULT_THEME].SURFACE_HOVER
BUTTON_HOVER = PALETTES[DEFAULT_THEME].BUTTON_HOVER
BORDER = PALETTES[DEFAULT_THEME].BORDER
BORDER_STRONG = PALETTES[DEFAULT_THEME].BORDER_STRONG
TEXT = PALETTES[DEFAULT_THEME].TEXT
TEXT_MUTED = PALETTES[DEFAULT_THEME].TEXT_MUTED
ACCENT = PALETTES[DEFAULT_THEME].ACCENT
ACCENT_HOVER = PALETTES[DEFAULT_THEME].ACCENT_HOVER
ACCENT_PRESSED = PALETTES[DEFAULT_THEME].ACCENT_PRESSED
ACCENT_SOFT = PALETTES[DEFAULT_THEME].ACCENT_SOFT
ACCENT_DIM = PALETTES[DEFAULT_THEME].ACCENT_DIM
ON_ACCENT = PALETTES[DEFAULT_THEME].ON_ACCENT
DANGER = PALETTES[DEFAULT_THEME].DANGER
DANGER_HOVER = PALETTES[DEFAULT_THEME].DANGER_HOVER
DANGER_SOFT = PALETTES[DEFAULT_THEME].DANGER_SOFT
DANGER_BORDER = PALETTES[DEFAULT_THEME].DANGER_BORDER
DANGER_HOVER_BG = PALETTES[DEFAULT_THEME].DANGER_HOVER_BG
PREVIEW_BG = PALETTES[DEFAULT_THEME].PREVIEW_BG
PREVIEW_BORDER = PALETTES[DEFAULT_THEME].PREVIEW_BORDER
SCROLL = PALETTES[DEFAULT_THEME].SCROLL
DISABLED = PALETTES[DEFAULT_THEME].DISABLED
DISABLED_BG = PALETTES[DEFAULT_THEME].DISABLED_BG


def list_themes() -> list[tuple[str, str]]:
    """Return (id, label) for built-in palettes in display order."""
    order = ("nexgen", "ocean", "ember", "classic")
    return [(tid, PALETTES[tid].label) for tid in order if tid in PALETTES]


def current_theme() -> str:
    return _current_theme


def resolve_theme(theme_id: Optional[str]) -> str:
    if theme_id and theme_id in PALETTES:
        return theme_id
    return DEFAULT_THEME


def _sync_globals(p: Palette) -> None:
    g = globals()
    for field in (
        "BG",
        "SURFACE",
        "SURFACE_2",
        "SURFACE_HOVER",
        "BUTTON_HOVER",
        "BORDER",
        "BORDER_STRONG",
        "TEXT",
        "TEXT_MUTED",
        "ACCENT",
        "ACCENT_HOVER",
        "ACCENT_PRESSED",
        "ACCENT_SOFT",
        "ACCENT_DIM",
        "ON_ACCENT",
        "DANGER",
        "DANGER_HOVER",
        "DANGER_SOFT",
        "DANGER_BORDER",
        "DANGER_HOVER_BG",
        "PREVIEW_BG",
        "PREVIEW_BORDER",
        "SCROLL",
        "DISABLED",
        "DISABLED_BG",
    ):
        g[field] = getattr(p, field)


def apply_app_palette(app: QApplication) -> None:
    """Apply Fusion + QPalette from the currently synced theme tokens."""
    p = PALETTES[_current_theme]
    app.setStyle("Fusion")
    try:
        scheme = Qt.ColorScheme.Dark if p.dark else Qt.ColorScheme.Light
        app.styleHints().setColorScheme(scheme)
    except Exception:  # noqa: BLE001
        pass
    pal = QPalette()
    pal.setColor(QPalette.Window, QColor(BG))
    pal.setColor(QPalette.WindowText, QColor(TEXT))
    pal.setColor(QPalette.Base, QColor(SURFACE))
    pal.setColor(QPalette.AlternateBase, QColor(BG))
    pal.setColor(QPalette.Text, QColor(TEXT))
    pal.setColor(QPalette.Button, QColor(SURFACE))
    pal.setColor(QPalette.ButtonText, QColor(TEXT))
    pal.setColor(QPalette.PlaceholderText, QColor(TEXT_MUTED))
    pal.setColor(QPalette.Highlight, QColor(ACCENT))
    pal.setColor(QPalette.HighlightedText, QColor(ON_ACCENT))
    pal.setColor(QPalette.ToolTipBase, QColor(SURFACE))
    pal.setColor(QPalette.ToolTipText, QColor(TEXT))
    pal.setColor(QPalette.BrightText, QColor(TEXT))
    pal.setColor(QPalette.Link, QColor(ACCENT))
    pal.setColor(QPalette.Mid, QColor(BORDER))
    pal.setColor(QPalette.Light, QColor(ACCENT_SOFT))
    pal.setColor(QPalette.Dark, QColor(BG))
    pal.setColor(QPalette.Shadow, QColor("#000000"))
    app.setPalette(pal)


def apply_theme(app: QApplication, theme_id: Optional[str] = None) -> str:
    """Switch built-in palette, sync tokens, re-apply QPalette + QSS. Returns id."""
    global _current_theme
    tid = resolve_theme(theme_id)
    _sync_globals(PALETTES[tid])
    _current_theme = tid
    apply_app_palette(app)
    app.setStyleSheet(app_stylesheet())
    return tid


def app_stylesheet() -> str:
    g, gs, p = GAP, GAP_SM, PAD
    return f"""
    QMainWindow, QDialog {{
        background: {BG};
        color: {TEXT};
        font-size: 13px;
    }}
    QWidget#shell, QWidget#pane, QWidget#cardsHost, QWidget#queueBody, QFrame#connStrip {{
        background: transparent;
        color: {TEXT};
    }}
    QFrame#zone {{
        background: {SURFACE};
        border: 1px solid {BORDER};
        border-radius: 12px;
    }}
    QFrame#toolbarStrip {{
        background: {SURFACE_2};
        border: 1px solid {BORDER};
        border-radius: 10px;
    }}
    QLabel {{
        color: {TEXT};
        background: transparent;
    }}
    QLabel#title {{
        font-size: 18px;
        font-weight: 700;
        color: {TEXT};
        letter-spacing: 0.02em;
    }}
    QLabel#zoneTitle {{
        font-size: 12px;
        font-weight: 700;
        color: {TEXT_MUTED};
        letter-spacing: 0.08em;
        text-transform: uppercase;
    }}
    QLabel#muted {{
        color: {TEXT_MUTED};
        font-size: 12px;
    }}
    QLabel#badge {{
        background: {ACCENT_SOFT};
        color: {ACCENT};
        border: 1px solid {ACCENT_DIM};
        border-radius: 6px;
        padding: 2px 8px;
        font-size: 11px;
        font-weight: 700;
    }}
    QLabel#queueTitle {{
        font-size: 14px;
        font-weight: 600;
        color: {TEXT};
    }}
    QLabel#scriptName {{
        font-size: 13px;
        font-weight: 600;
        color: {TEXT};
    }}
    QLabel#stepNum {{
        font-size: 16px;
        font-weight: 700;
        color: {TEXT_MUTED};
    }}
    QLabel#stepTitle {{
        font-size: 14px;
        font-weight: 600;
        color: {TEXT};
    }}
    QLabel#previewCanvas {{
        background: {PREVIEW_BG};
        color: {TEXT_MUTED};
        border: 1px solid {PREVIEW_BORDER};
        border-radius: 10px;
    }}

    /* Steps = only card surface in compose */
    QFrame#stepCard {{
        background: {SURFACE_2};
        border: 1px solid {BORDER};
        border-radius: 10px;
        color: {TEXT};
    }}
    QFrame#stepCard:hover {{
        border-color: {BORDER_STRONG};
        background: {SURFACE_HOVER};
    }}
    QFrame#queueSection {{
        background: transparent;
        border: 1px solid {BORDER};
        border-radius: 12px;
        color: {TEXT};
    }}
    QFrame#queueSection[activeQueue="true"] {{
        border: 1px solid {ACCENT};
        background: {ACCENT_SOFT};
    }}
    QFrame#queueSection[dropHover="true"] {{
        border: 1px dashed {ACCENT};
        background: {ACCENT_DIM};
    }}
    QFrame#queueHeader {{
        background: {SURFACE};
        border: none;
        border-bottom: 1px solid {BORDER};
        border-top-left-radius: 12px;
        border-top-right-radius: 12px;
    }}

    /* Library = flat rows, not second card system */
    QFrame#scriptRow {{
        background: transparent;
        border: none;
        border-bottom: 1px solid {BORDER};
        border-radius: 0;
        color: {TEXT};
    }}
    QFrame#scriptRow:hover {{
        background: {ACCENT_SOFT};
    }}

    QPushButton {{
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 {SURFACE_HOVER}, stop:1 {SURFACE_2});
        border: 1px solid {BORDER};
        border-radius: 10px;
        padding: 8px 16px;
        color: {TEXT};
        font-weight: 600;
        letter-spacing: 0.02em;
        min-height: 18px;
    }}
    QPushButton:hover {{
        border-color: {ACCENT_DIM};
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 {BUTTON_HOVER}, stop:1 {SURFACE_HOVER});
        color: {TEXT};
    }}
    QPushButton:pressed {{
        background: {SURFACE};
        border-color: {ACCENT};
        padding-top: 9px;
        padding-bottom: 7px;
    }}
    QPushButton:disabled {{
        color: {DISABLED};
        background: {DISABLED_BG};
        border-color: {BORDER};
    }}
    QPushButton#primary {{
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 {ACCENT_HOVER}, stop:0.55 {ACCENT}, stop:1 {ACCENT_PRESSED});
        border: 1px solid {ACCENT_HOVER};
        color: {ON_ACCENT};
        font-weight: 700;
        letter-spacing: 0.04em;
        padding: 9px 20px;
        border-radius: 10px;
    }}
    QPushButton#primary:hover {{
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 {ACCENT_HOVER}, stop:1 {ACCENT});
        border-color: {ACCENT_HOVER};
    }}
    QPushButton#primary:pressed {{
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 {ACCENT}, stop:1 {ACCENT_PRESSED});
        border-color: {ACCENT_PRESSED};
        padding-top: 10px;
        padding-bottom: 8px;
    }}
    QPushButton#primary:disabled {{
        background: {ACCENT_DIM};
        border-color: {ACCENT_DIM};
        color: {DISABLED};
    }}
    QPushButton#secondary, QPushButton#ghost {{
        background: {ACCENT_SOFT};
        border: 1px solid {ACCENT_DIM};
        color: {ACCENT};
        font-weight: 600;
        letter-spacing: 0.03em;
    }}
    QPushButton#secondary:hover, QPushButton#ghost:hover {{
        background: {ACCENT_DIM};
        border-color: {ACCENT};
        color: {ACCENT_HOVER};
    }}
    QPushButton#secondary:pressed, QPushButton#ghost:pressed {{
        background: {ACCENT_SOFT};
        border-color: {ACCENT_PRESSED};
        color: {ACCENT};
    }}
    QPushButton#danger {{
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 {DANGER_HOVER_BG}, stop:1 {DANGER_SOFT});
        border: 1px solid {DANGER_BORDER};
        color: {DANGER};
        font-weight: 600;
    }}
    QPushButton#danger:hover {{
        background: {DANGER_HOVER_BG};
        border-color: {DANGER};
        color: {DANGER_HOVER};
    }}
    QPushButton#danger:pressed {{
        background: {DANGER_SOFT};
        border-color: {DANGER};
    }}
    QPushButton#icon {{
        min-width: 34px;
        max-width: 38px;
        padding: 6px 8px;
        border-radius: 8px;
        font-weight: 700;
    }}
    QPushButton#linkish, QPushButton#chevron {{
        background: transparent;
        border: none;
        color: {ACCENT};
        padding: 4px 8px;
        font-weight: 600;
        letter-spacing: 0.02em;
    }}
    QPushButton#linkish:hover, QPushButton#chevron:hover {{
        color: {ACCENT_HOVER};
        background: {ACCENT_SOFT};
        border-radius: 6px;
    }}
    QPushButton#chevron {{
        color: {TEXT_MUTED};
    }}
    QToolButton#primary {{
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 {ACCENT_HOVER}, stop:1 {ACCENT});
        border: 1px solid {ACCENT_HOVER};
        border-radius: 10px;
        color: {ON_ACCENT};
        font-weight: 700;
        padding: 6px 12px;
    }}
    QToolButton#primary:hover {{
        background: {ACCENT_HOVER};
    }}
    QToolButton#primary::menu-button {{
        border-left: 1px solid rgba(0, 0, 0, 0.25);
        width: 16px;
    }}

    QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QTextEdit, QPlainTextEdit,
    QListWidget, QTableWidget, QTreeWidget {{
        background: {SURFACE_2};
        color: {TEXT};
        border: 1px solid {BORDER};
        border-radius: 8px;
        padding: 7px 10px;
        selection-background-color: {ACCENT_DIM};
        selection-color: {TEXT};
    }}
    QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus,
    QTextEdit:focus, QPlainTextEdit:focus {{
        border-color: {ACCENT};
    }}
    QComboBox::drop-down {{
        border: none;
        width: 22px;
    }}
    QComboBox QAbstractItemView {{
        background: {SURFACE};
        color: {TEXT};
        border: 1px solid {BORDER};
        selection-background-color: {ACCENT_DIM};
        selection-color: {TEXT};
        outline: 0;
        padding: 4px;
    }}
    QListWidget::item, QTreeWidget::item {{
        padding: 4px 6px;
        border-radius: 6px;
    }}
    QListWidget::item:selected, QTreeWidget::item:selected {{
        background: {ACCENT_DIM};
        color: {TEXT};
    }}
    QListWidget::item:hover, QTreeWidget::item:hover {{
        background: {SURFACE_2};
    }}
    QAbstractScrollArea, QScrollArea {{
        background: transparent;
        color: {TEXT};
        border: none;
    }}
    QScrollArea > QWidget {{
        background: transparent;
    }}
    QScrollBar:vertical {{
        background: transparent;
        width: 10px;
        margin: 2px;
    }}
    QScrollBar::handle:vertical {{
        background: {SCROLL};
        border-radius: 5px;
        min-height: 28px;
    }}
    QScrollBar::handle:vertical:hover {{
        background: {BORDER_STRONG};
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
        background: transparent;
        height: 0;
    }}
    QScrollBar:horizontal {{
        background: transparent;
        height: 10px;
        margin: 2px;
    }}
    QScrollBar::handle:horizontal {{
        background: {SCROLL};
        border-radius: 5px;
        min-width: 28px;
    }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal,
    QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
        background: transparent;
        width: 0;
    }}
    QSplitter::handle {{
        background: transparent;
        width: {g}px;
        height: {g}px;
    }}
    QStatusBar {{
        background: {SURFACE};
        border-top: 1px solid {BORDER};
        color: {TEXT_MUTED};
    }}
    QGroupBox {{
        background: {SURFACE};
        color: {TEXT};
        border: 1px solid {BORDER};
        border-radius: 12px;
        margin-top: 14px;
        padding: {p}px;
        padding-top: 20px;
        font-weight: 600;
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        subcontrol-position: top left;
        left: {p}px;
        top: 0px;
        padding: 0 8px;
        color: {ACCENT};
        background: {SURFACE};
    }}
    QHeaderView::section {{
        background: {SURFACE};
        color: {TEXT_MUTED};
        border: none;
        border-bottom: 1px solid {BORDER};
        padding: 8px;
        font-weight: 700;
    }}
    QTabWidget::pane {{
        background: {SURFACE};
        border: 1px solid {BORDER};
        border-radius: 12px;
        top: -1px;
        padding: {gs}px;
    }}
    QTabBar::tab {{
        background: transparent;
        color: {TEXT_MUTED};
        border: none;
        border-bottom: 2px solid transparent;
        padding: 10px 16px;
        margin-right: 4px;
        font-weight: 600;
    }}
    QTabBar::tab:selected {{
        color: {ACCENT};
        border-bottom: 2px solid {ACCENT};
        background: transparent;
    }}
    QTabBar::tab:hover:!selected {{
        color: {TEXT};
        background: {SURFACE_2};
        border-radius: 8px 8px 0 0;
    }}
    QCheckBox {{
        color: {TEXT};
        spacing: 8px;
    }}
    QCheckBox::indicator {{
        width: 16px;
        height: 16px;
        border-radius: 4px;
        border: 1px solid {BORDER_STRONG};
        background: {SURFACE_2};
    }}
    QCheckBox::indicator:hover {{
        border-color: {ACCENT};
    }}
    QCheckBox::indicator:checked {{
        background: {ACCENT};
        border-color: {ACCENT};
    }}
    QToolTip {{
        background: {SURFACE_2};
        color: {TEXT};
        border: 1px solid {BORDER};
        border-radius: 6px;
        padding: 6px 8px;
    }}
    QDialogButtonBox QPushButton {{
        min-width: 72px;
    }}
    QMenu {{
        background: {SURFACE};
        color: {TEXT};
        border: 1px solid {BORDER};
        border-radius: 8px;
        padding: 4px;
    }}
    QMenu::item {{
        padding: 6px 16px;
        border-radius: 6px;
    }}
    QMenu::item:selected {{
        background: {ACCENT_DIM};
        color: {TEXT};
    }}
    QMenu::separator {{
        height: 1px;
        background: {BORDER};
        margin: 4px 8px;
    }}
    """
