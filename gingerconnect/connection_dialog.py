from __future__ import annotations
from typing import Optional

from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
    QGroupBox, QLabel, QLineEdit, QVBoxLayout, QWidget,
)
from PyQt6.QtCore import Qt

from gingerconnect.models.connection import Connection, SIA, Target


class ConnectionDialog(QDialog):
    def __init__(
        self,
        parent: Optional[QWidget] = None,
        connection: Optional[Connection] = None,
        default_group: Optional[str] = None,
    ) -> None:
        super().__init__(parent)
        self._editing = connection is not None
        self.setWindowTitle("Edit Connection" if self._editing else "Add Connection")
        self.setMinimumWidth(420)
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # ── Basic ──────────────────────────────────────────────────────────
        basic_box = QGroupBox("Connection")
        form = QFormLayout(basic_box)
        form.setSpacing(8)

        self._name = QLineEdit()
        self._name.setPlaceholderText("My Server")
        form.addRow("Name", self._name)

        self._group = QLineEdit()
        self._group.setPlaceholderText("Default  (use / for nesting, e.g. CSSE/RDP)")
        form.addRow("Group", self._group)

        self._protocol = QComboBox()
        self._protocol.addItems(["rdp", "ssh"])
        form.addRow("Protocol", self._protocol)

        self._mode = QComboBox()
        self._mode.addItems(["direct", "sia"])
        form.addRow("Mode", self._mode)

        layout.addWidget(basic_box)

        # ── Target ────────────────────────────────────────────────────────
        self._target_box = QGroupBox("Target")
        tform = QFormLayout(self._target_box)
        tform.setSpacing(8)

        self._host = QLineEdit()
        self._host.setPlaceholderText("hostname or IP")
        tform.addRow("Host", self._host)

        self._username = QLineEdit()
        self._username.setPlaceholderText("(optional for ZSP)")
        self._username_label = QLabel("Username")
        tform.addRow(self._username_label, self._username)

        self._domain_label = QLabel("Domain")
        self._domain = QLineEdit()
        self._domain.setPlaceholderText("(optional)")
        tform.addRow(self._domain_label, self._domain)

        self._network_label = QLabel("Network")
        self._network = QLineEdit()
        self._network.setPlaceholderText("(optional)")
        tform.addRow(self._network_label, self._network)

        layout.addWidget(self._target_box)

        # ── SIA ───────────────────────────────────────────────────────────
        self._sia_box = QGroupBox("CyberArk SIA")
        sform = QFormLayout(self._sia_box)
        sform.setSpacing(8)

        self._subdomain = QLineEdit()
        sform.addRow("Subdomain", self._subdomain)

        self._identity = QLineEdit()
        self._identity.setPlaceholderText("user@example.cloud")
        sform.addRow("Identity", self._identity)

        layout.addWidget(self._sia_box)

        # ── Buttons ───────────────────────────────────────────────────────
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        ok_btn = buttons.button(QDialogButtonBox.StandardButton.Ok)
        assert ok_btn is not None
        ok_btn.setObjectName("AccentButton")
        ok_btn.setText("Save")
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        # Signals
        self._protocol.currentTextChanged.connect(self._update_visibility)
        self._mode.currentTextChanged.connect(self._update_visibility)

        # Populate if editing, or pre-fill group when adding inside a group
        if connection:
            self._populate(connection)
        elif default_group:
            self._group.setText(default_group)

        self._update_visibility()

    # ── helpers ────────────────────────────────────────────────────────────

    def _populate(self, c: Connection) -> None:
        self._name.setText(c.name)
        self._group.setText(c.group)
        idx = self._protocol.findText(c.protocol)
        if idx >= 0:
            self._protocol.setCurrentIndex(idx)
        idx = self._mode.findText(c.mode)
        if idx >= 0:
            self._mode.setCurrentIndex(idx)
        self._host.setText(c.target.host)
        self._username.setText(c.target.username)
        self._domain.setText(c.target.domain)
        self._network.setText(c.target.network)
        self._subdomain.setText(c.sia.subdomain)
        self._identity.setText(c.sia.identity)

    def _update_visibility(self) -> None:
        proto = self._protocol.currentText()
        mode = self._mode.currentText()
        is_rdp = proto == "rdp"
        is_sia = mode == "sia"

        # Username: always visible; placeholder indicates it's optional for SIA (ZSP)
        self._username.setPlaceholderText(
            "(optional for ZSP)" if is_sia else ""
        )

        # Domain: RDP only
        self._domain_label.setVisible(is_rdp)
        self._domain.setVisible(is_rdp)

        # Network: SSH + SIA only
        is_ssh_sia = not is_rdp and is_sia
        self._network_label.setVisible(is_ssh_sia)
        self._network.setVisible(is_ssh_sia)

        # SIA box
        self._sia_box.setVisible(is_sia)

    def _accept(self) -> None:
        if not self._name.text().strip():
            self._name.setFocus()
            return
        if not self._host.text().strip():
            self._host.setFocus()
            return
        self.accept()

    # ── result ─────────────────────────────────────────────────────────────

    def get_connection(self) -> Connection:
        return Connection(
            name=self._name.text().strip(),
            group=self._group.text().strip() or "Default",
            protocol=self._protocol.currentText(),
            mode=self._mode.currentText(),
            target=Target(
                host=self._host.text().strip(),
                username=self._username.text().strip(),
                domain=self._domain.text().strip(),
                network=self._network.text().strip(),
            ),
            sia=SIA(
                subdomain=self._subdomain.text().strip(),
                identity=self._identity.text().strip(),
            ),
        )
