"""
IPMI Launcher — drag-drop JNLP launcher for BMC KVM consoles.

Parses a .jnlp file, downloads the required JARs (with pack200 support),
extracts native DLLs, and launches the viewer through the bundled Java 7
runtime.  Bypasses Java Web Start entirely.

Supports: AMI/Supermicro JViewer, ATEN iKVM, and other JNLP-based BMC KVMs.
"""
from __future__ import annotations

import base64
import ctypes
import ctypes.wintypes
import gzip
import http.cookiejar
import json
import re
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import asdict, dataclass, field, fields, replace
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QDesktopServices
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox,
    QFileDialog, QFormLayout, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QMainWindow, QMenu, QMessageBox, QPlainTextEdit, QPushButton,
    QStatusBar, QToolBar, QToolButton, QVBoxLayout, QWidget,
)


# --- Paths -------------------------------------------------------------------

def app_dir() -> Path:
    """Folder containing the app — next to .exe in bundled mode, alongside main.py in dev."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent

APP_DIR = app_dir()
JAVA_HOME = APP_DIR / "jre7"
WORKING_DIR = APP_DIR / "working"
SETTINGS_FILE = APP_DIR / "settings.json"

STATE_IDLE = "idle"
STATE_STAGED = "staged"
STATE_LAUNCHING = "launching"
STATE_RUNNING = "running"
STATE_ERROR = "error"


# --- Settings ----------------------------------------------------------------

@dataclass
class Settings:
    working_folder_override: str = ""
    wipe_jar_cache_on_launch: bool = False
    recent_files: list = field(default_factory=list)   # list of path strings, newest first
    profiles: list = field(default_factory=list)        # list of profile dicts


def load_settings() -> Settings:
    if not SETTINGS_FILE.exists():
        return Settings()
    try:
        data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return Settings()
    valid = {f.name for f in fields(Settings)}
    return Settings(**{k: v for k, v in data.items() if k in valid})


def save_settings(settings: Settings) -> None:
    SETTINGS_FILE.write_text(
        json.dumps(asdict(settings), indent=2),
        encoding="utf-8",
    )


# --- Stylesheet --------------------------------------------------------------

STYLESHEET = """
QMainWindow, QWidget, QDialog {
    background-color: #0c0820;
    color: #e9e4ff;
    font-family: "Segoe UI", system-ui, sans-serif;
    font-size: 10pt;
}

QLabel { color: #e9e4ff; }
QLabel#SectionLabel {
    color: #a594d1;
    font-size: 9pt;
    font-weight: 600;
    letter-spacing: 1px;
}
QLabel#ValueLabel {
    color: #e9e4ff;
    font-size: 11pt;
    font-weight: 500;
}
QLabel#MutedLabel { color: #8b7dc7; }

QPushButton {
    background-color: #1f1244;
    color: #d4c5ff;
    border: 1px solid #3a2068;
    padding: 8px 16px;
    border-radius: 4px;
    font-weight: 500;
}
QPushButton:hover {
    background-color: #2a1860;
    border-color: #a855f7;
    color: #f3edff;
}
QPushButton:pressed { background-color: #14082b; }
QPushButton:disabled {
    background-color: #14082b;
    color: #5a4d80;
    border-color: #251743;
}
QPushButton#IconButton {
    padding: 8px 4px;
    font-size: 14pt;
    min-width: 32px;
}
QPushButton#PrimaryButton {
    background-color: #7c3aed;
    color: #fff;
    border: 1px solid #a855f7;
    padding: 10px 22px;
    font-weight: 600;
}
QPushButton#PrimaryButton:hover {
    background-color: #a855f7;
    border-color: #d946ef;
}
QPushButton#PrimaryButton:disabled {
    background-color: #2a1860;
    color: #6d5fa3;
    border-color: #2a1860;
}

QPlainTextEdit {
    background-color: #07041a;
    color: #00ff9f;
    border: 1px solid #3a2068;
    border-radius: 4px;
    padding: 8px;
    font-family: "Cascadia Code", "Consolas", monospace;
    font-size: 9pt;
    selection-background-color: #6d28d9;
    selection-color: #fff;
}

