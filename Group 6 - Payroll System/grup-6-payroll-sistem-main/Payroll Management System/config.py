from __future__ import annotations

from pathlib import Path
from typing import Final

BASE_DIR: Final[Path] = Path(__file__).resolve().parent
DATABASE_DIR: Final[Path] = BASE_DIR / "database"
DATABASE_PATH: Final[Path] = DATABASE_DIR / "payroll.db"
ASSETS_DIR: Final[Path] = BASE_DIR / "assets"

APP_NAME: Final[str] = "BNU Payroll Management System"
APP_VERSION: Final[str] = "2.0.0"
UNIVERSITY_NAME: Final[str] = "Biringan National University"
UNIVERSITY_TAGLINE: Final[str] = "Human Resource & Payroll Control Center"

# ── BNU Brand Palette ────────────────────────────────────────────────────────
# Primary navy (seal ring, sidebar)
PRIMARY_COLOR: Final[str] = "#0D2B5E"
# Bright sky-blue (wave accent, buttons)
ACCENT_BLUE: Final[str] = "#1A6FBF"
# Light sky used on header/cards
LIGHT_BLUE: Final[str] = "#D6EAF8"
# Gold / yellow used on seal and highlights
GOLD_COLOR: Final[str] = "#D4A017"
GOLD_LIGHT: Final[str] = "#F5D98B"
# Sidebar gradient end
SIDEBAR_END: Final[str] = "#1A3A6B"

# Neutrals
BACKGROUND_COLOR: Final[str] = "#F4F7FB"
SECONDARY_COLOR: Final[str] = "#F8FAFC"
TEXT_COLOR: Final[str] = "#1B2A3B"
MUTED_COLOR: Final[str] = "#6B7D93"
BORDER_COLOR: Final[str] = "#E1E8F0"
WHITE: Final[str] = "#FFFFFF"

# Semantic
SUCCESS_COLOR: Final[str] = "#15966A"
WARNING_COLOR: Final[str] = "#D4A017"
DANGER_COLOR: Final[str] = "#dc2626"

# ── Typography ────────────────────────────────────────────────────────────────
DEFAULT_FONT: Final[tuple] = ("Segoe UI", 11)
SMALL_FONT: Final[tuple] = ("Segoe UI", 10)
TITLE_FONT: Final[tuple] = ("Segoe UI", 22, "bold")
HEADING_FONT: Final[tuple] = ("Segoe UI", 13, "bold")
SUBHEADING_FONT: Final[tuple] = ("Segoe UI", 11, "bold")
LARGE_NUM_FONT: Final[tuple] = ("Segoe UI", 28, "bold")
SIDEBAR_TITLE_FONT: Final[tuple] = ("Segoe UI", 14, "bold")
SIDEBAR_SUB_FONT: Final[tuple] = ("Segoe UI", 9)


def ensure_directories() -> None:
    """Create the directories required by the application."""
    DATABASE_DIR.mkdir(parents=True, exist_ok=True)
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
