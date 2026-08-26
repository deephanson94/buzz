"""Terminal color, kept honest: ANSI only when stdout is a real terminal
and NO_COLOR is unset, so piped output (agents, CI, grep) stays plain."""
from __future__ import annotations

import os
import sys

CODES = {
    "green": "32;1", "red": "31;1", "yellow": "33", "cyan": "36",
    "magenta": "35;1", "bold": "1", "dim": "2", "gold": "93;1",
}


def color_on() -> bool:
    return sys.stdout.isatty() and not os.environ.get("NO_COLOR")


def paint(text: str, style: str) -> str:
    if not color_on():
        return text
    return f"\033[{CODES[style]}m{text}\033[0m"