QLineEdit {
    background-color: #1f1244;
    color: #e9e4ff;
    border: 1px solid #3a2068;
    border-radius: 4px;
    padding: 6px 8px;
}
QLineEdit:focus { border-color: #a855f7; }
QLineEdit:disabled { color: #6d5fa3; }

QCheckBox {
    color: #e9e4ff;
    spacing: 8px;
}
QCheckBox::indicator {
    width: 16px;
    height: 16px;
    background-color: #1f1244;
    border: 1px solid #3a2068;
    border-radius: 3px;
}
QCheckBox::indicator:hover { border-color: #a855f7; }
QCheckBox::indicator:checked {
    background-color: #a855f7;
    border-color: #a855f7;
}

QComboBox {
    background-color: #1f1244;
    color: #e9e4ff;
    border: 1px solid #3a2068;
    border-radius: 4px;
    padding: 4px 8px;
    min-width: 120px;
}
QComboBox:hover { border-color: #a855f7; }
QComboBox:disabled { color: #5a4d80; }
QComboBox::drop-down { border: none; width: 18px; }
QComboBox QAbstractItemView {
    background-color: #1f1244;
    color: #e9e4ff;
    border: 1px solid #3a2068;
    selection-background-color: #6d28d9;
    selection-color: #fff;
    outline: none;
}

QMenu {
    background-color: #1f1244;
    color: #e9e4ff;
    border: 1px solid #3a2068;
    padding: 4px 0;
}
QMenu::item { padding: 6px 20px; }
QMenu::item:selected { background-color: #6d28d9; color: #fff; }
QMenu::item:disabled { color: #5a4d80; }
QMenu::separator { height: 1px; background: #3a2068; margin: 3px 0; }

QFrame#DropZone {
    background-color: #14092e;
    border: 2px dashed #6d28d9;
    border-radius: 8px;
    min-height: 130px;
}
QFrame#DropZone[active="true"] {
    border-color: #d946ef;
    background-color: #1f1244;
}

QToolBar {
    background-color: #14092e;
    border: 0;
    border-bottom: 1px solid #3a2068;
    padding: 4px;
    spacing: 4px;
}
QToolBar QToolButton {
    background-color: transparent;
    color: #d4c5ff;
    padding: 6px 14px;
    border-radius: 4px;
}
QToolBar QToolButton:hover {
    background-color: #2a1860;
    color: #f3edff;
}
QToolBar QToolButton:disabled { color: #5a4d80; }

QStatusBar {
    background-color: #07041a;
    color: #a594d1;
    border-top: 1px solid #3a2068;
}
"""


# --- Custom widgets ----------------------------------------------------------

class DropZone(QFrame):
    """Visual drop area for the JNLP file."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("DropZone")
        self.setProperty("active", "false")

        title = QLabel("Drop a .jnlp file here", self)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet("font-size: 14pt; font-weight: 600; color: #e9d4ff; letter-spacing: 1px;")

        hint = QLabel("or click below to browse", self)
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setObjectName("MutedLabel")

        browse_btn = QPushButton("Browse files...", self)
        browse_btn.setFixedWidth(160)
        browse_btn.clicked.connect(self._on_browse)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.addStretch(1)
        layout.addWidget(title)
        layout.addWidget(hint)
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(browse_btn)
        row.addStretch()
        layout.addSpacing(4)
        layout.addLayout(row)
        layout.addStretch(1)

    def set_active(self, active):
        self.setProperty("active", "true" if active else "false")
        self.style().unpolish(self)
        self.style().polish(self)

    def _on_browse(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select a JNLP file", "",
            "JNLP files (*.jnlp);;All files (*.*)",
        )
        if path:
            window = self.window()
            if hasattr(window, "stage_file"):
                window.stage_file(Path(path))


class StatusDot(QLabel):
    """Colored dot showing app state."""

    COLORS = {
        STATE_IDLE: "#6d5fa3",
        STATE_STAGED: "#a855f7",
        STATE_LAUNCHING: "#d946ef",
        STATE_RUNNING: "#00ff9f",
        STATE_ERROR: "#f43f5e",
    }

    def __init__(self, parent=None):
        super().__init__("●", parent)
        self.set_state(STATE_IDLE)

    def set_state(self, state):
        color = self.COLORS.get(state, "#6d5fa3")
        self.setStyleSheet(f"font-size: 14pt; color: {color}; padding: 0 6px 0 8px;")


class InfoPanel(QFrame):
    """Shows the parsed JNLP details."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._labels = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        for key, title in [
            ("file", "File"),
            ("host", "Connection"),
            ("token", "Session token"),
        ]:
            section = QLabel(title)
            section.setObjectName("SectionLabel")
            value = QLabel("—")
            value.setObjectName("ValueLabel")
            self._labels[key] = value
            layout.addWidget(section)
            layout.addWidget(value)
            layout.addSpacing(6)

    def set_info(self, file_name, host, token):
        self._labels["file"].setText(file_name or "—")
        self._labels["host"].setText(host or "—")
        if token:
            short = f"{token[:10]}..." if len(token) > 12 else token
            self._labels["token"].setText(short)
        else:
            self._labels["token"].setText("—")

    def clear(self):
        for label in self._labels.values():
            label.setText("—")


# --- Dialogs -----------------------------------------------------------------

class SettingsDialog(QDialog):
    def __init__(self, settings: Settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumWidth(560)
        self._original = settings

        self.working_edit = QLineEdit(settings.working_folder_override, self)
        self.working_edit.setPlaceholderText("(leave blank to use default)")

        browse_btn = QPushButton("Browse...", self)
        browse_btn.setFixedWidth(100)
        browse_btn.clicked.connect(self._browse_working)

        working_row = QHBoxLayout()
        working_row.addWidget(self.working_edit, 1)
        working_row.addWidget(browse_btn)
        working_wrap = QWidget(self)
        working_wrap.setLayout(working_row)

        self.wipe_check = QCheckBox(
            "Wipe downloaded JARs before each launch", self
        )
        self.wipe_check.setChecked(settings.wipe_jar_cache_on_launch)

        wipe_hint = QLabel(
            "Forces fresh download every launch. Useful if your BMC firmware updates the JARs.",
            self,
        )
        wipe_hint.setObjectName("MutedLabel")
        wipe_hint.setWordWrap(True)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.addRow("Working folder:", working_wrap)
        form.addRow("", self.wipe_check)
        form.addRow("", wipe_hint)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        intro = QLabel(f"Settings saved to {SETTINGS_FILE.name}", self)
        intro.setObjectName("MutedLabel")
        layout.addWidget(intro)
        layout.addSpacing(10)
        layout.addLayout(form)
        layout.addStretch()
        layout.addWidget(buttons)

    def _browse_working(self):
        start = self.working_edit.text() or str(WORKING_DIR)
        chosen = QFileDialog.getExistingDirectory(self, "Choose working folder", start)
        if chosen:
            self.working_edit.setText(chosen)

    def updated_settings(self) -> Settings:
        return replace(
            self._original,
            working_folder_override=self.working_edit.text().strip(),
            wipe_jar_cache_on_launch=self.wipe_check.isChecked(),
        )


class ProfileDialog(QDialog):
    """Add or edit a BMC profile."""

    BMC_TYPES = ["ATEN", "AMI / Supermicro"]

    def __init__(self, profile: dict | None = None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add Profile" if profile is None else "Edit Profile")
        self.setMinimumWidth(480)

        self.name_edit = QLineEdit(profile.get("name", "") if profile else "", self)
        self.name_edit.setPlaceholderText('e.g. "Server Room Rack 3"')

        self.type_combo = QComboBox(self)
        self.type_combo.addItems(self.BMC_TYPES)
        if profile:
            label = "ATEN" if profile.get("bmc_type") == "aten" else "AMI / Supermicro"
            self.type_combo.setCurrentText(label)

        self.host_edit = QLineEdit(profile.get("hostname", "") if profile else "", self)
        self.host_edit.setPlaceholderText("192.168.1.100")

        self.user_edit = QLineEdit(profile.get("username", "") if profile else "", self)
        self.user_edit.setPlaceholderText("admin")

        self.pass_edit = QLineEdit(profile.get("password", "") if profile else "", self)
        self.pass_edit.setEchoMode(QLineEdit.EchoMode.Password)

        show_pass = QCheckBox("Show password", self)
        show_pass.toggled.connect(
            lambda on: self.pass_edit.setEchoMode(
                QLineEdit.EchoMode.Normal if on else QLineEdit.EchoMode.Password
            )
        )

        hint = QLabel(
            "Password is encrypted with Windows DPAPI — only the current user "
            "on this machine can decrypt it.",
            self,
        )
        hint.setObjectName("MutedLabel")
        hint.setWordWrap(True)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        form.addRow("Name:", self.name_edit)
        form.addRow("BMC type:", self.type_combo)
        form.addRow("Hostname / IP:", self.host_edit)
        form.addRow("Username:", self.user_edit)
        form.addRow("Password:", self.pass_edit)
        form.addRow("", show_pass)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addSpacing(6)
        layout.addWidget(hint)
        layout.addSpacing(4)
        layout.addWidget(buttons)

    def get_profile(self) -> dict:
        bmc_type = "aten" if self.type_combo.currentIndex() == 0 else "ami"
        return {
            "id": str(time.time()),
            "name": self.name_edit.text().strip(),
            "bmc_type": bmc_type,
            "hostname": self.host_edit.text().strip(),
            "username": self.user_edit.text().strip(),
            "password": self.pass_edit.text(),
        }


# --- Main window -------------------------------------------------------------

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("IPMI Launcher")
        self.resize(680, 760)
        self.setAcceptDrops(True)

        # state
        self.staged_jnlp = None
        self.parsed_info = None
        self.java_proc = None
        self.settings = load_settings()

        # --- toolbar ---
        toolbar = QToolBar(self)
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        settings_action = QAction("Settings", self)
        settings_action.triggered.connect(self.open_settings)
        toolbar.addAction(settings_action)

        open_folder_action = QAction("Open working folder", self)
        open_folder_action.triggered.connect(self.open_working_folder)
        toolbar.addAction(open_folder_action)

        toolbar.addSeparator()

        # Recent files dropdown
        self.recent_btn = QToolButton(toolbar)
        self.recent_btn.setText("Recent ▾")
        self.recent_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self.recent_menu = QMenu(self.recent_btn)
        self.recent_btn.setMenu(self.recent_menu)
        toolbar.addWidget(self.recent_btn)

        # --- central widget ---
        central = QWidget(self)
        self.setCentralWidget(central)

        self.drop_zone = DropZone(central)
        self.info_panel = InfoPanel(central)

        # Profile row (lives in the main layout, never hidden by toolbar overflow)
        self.profile_combo = QComboBox(central)
        self.profile_combo.setMinimumWidth(180)
        self.profile_combo.currentIndexChanged.connect(self._on_profile_changed)

        add_profile_btn = QPushButton("+", central)
        add_profile_btn.setObjectName("IconButton")
        add_profile_btn.setFixedWidth(32)
        add_profile_btn.setToolTip("Add BMC profile")
        add_profile_btn.clicked.connect(self.add_profile)

        self.manage_profile_btn = QPushButton("⋮", central)
        self.manage_profile_btn.setObjectName("IconButton")
        self.manage_profile_btn.setFixedWidth(32)
        self.manage_profile_btn.setToolTip("Edit or delete selected profile")
        self.manage_profile_btn.setEnabled(False)
        self._manage_menu = QMenu(self.manage_profile_btn)
        self._edit_profile_action = self._manage_menu.addAction("Edit profile")
        self._edit_profile_action.triggered.connect(self.edit_profile)
        self._manage_menu.addSeparator()
        self._delete_profile_action = self._manage_menu.addAction("Delete profile")
        self._delete_profile_action.triggered.connect(self.delete_profile)
        self.manage_profile_btn.clicked.connect(self._show_manage_menu)

        self.fetch_btn = QPushButton("Fetch JNLP", central)
        self.fetch_btn.setToolTip("Log into the selected BMC and download a fresh JNLP")
        self.fetch_btn.setEnabled(False)
        self.fetch_btn.clicked.connect(self.on_fetch_jnlp)

        profile_row = QHBoxLayout()
        profile_row.setSpacing(4)
        profile_row.addWidget(self.profile_combo, 1)
        profile_row.addWidget(add_profile_btn)
        profile_row.addWidget(self.manage_profile_btn)
        profile_row.addSpacing(8)
        profile_row.addWidget(self.fetch_btn)

        self.launch_button = QPushButton("Launch IPMI", central)
        self.launch_button.setObjectName("PrimaryButton")
        self.launch_button.clicked.connect(self.on_launch)

        self.clear_button = QPushButton("Clear", central)
        self.clear_button.clicked.connect(self.on_clear)

        log_label = QLabel("Log", central)
        log_label.setObjectName("SectionLabel")

        self.log_view = QPlainTextEdit(central)
        self.log_view.setReadOnly(True)
        self.log_view.setMinimumHeight(160)

        button_row = QHBoxLayout()
        button_row.addWidget(self.launch_button)
        button_row.addWidget(self.clear_button)
        button_row.addStretch()

        layout = QVBoxLayout(central)
        layout.setContentsMargins(20, 20, 20, 16)
        layout.setSpacing(14)
        layout.addWidget(self.drop_zone)
        layout.addLayout(profile_row)
        layout.addWidget(self.info_panel)
        layout.addLayout(button_row)
        layout.addSpacing(4)
        layout.addWidget(log_label)
        layout.addWidget(self.log_view, stretch=1)

        # --- status bar ---
        sb = QStatusBar(self)
        self.setStatusBar(sb)
        self._status_dot = StatusDot(sb)
        self._status_text = QLabel("Ready", sb)
        sb.addWidget(self._status_dot)
        sb.addWidget(self._status_text, 1)

        self.set_state(STATE_IDLE)
        self.refresh_ui()
        self._rebuild_recent_menu()
        self._rebuild_profile_combo()

    # --- properties ----------------------------------------------------------

    @property
    def working_dir(self) -> Path:
        if self.settings.working_folder_override:
            return Path(self.settings.working_folder_override)
        return WORKING_DIR

    # --- state ---------------------------------------------------------------

    def set_state(self, state):
        labels = {
            STATE_IDLE: "Ready — drop a JNLP file to begin",
            STATE_STAGED: "Ready to launch",
            STATE_LAUNCHING: "Preparing...",
            STATE_RUNNING: "KVM running",
            STATE_ERROR: "Error — see log",
        }
        self._status_dot.set_state(state)
        self._status_text.setText(labels.get(state, state))

    def refresh_ui(self):
        if self.staged_jnlp is None:
            self.info_panel.clear()
            self.launch_button.setEnabled(False)
            self.clear_button.setEnabled(False)
        else:
            info = self.parsed_info or {}
            self.info_panel.set_info(
                self.staged_jnlp.name,
                info.get("hostname"),
                info.get("token"),
            )
            self.launch_button.setEnabled(self.java_proc is None)
            self.clear_button.setEnabled(True)

    def log(self, message):
        ts = time.strftime("%H:%M:%S")
        line = f"[{ts}] {message}"
        print(line)
        self.log_view.appendPlainText(line)
        QApplication.processEvents()

    # --- recent files --------------------------------------------------------

    def _add_to_recent(self, path: Path):
        path_str = str(path.resolve())
        recent = list(self.settings.recent_files)
        if path_str in recent:
            recent.remove(path_str)
        recent.insert(0, path_str)
        self.settings.recent_files = recent[:5]
        save_settings(self.settings)
        self._rebuild_recent_menu()

    def _rebuild_recent_menu(self):
        self.recent_menu.clear()
        valid = [p for p in self.settings.recent_files if Path(p).exists()]
        if not valid:
            act = self.recent_menu.addAction("(no recent files)")
            act.setEnabled(False)
            return
        for path_str in valid:
            p = Path(path_str)
            act = self.recent_menu.addAction(p.name)
            act.setToolTip(path_str)
            act.triggered.connect(lambda checked=False, fp=p: self.stage_file(fp))

    # --- profiles ------------------------------------------------------------

    def _rebuild_profile_combo(self):
        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        self.profile_combo.addItem("— select profile —")
        for p in self.settings.profiles:
            self.profile_combo.addItem(p["name"])
        self.profile_combo.blockSignals(False)
        self._update_fetch_btn()

    def _on_profile_changed(self, _idx):
        self._update_fetch_btn()

    def _show_manage_menu(self):
        btn = self.manage_profile_btn
        self._manage_menu.exec(btn.mapToGlobal(btn.rect().bottomLeft()))

    def _update_fetch_btn(self):
        has_profile = self.profile_combo.currentIndex() > 0
        self.fetch_btn.setEnabled(has_profile)
        self.manage_profile_btn.setEnabled(has_profile)

    def add_profile(self):
        dlg = ProfileDialog(parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        profile = dlg.get_profile()
        if not profile["name"] or not profile["hostname"]:
            QMessageBox.warning(self, "Incomplete profile",
                                "A profile needs at least a name and a hostname.")
            return
        try:
            profile["password_enc"] = _encrypt_password(profile.pop("password", ""))
        except RuntimeError as e:
            QMessageBox.critical(self, "Encryption failed", str(e))
            return
        self.settings.profiles.append(profile)
        save_settings(self.settings)
        self._rebuild_profile_combo()
        self.profile_combo.setCurrentIndex(len(self.settings.profiles))
        self.log(f"Profile saved: {profile['name']}")

    def edit_profile(self):
        idx = self.profile_combo.currentIndex()
        if idx <= 0:
            return
        existing = self.settings.profiles[idx - 1]
        # Decrypt password so the edit dialog shows the current value.
        try:
            plaintext = _decrypt_password(existing.get("password_enc", ""))
        except RuntimeError:
            plaintext = ""
        editable = {**existing, "password": plaintext}
        dlg = ProfileDialog(profile=editable, parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        updated = dlg.get_profile()
        if not updated["name"] or not updated["hostname"]:
            QMessageBox.warning(self, "Incomplete profile",
                                "A profile needs at least a name and a hostname.")
            return
        try:
            updated["password_enc"] = _encrypt_password(updated.pop("password", ""))
        except RuntimeError as e:
            QMessageBox.critical(self, "Encryption failed", str(e))
            return
        updated["id"] = existing.get("id", updated["id"])
        self.settings.profiles[idx - 1] = updated
        save_settings(self.settings)
        self._rebuild_profile_combo()
        self.profile_combo.setCurrentIndex(idx)
        self.log(f"Profile updated: {updated['name']}")

    def delete_profile(self):
        idx = self.profile_combo.currentIndex()
        if idx <= 0:
            return
        profile = self.settings.profiles[idx - 1]
        answer = QMessageBox.question(
            self, "Delete profile",
            f"Delete profile \"{profile['name']}\"?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.settings.profiles.pop(idx - 1)
        save_settings(self.settings)
        self._rebuild_profile_combo()
        self.log(f"Profile deleted: {profile['name']}")

    def on_fetch_jnlp(self):
        idx = self.profile_combo.currentIndex()
        if idx <= 0:
            return
        profile = self.settings.profiles[idx - 1]
        self.fetch_btn.setEnabled(False)
        self.log(f"=== Fetching JNLP for: {profile['name']} ===")
        try:
            jnlp_path = fetch_jnlp_for_profile(profile, self.working_dir, log_fn=self.log)
            self.stage_file(jnlp_path, add_to_recent=False)
            # Delete immediately — the file may contain plaintext credentials in args.
            try:
                jnlp_path.unlink()
            except OSError:
                pass
        except Exception as e:
            self.log(f"ERROR: {e}")
            self.set_state(STATE_ERROR)
            QMessageBox.critical(self, "Fetch failed", str(e))
        finally:
            self._update_fetch_btn()

    # --- JNLP staging --------------------------------------------------------

    def stage_file(self, path: Path, add_to_recent: bool = True):
        if path.suffix.lower() != ".jnlp":
            QMessageBox.warning(self, "Wrong file type",
                                f"That doesn't look like a JNLP:\n{path}")
            return
        try:
            self.parsed_info = parse_jnlp(path)
        except Exception as e:
            self.log(f"ERROR parsing {path.name}: {e}")
            self.set_state(STATE_ERROR)
            QMessageBox.critical(self, "Parse error", f"Could not parse JNLP:\n{e}")
            return
        self.staged_jnlp = path
        self.log(f"Staged: {path.name}")
        self.set_state(STATE_STAGED)
        if add_to_recent:
            self._add_to_recent(path)
        self.refresh_ui()

    # --- launch --------------------------------------------------------------

    def on_launch(self):
        if self.staged_jnlp is None:
            return
        if self.java_proc is not None:
            QMessageBox.information(self, "Already running",
                                    "The KVM viewer is already running. Close it first.")
            return

        self.set_state(STATE_LAUNCHING)
        self.log(f"=== Launching from {self.staged_jnlp.name} ===")

        try:
            work = self.working_dir
            if self.settings.wipe_jar_cache_on_launch:
                self._wipe_cache(work)
            download_jars(self.parsed_info, work, log_fn=self.log)
            extract_natives(self.parsed_info, work, log_fn=self.log)
            self.java_proc = launch_java(self.parsed_info, work, log_fn=self.log)
        except Exception as e:
            self.log(f"FATAL: {e}")
            self.set_state(STATE_ERROR)
            return

        self.refresh_ui()
        self.set_state(STATE_RUNNING)
        QTimer.singleShot(2000, self.check_java_status)

    def _wipe_cache(self, work: Path):
        self.log("Wiping JAR cache (per settings)...")
        for jar in work.glob("*.jar"):
            try:
                jar.unlink()
            except OSError:
                pass
        natives = work / "natives"
        if natives.exists():
            for f in natives.glob("*"):
                try:
                    f.unlink()
                except OSError:
                    pass

    def on_clear(self):
        self.staged_jnlp = None
        self.parsed_info = None
        self.set_state(STATE_IDLE)
        self.refresh_ui()
        self.log("Cleared.")

    def check_java_status(self):
        proc = self.java_proc
        if proc is None:
            return
        result = proc.poll()
        if result is None:
            QTimer.singleShot(2000, self.check_java_status)
            return

        self.log(f"Java exited (code {result}).")
        try:
            stdout, stderr = proc.communicate(timeout=3)
        except subprocess.TimeoutExpired:
            stdout, stderr = "", "(communicate timed out)"
        if stdout and stdout.strip():
            self.log("--- stdout ---")
            self.log(stdout.strip())
        if stderr and stderr.strip():
            self.log("--- stderr ---")
            self.log(stderr.strip())

        self.java_proc = None
        self.staged_jnlp = None
        self.parsed_info = None

        if result == 0:
            self.set_state(STATE_IDLE)
            self.log("Session ended — drop a new JNLP to launch again.")
        else:
            self.set_state(STATE_ERROR)
            self.log("Session failed — drop a new JNLP to retry.")

        self.refresh_ui()

    # --- toolbar actions -----------------------------------------------------

    def open_settings(self):
        dlg = SettingsDialog(self.settings, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self.settings = dlg.updated_settings()
            save_settings(self.settings)
            self.log("Settings saved.")

    def open_working_folder(self):
        path = self.working_dir
        path.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.resolve())))

    # --- drag and drop -------------------------------------------------------

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls() and any(
            u.toLocalFile().lower().endswith(".jnlp") for u in event.mimeData().urls()
        ):
            self.drop_zone.set_active(True)
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event):
        self.drop_zone.set_active(False)

    def dropEvent(self, event):
        self.drop_zone.set_active(False)
        for url in event.mimeData().urls():
            local = url.toLocalFile()
            if local.lower().endswith(".jnlp"):
                self.stage_file(Path(local))
                event.acceptProposedAction()
                return
        event.ignore()


# --- Worker functions --------------------------------------------------------

def _make_ssl_context():
    """Permissive SSL context for BMCs with self-signed certs and legacy TLS."""
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        ctx.options |= ssl.OP_LEGACY_SERVER_CONNECT
    except AttributeError:
        pass
    ctx.set_ciphers("DEFAULT:@SECLEVEL=1")
    return ctx


def _encrypt_password(plaintext: str) -> str:
    """Encrypt a password with Windows DPAPI (current user only).

    The result is a base64 string safe to store in settings.json.
    Only the same Windows user on the same machine can decrypt it.
    """
    if not plaintext:
        return ""

    class _Blob(ctypes.Structure):
        _fields_ = [("cbData", ctypes.wintypes.DWORD),
                    ("pbData", ctypes.POINTER(ctypes.c_ubyte))]

    raw = plaintext.encode("utf-8")
    buf = (ctypes.c_ubyte * len(raw))(*raw)
    blob_in = _Blob(len(raw), buf)
    blob_out = _Blob()

    ok = ctypes.windll.crypt32.CryptProtectData(
        ctypes.byref(blob_in), None, None, None, None, 0,
        ctypes.byref(blob_out),
    )
    if not ok:
        raise RuntimeError(
            f"CryptProtectData failed (error {ctypes.GetLastError()})"
        )
    try:
        encrypted = bytes(blob_out.pbData[:blob_out.cbData])
    finally:
        ctypes.windll.kernel32.LocalFree(blob_out.pbData)
    return base64.b64encode(encrypted).decode("ascii")


def _decrypt_password(ciphertext: str) -> str:
    """Decrypt a DPAPI-encrypted password previously encrypted by _encrypt_password."""
    if not ciphertext:
        return ""

    class _Blob(ctypes.Structure):
        _fields_ = [("cbData", ctypes.wintypes.DWORD),
                    ("pbData", ctypes.POINTER(ctypes.c_ubyte))]

    raw = base64.b64decode(ciphertext)
    buf = (ctypes.c_ubyte * len(raw))(*raw)
    blob_in = _Blob(len(raw), buf)
    blob_out = _Blob()

    ok = ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(blob_in), None, None, None, None, 0,
        ctypes.byref(blob_out),
    )
    if not ok:
        raise RuntimeError(
            "Could not decrypt stored password — it was encrypted for a "
            "different Windows user or machine."
        )
    try:
        plaintext = bytes(blob_out.pbData[:blob_out.cbData])
    finally:
        ctypes.windll.kernel32.LocalFree(blob_out.pbData)
    return plaintext.decode("utf-8")


def _make_opener(ssl_ctx):
    """urllib opener that handles cookies and our permissive SSL context."""
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(
        urllib.request.HTTPSHandler(context=ssl_ctx),
        urllib.request.HTTPCookieProcessor(jar),
    )
    opener.addheaders = [("User-Agent", "Mozilla/5.0")]
    return opener


def parse_jnlp(path):
    """Parse a JNLP file and return a dict describing what to download and run.

    Handles both AMI/Supermicro style (flag-value argument pairs like
    -hostname x -kvmtoken y) and ATEN style (positional arguments).
    """
    tree = ET.parse(path)
    root = tree.getroot()

    codebase = root.get("codebase", "").rstrip("/")
    app_desc = root.find("application-desc")
    main_class = app_desc.get("main-class") if app_desc is not None else None
    arg_values = [a.text for a in root.findall("application-desc/argument")]

    # Build a dict from flag-style args (-flag value).
    arg_dict = {}
    i = 0
    while i < len(arg_values):
        v = arg_values[i]
        if (v.startswith("-")
                and i + 1 < len(arg_values)
                and not arg_values[i + 1].startswith("-")):
            arg_dict[v] = arg_values[i + 1]
            i += 2
        else:
            i += 1

    # Hostname: flag-style first, then first positional arg.
    hostname = (arg_dict.get("-hostname")
                or arg_dict.get("-host")
                or (arg_values[0] if arg_values and not arg_values[0].startswith("-") else None))

    # Session token: flag-style first, then second positional arg.
    token = (arg_dict.get("-webcookie")
             or arg_dict.get("-kvmtoken")
             or arg_dict.get("-token")
             or arg_dict.get("-webessid")
             or arg_dict.get("-u")        # AMI standalone: username doubles as identity
             or (arg_values[1] if len(arg_values) > 1 and not arg_values[1].startswith("-") else None))

    jar_hrefs = []
    native_hrefs = []
    for resources in root.findall("resources"):
        os_attr = resources.get("os")
        arch_attr = resources.get("arch")
        if os_attr is None or (
            os_attr.lower() == "windows" and arch_attr in ("amd64", "x86_64", "x64")
        ):
            for jar in resources.findall("jar"):
                href = jar.get("href")
                if href:
                    jar_hrefs.append(href)
            for native in resources.findall("nativelib"):
                href = native.get("href")
                if href:
                    native_hrefs.append(href)

    return {
        "codebase": codebase,
        "hostname": hostname,
        "token": token,
        "jars": jar_hrefs,
        "native_jars": native_hrefs,
        "raw_args": arg_values,
        "main_class": main_class,
    }


def download_jars(info, dest_folder, log_fn=print):
    """Download all JARs declared in the JNLP.

    Tries .jar.pack.gz first (ATEN/pack200 servers), falls back to plain .jar
    (AMI/Supermicro).  Uses a permissive SSL context for self-signed certs.
    """
    dest_folder.mkdir(parents=True, exist_ok=True)
    codebase = info["codebase"]
    ssl_ctx = _make_ssl_context()
    unpack200 = JAVA_HOME / "jre" / "bin" / "unpack200.exe"
    all_hrefs = info.get("jars", []) + info.get("native_jars", [])

    for href in all_hrefs:
        filename = href.split("/")[-1]
        target = dest_folder / filename
        if target.exists():
            log_fn(f"Cached:      {filename}")
            continue

        pack_url = f"{codebase}/{href}.pack.gz"
        pack_tmp = dest_folder / (filename + ".pack.gz")

        try:
            log_fn(f"Downloading: {filename} (trying pack200)...")
            req = urllib.request.Request(pack_url)
            with urllib.request.urlopen(req, context=ssl_ctx, timeout=30) as resp:
                with pack_tmp.open("wb") as f:
                    while True:
                        chunk = resp.read(65536)
                        if not chunk:
                            break
                        f.write(chunk)
            log_fn(f"  Unpacking {pack_tmp.stat().st_size / 1024:.1f} KB...")
            result = subprocess.run(
                [str(unpack200), str(pack_tmp), str(target)],
                capture_output=True, text=True,
            )
            pack_tmp.unlink()
            if result.returncode != 0:
                raise RuntimeError(f"unpack200 failed: {result.stderr.strip()}")
            log_fn(f"  Unpacked to {target.stat().st_size / 1024:.1f} KB")
            continue

        except urllib.error.HTTPError as e:
            if e.code != 404:
                raise
            log_fn(f"  No pack200, trying plain JAR...")
            if pack_tmp.exists():
                pack_tmp.unlink()
        except Exception as e:
            log_fn(f"  pack200 failed ({e}), trying plain JAR...")
            if pack_tmp.exists():
                pack_tmp.unlink()

        plain_url = f"{codebase}/{href}"
        log_fn(f"Downloading: {filename}...")
        req = urllib.request.Request(plain_url)
        with urllib.request.urlopen(req, context=ssl_ctx, timeout=30) as resp:
            with target.open("wb") as f:
                while True:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    f.write(chunk)
        log_fn(f"  Saved {target.stat().st_size / 1024:.1f} KB")


def extract_natives(info, working_folder, log_fn=print):
    """Extract .dll files from native lib JARs into working_folder/natives/."""
    natives_dir = working_folder / "natives"
    natives_dir.mkdir(exist_ok=True)

    native_hrefs = info.get("native_jars", [])
    if not native_hrefs:
        log_fn("No native libs declared in JNLP; skipping DLL extraction.")
        return

    for href in native_hrefs:
        filename = href.split("/")[-1]
        native_jar = working_folder / filename
        if not native_jar.exists():
            log_fn(f"WARNING: {filename} not found — skipping native extraction.")
            continue
        with zipfile.ZipFile(native_jar, "r") as z:
            for name in z.namelist():
                if not name.endswith(".dll"):
                    continue
                target = natives_dir / Path(name).name
                if target.exists():
                    log_fn(f"Cached native:     {Path(name).name}")
                    continue
                log_fn(f"Extracting native: {Path(name).name}")
                with z.open(name) as src, target.open("wb") as dst:
                    dst.write(src.read())


def launch_java(info, working_folder, log_fn=print):
    """Launch the KVM viewer via the bundled java.exe."""
    java = JAVA_HOME / "jre" / "bin" / "java.exe"
    if not java.exists():
        raise FileNotFoundError(
            f"java.exe not found at {java}. Make sure jre7/ is in place."
        )

    natives_dir = working_folder.resolve() / "natives"
    main_class = info.get("main_class") or "com.ami.kvm.jviewer.JViewer"

    jar_names = [href.split("/")[-1] for href in info.get("jars", [])]
    classpath = ";".join(jar_names) if jar_names else "JViewer.jar"

    cmd = [
        str(java),
        f"-Djava.library.path={natives_dir}",
        "-Dsun.java2d.noddraw=true",
        "-Dsun.java2d.d3d=false",
        "-Xms32m",
        "-Xmx128m",
        "-cp", classpath,
        main_class,
        *info["raw_args"],
    ]
    log_fn(f"Launching: {main_class}")
    log_fn(f"Classpath: {classpath}")
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=str(working_folder.resolve()),
    )
    return proc


# --- Auto-fetch JNLP ---------------------------------------------------------

def fetch_jnlp_for_profile(profile: dict, dest_folder: Path, log_fn=print) -> Path:
    """Log into a BMC and download a fresh JNLP file."""
    bmc_type = profile.get("bmc_type", "aten")
    ssl_ctx = _make_ssl_context()
    opener = _make_opener(ssl_ctx)
    hostname = profile["hostname"].strip()
    base = f"https://{hostname}"

    try:
        password = _decrypt_password(profile.get("password_enc", ""))
    except RuntimeError as e:
        raise RuntimeError(f"Cannot use profile — {e}")

    if bmc_type == "aten":
        return _fetch_aten(opener, base, profile, password, dest_folder, log_fn)
    else:
        # AMI BMCs are sometimes HTTP-only; try HTTPS then fall back.
        try:
            return _fetch_ami(opener, base, profile, password, dest_folder, log_fn)
        except Exception as https_err:
            log_fn(f"  HTTPS failed ({https_err}), retrying over HTTP...")
            opener2 = _make_opener(ssl_ctx)
            return _fetch_ami(opener2, f"http://{hostname}", profile, password, dest_folder, log_fn)


def _decompress_if_needed(data: bytes) -> bytes:
    """Decompress gzip-encoded response bodies (some BMCs compress unconditionally)."""
    if data[:2] == b'\x1f\x8b':
        return gzip.decompress(data)
    return data


def _post_login(opener, url: str, fields: dict) -> bytes:
    data = urllib.parse.urlencode(fields).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        return _decompress_if_needed(opener.open(req, timeout=15).read())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Login POST returned HTTP {e.code}")
    except OSError as e:
        raise RuntimeError(f"Could not connect: {e}")


def _get_jnlp_bytes(opener, url: str, log_fn=None) -> bytes:
    try:
        content = _decompress_if_needed(opener.open(url, timeout=15).read())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code}")
    except OSError as e:
        raise RuntimeError(f"Could not fetch: {e}")
    if b"<jnlp" not in content[:1024]:
        preview = content[:300].decode("utf-8", errors="replace").replace("\n", " ").strip()
        if log_fn:
            log_fn(f"    Response preview: {preview}")
        raise RuntimeError("Not a JNLP file")
    return content


def _save_jnlp(content: bytes, dest_folder: Path, log_fn) -> Path:
    dest_folder.mkdir(parents=True, exist_ok=True)
    out = dest_folder / "fetched.jnlp"
    out.write_bytes(content)
    log_fn(f"  Saved {out.name} ({len(content)} bytes)")
    return out


def _fetch_aten(opener, base: str, profile: dict, password: str,
                dest_folder: Path, log_fn) -> Path:
    log_fn(f"  Connecting to {base}...")

    # ATEN uses IP-based sessions — no cookies. Send browser-like headers so
    # the old CGI doesn't crash on the request environment.
    opener.addheaders = [
        ("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/120.0.0.0 Safari/537.36"),
        ("Accept", "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"),
        ("Accept-Language", "en-US,en;q=0.9"),
        ("Referer", base + "/"),
        ("Origin", base),
    ]

    login_url = f"{base}/cgi/login.cgi"
    qs = urllib.parse.urlencode({"name": profile["username"], "pwd": password})
    req = urllib.request.Request(login_url, data=qs.encode(), method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        resp_bytes = _decompress_if_needed(opener.open(req, timeout=15).read())
    except urllib.error.HTTPError as e:
        body = _decompress_if_needed(e.read()).decode("utf-8", errors="replace")
        raise RuntimeError(f"Login failed HTTP {e.code}: {body[:200]}")

    log_fn("  Logged in, fetching JNLP...")
    content = _get_jnlp_bytes(
        opener,
        f"{base}/cgi/url_redirect.cgi?url_name=ikvm&url_type=jwsk",
        log_fn=log_fn,
    )
    return _save_jnlp(content, dest_folder, log_fn)


def _get_cookie_jar(opener):
    for h in opener.handlers:
        if isinstance(h, urllib.request.HTTPCookieProcessor):
            return h.cookiejar
    return None


def _inject_cookie(opener, host: str, name: str, value: str) -> None:
    """Manually add a cookie to the opener's jar (for JS-set cookies the server won't send)."""
    jar = _get_cookie_jar(opener)
    if jar is None:
        return
    c = http.cookiejar.Cookie(
        version=0, name=name, value=value,
        port=None, port_specified=False,
        domain=host, domain_specified=True, domain_initial_dot=False,
        path="/", path_specified=True,
        secure=False, expires=None, discard=True,
        comment=None, comment_url=None, rest={},
    )
    jar.set_cookie(c)


def _ami_login(opener, base: str, username: str, password: str, log_fn) -> tuple:
    """Log into an AMI MegaRAC BMC.
    Returns (session_key, csrf_token) — either may be an empty string.
    """
    host = base.split("//", 1)[-1].split(":")[0]
    try:
        resp = _post_login(opener, f"{base}/rpc/WEBSES/create.asp", {
            "WEBVAR_USERNAME": username,
            "WEBVAR_PASSWORD": password,
        })
    except RuntimeError:
        resp = None

    if resp is not None:
        decoded = resp.decode("utf-8", errors="replace")

        session_key = ""
        csrf_token = ""
        try:
            data = json.loads(decoded)
            entries = data.get("WEBSES_ACTIVE_ENTRY", [])
            if entries:
                session_key = entries[0].get("SESSION_COOKIE", "")
                csrf_token = entries[0].get("CSRFTOKEN", "")
        except json.JSONDecodeError:
            m = re.search(r'SESSION_COOKIE["\']?\s*[=:]\s*["\']([^"\']{8,})["\']', decoded)
            if m:
                session_key = m.group(1)
            m2 = re.search(r'CSRFTOKEN["\']?\s*[=:]\s*["\']([^"\']{4,})["\']', decoded)
            if m2:
                csrf_token = m2.group(1)

        if session_key:
            log_fn(f"  Session key: {session_key[:8]}...  CSRF token: {csrf_token or '(none)'}")
            _inject_cookie(opener, host, "SessionCookie", session_key)
            if csrf_token:
                _inject_cookie(opener, host, "CSRFTOKEN", csrf_token)
            # AMI MegaRAC requires X-CSRFTOKEN header and a plausible Referer
            # on all authenticated RPC requests.
            opener.addheaders = [h for h in opener.addheaders
                                 if h[0] not in ("X-CSRFTOKEN", "Referer", "Origin")]
            if csrf_token:
                opener.addheaders.append(("X-CSRFTOKEN", csrf_token))
            opener.addheaders.append(("Referer", f"{base}/page/dashboard.html"))
            opener.addheaders.append(("Origin", base))
            return session_key, csrf_token

        log_fn("  create.asp succeeded but no session key in response.")
        return "", ""

    log_fn("  /rpc/WEBSES/create.asp not found; trying /cgi/login.cgi...")
    _post_login(opener, f"{base}/cgi/login.cgi", {"name": username, "pwd": password})
    log_fn("  Logged in via /cgi/login.cgi.")
    return "", ""


def _ami_session_setup(opener, base: str, session_key: str, profile: dict,
                       log_fn) -> None:
    """Complete the post-login AMI session setup so the JNLP is generated correctly.

    The browser's JavaScript normally sets several cookies after login (BMC_IP_ADDR,
    Username, etc.) and calls a few RPC endpoints.  Without BMC_IP_ADDR the server
    substitutes '(null)' into the JNLP codebase URL.
    """
    host = base.split("//", 1)[-1].split(":")[0]

    # Inject the client-side cookies AMI's JavaScript normally sets via document.cookie.
    for name, value in [
        ("BMC_IP_ADDR",   host),
        ("Username",      profile["username"]),
        ("Language",      "EN"),
        ("PNO",           "4"),
        ("Extendedpriv",  "259"),
    ]:
        _inject_cookie(opener, host, name, value)
    log_fn("  Session cookies injected (BMC_IP_ADDR, Username, Language, PNO, Extendedpriv).")

    # Mirror the browser's XHR sequence before it fetches jviewer.jnlp.
    # Each call is tried at both /rpc/WEBSES/ and /rpc/ paths.
    sn = f"WEBVAR_SERIALNUMBER={session_key}"
    rpc_calls = [
        f"getrole.asp?{sn}",
        f"getlanchannelinfo.asp?{sn}",
        f"getprojectcfg.asp?{sn}",
        f"validate.asp?{sn}",
        f"getfwinfo.asp?{sn}",
        f"getalllancfg.asp?{sn}",
    ]
    for call in rpc_calls:
        name = call.split("?")[0]
        for prefix in ["/rpc/WEBSES/", "/rpc/"]:
            try:
                resp_data = _decompress_if_needed(
                    opener.open(f"{base}{prefix}{call}", timeout=8).read()
                )
                preview = resp_data.decode("utf-8", errors="replace")
                if "SessionExpired" in preview or "session_expired" in preview:
                    log_fn(f"  Session setup: {name} session_expired at {prefix.rstrip('/')}")
                    continue  # try next prefix
                log_fn(f"  Session setup: {name} OK ({prefix.strip('/')})")
                break
            except Exception:
                pass


def _patch_ami_jnlp(content: bytes, hostname: str, session_key: str,
                    username: str, password: str, webport: str, log_fn) -> bytes:
    """Fix a broken AMI JNLP where the codebase shows (null) and the
    application-desc contains an 'Unable to find JNLP String' HTML error.

    AMI's server only populates the JNLP template when certain server-side
    session state is present.  When it's missing, it returns a 2177-byte stub.
    We detect that condition and rebuild a working application-desc ourselves.
    """
    text = content.decode("utf-8", errors="replace")
    broken_codebase = "(null)" in text
    broken_app_desc = "Unable to find JNLP String" in text

    if not (broken_codebase or broken_app_desc):
        return content

    log_fn("  JNLP stub detected — patching codebase and application-desc...")

    # Fix the codebase URL so JAR downloads resolve correctly.
    text = re.sub(
        r'codebase="https?://\(null\)[^"]*"',
        f'codebase="http://{hostname}/Java"',
        text,
    )

    # Build a valid application-desc with the argument format this JViewer version
    # expects: -apptype StandAlone -hostname <ip> -u <user> -p <pass> -webport <port> -lang EN
    args = [
        ("-apptype",  "StandAlone"),
        ("-hostname", hostname),
        ("-u",        username),
        ("-p",        password),
        ("-webport",  webport),
    ]
    arg_xml = "\n".join(
        f'        <argument>{k}</argument>\n        <argument>{v}</argument>'
        for k, v in args
    )
    new_app_desc = (
        f'<application-desc main-class="com.ami.kvm.jviewer.JViewer">\n'
        f'{arg_xml}\n'
        f'    </application-desc>'
    )

    # The stub JNLP omits </application-desc> and </jnlp> entirely.
    # Match from <application-desc to the end (greedy) and replace, appending
    # the missing closing </jnlp> so the document is well-formed.
    if re.search(r'</application-desc>', text):
        text = re.sub(
            r'<application-desc[^>]*>.*?</application-desc>',
            new_app_desc,
            text,
            flags=re.DOTALL,
        )
    else:
        text = re.sub(
            r'<application-desc[^>]*>.*',
            new_app_desc + '\n</jnlp>',
            text,
            flags=re.DOTALL,
        )
    log_fn(f"  Patched JNLP: hostname={hostname}, session={'yes' if session_key else 'no'}")
    return text.encode("utf-8")


def _fetch_ami(opener, base: str, profile: dict, password: str,
               dest_folder: Path, log_fn) -> Path:
    log_fn(f"  Connecting to {base}...")
    session_key, csrf_token = _ami_login(opener, base, profile["username"], password, log_fn)
    if session_key:
        _ami_session_setup(opener, base, session_key, profile, log_fn)
    log_fn("  Trying JNLP endpoints...")

    candidates = []
    if session_key:
        # Some AMI firmware variants accept credentials directly in the JNLP URL.
        user = urllib.parse.quote(profile["username"])
        candidates.append(
            f"/Java/jviewer.jnlp?WEBVAR_USERNAME={user}"
            f"&WEBVAR_PRIVILEGE=4&SessionCookie={session_key}"
        )
        candidates.append(f"/Java/jviewer.jnlp?SESSIONKEY={session_key}")
    candidates += [
        "/Java/jviewer.jnlp",
        "/cgi/url_redirect.cgi?url_name=ikvm&url_type=jwsk",
    ]

    hostname = profile["hostname"].strip()
    parsed_base = urllib.parse.urlparse(base)
    webport = str(parsed_base.port or (443 if parsed_base.scheme == "https" else 80))
    for path in candidates:
        try:
            content = _get_jnlp_bytes(opener, f"{base}{path}", log_fn=log_fn)
            content = _patch_ami_jnlp(content, hostname, session_key,
                                       profile["username"], password, webport, log_fn)
            return _save_jnlp(content, dest_folder, log_fn)
        except RuntimeError as e:
            log_fn(f"  {path}: {e}")
            continue
    raise RuntimeError(
        "Could not find the JNLP endpoint on this BMC.\n\n"
        "To fix this: open your browser's DevTools (F12) → Network tab, log "
        "into the BMC web UI, click the KVM launch button, and look for the "
        "request that downloads a .jnlp file.  Share the URL with me and I "
        "can add it."
    )


# --- Entry point -------------------------------------------------------------

def main():
    app = QApplication([])
    app.setApplicationName("IPMI Launcher")
    app.setStyle("Fusion")
    app.setStyleSheet(STYLESHEET)
    window = MainWindow()
    window.show()
    app.exec()


if __name__ == "__main__":
    main()
