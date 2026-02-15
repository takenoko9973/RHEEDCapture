from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QGroupBox, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout


class StoragePanel(QGroupBox):
    browse_requested = Signal()
    new_branch_requested = Signal()

    def __init__(self) -> None:
        super().__init__("Storage Settings")
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)

        root_h_layout = QHBoxLayout()

        self.edit_root_dir = QLineEdit("Not set")
        self.edit_root_dir.setReadOnly(True)
        self.edit_root_dir.setStyleSheet("background: transparent; border: none;")

        btn_browse = QPushButton("Browse...")
        btn_browse.clicked.connect(self.browse_requested.emit)

        root_h_layout.addWidget(self.edit_root_dir, stretch=1)
        root_h_layout.addWidget(btn_browse)

        # --- ターゲットディレクトリ表示部 ---
        target_h_layout = QHBoxLayout()
        self.lbl_target_dir = QLabel("Target: Not set")
        self.lbl_target_dir.setStyleSheet("font-weight: bold; color: blue;")
        # 長くなった時のために折り返しを許可しておく
        self.lbl_target_dir.setWordWrap(True)

        btn_new_branch = QPushButton("New Branch (-n)")
        btn_new_branch.clicked.connect(self.new_branch_requested.emit)

        target_h_layout.addWidget(self.lbl_target_dir, stretch=1)
        target_h_layout.addWidget(btn_new_branch)

        layout.addLayout(root_h_layout)
        layout.addLayout(target_h_layout)

    def update_displays(self, root_dir: str, target_dir_name: str) -> None:
        """パスを絶対パスに変換してUIに反映する"""
        # Path.resolve() を使って絶対パス化
        abs_root = str(Path(root_dir).resolve())

        self.edit_root_dir.setText(abs_root)
        self.edit_root_dir.setToolTip(abs_root)

        self.lbl_target_dir.setText(f"Target: {target_dir_name}")

    def get_values(self) -> dict:
        return {"root_dir": self.edit_root_dir.text()}
