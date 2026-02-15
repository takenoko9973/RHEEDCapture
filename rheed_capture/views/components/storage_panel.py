from PySide6.QtCore import Signal
from PySide6.QtWidgets import QGroupBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout


class StoragePanel(QGroupBox):
    browse_requested = Signal()
    new_branch_requested = Signal()

    def __init__(self) -> None:
        super().__init__("Storage Settings")
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)

        root_h_layout = QHBoxLayout()
        self.lbl_root_dir = QLabel("Not set")
        btn_browse = QPushButton("Browse...")
        btn_browse.clicked.connect(self.browse_requested.emit)
        root_h_layout.addWidget(self.lbl_root_dir)
        root_h_layout.addWidget(btn_browse)

        target_h_layout = QHBoxLayout()
        self.lbl_target_dir = QLabel("Target: Not set")
        self.lbl_target_dir.setStyleSheet("font-weight: bold; color: blue;")
        btn_new_branch = QPushButton("New Branch (-n)")
        btn_new_branch.clicked.connect(self.new_branch_requested.emit)
        target_h_layout.addWidget(self.lbl_target_dir)
        target_h_layout.addWidget(btn_new_branch)

        layout.addLayout(root_h_layout)
        layout.addLayout(target_h_layout)

    def update_displays(self, root_dir: str, target_dir_name: str) -> None:
        self.lbl_root_dir.setText(root_dir)
        self.lbl_target_dir.setText(f"Target: {target_dir_name}")

    def get_values(self) -> dict:
        return {"root_dir": self.lbl_root_dir.text()}
