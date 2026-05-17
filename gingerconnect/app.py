from __future__ import annotations
import sys
from pathlib import Path
from typing import List

from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication

from gingerconnect.theme import STYLESHEET
from gingerconnect.main_window import MainWindow

# Resolve the icon relative to the project root (one level above this package)
_ICON_PATH = Path(__file__).parent.parent / "GingerConnect.png"


class GingerConnectApp(QApplication):
    def __init__(self, argv: List[str]) -> None:
        super().__init__(argv)
        self.setApplicationName("GingerConnect")
        self.setApplicationVersion("1.0.0")
        self.setDesktopFileName("gingerconnect")
        self.setStyleSheet(STYLESHEET)

        if _ICON_PATH.exists():
            icon = QIcon(str(_ICON_PATH))
            self.setWindowIcon(icon)

        self._window = MainWindow()
        if _ICON_PATH.exists():
            self._window.setWindowIcon(QIcon(str(_ICON_PATH)))
        self._window.show()


def main() -> None:
    import sys
    app = GingerConnectApp(sys.argv)
    sys.exit(app.exec())
