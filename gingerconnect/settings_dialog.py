from __future__ import annotations
from typing import Optional

from PyQt6.QtWidgets import (
    QDialog, QDialogButtonBox, QFormLayout, QGroupBox,
    QLineEdit, QVBoxLayout, QWidget,
)

from gingerconnect.managers.connection_manager import ConnectionManager


class SettingsDialog(QDialog):
    def __init__(self, manager: ConnectionManager, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._manager = manager
        self.setWindowTitle("Settings")
        self.setMinimumWidth(380)
        self.setModal(True)

        layout = QVBoxLayout(self)

        box = QGroupBox("CyberArk Gateway")
        form = QFormLayout(box)
        form.setSpacing(8)

        settings = manager.settings
        self._gw_user = QLineEdit(settings.get("gateway_username", ""))
        form.addRow("Username", self._gw_user)

        self._gw_pass = QLineEdit(settings.get("gateway_password", ""))
        self._gw_pass.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow("Password", self._gw_pass)

        layout.addWidget(box)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        ok_btn = buttons.button(QDialogButtonBox.StandardButton.Ok)
        assert ok_btn is not None
        ok_btn.setObjectName("AccentButton")
        ok_btn.setText("Save")
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _save(self) -> None:
        self._manager.update_settings({
            "gateway_username": self._gw_user.text().strip(),
            "gateway_password": self._gw_pass.text(),
        })
        self.accept()
