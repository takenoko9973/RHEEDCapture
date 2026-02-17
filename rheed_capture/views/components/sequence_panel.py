from PySide6.QtCore import Signal, Slot
from PySide6.QtWidgets import QFormLayout, QGroupBox, QLineEdit, QProgressBar, QPushButton


class SequencePanel(QGroupBox):
    start_requested = Signal()
    cancel_requested = Signal()

    expo_text_edited = Signal(str)
    gain_text_edited = Signal(str)

    def __init__(self) -> None:
        super().__init__("Sequence Capture")
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QFormLayout(self)

        self.edit_seq_expo = QLineEdit("10, 50, 100")
        self.edit_seq_gain = QLineEdit("0")
        self.btn_start = QPushButton("Start Sequence Capture")
        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.setEnabled(False)
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)

        layout.addRow("Exposures (ms):", self.edit_seq_expo)
        layout.addRow("Gains:", self.edit_seq_gain)
        layout.addRow(self.btn_start)
        layout.addRow(self.btn_cancel)
        layout.addRow(self.progress_bar)

        # QLineEditの編集完了(Enterキー押下 or フォーカスが外れた時)にシグナルを発火
        self.edit_seq_expo.editingFinished.connect(
            lambda: self.expo_text_edited.emit(self.edit_seq_expo.text())
        )
        self.edit_seq_gain.editingFinished.connect(
            lambda: self.gain_text_edited.emit(self.edit_seq_gain.text())
        )

        self.btn_start.clicked.connect(self._on_start_clicked)
        self.btn_cancel.clicked.connect(self.cancel_requested.emit)

    @Slot(str)
    def update_expo_ui(self, text: str) -> None:
        self.edit_seq_expo.setText(text)

    @Slot(str)
    def update_gain_ui(self, text: str) -> None:
        self.edit_seq_gain.setText(text)

    @Slot()
    def _on_start_clicked(self) -> None:
        self.start_requested.emit()

    @Slot(int, int)
    def update_progress(self, current: int, total: int) -> None:
        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(current)

    def set_capturing_state(self, is_capturing: bool) -> None:
        self.btn_start.setEnabled(not is_capturing)
        self.btn_cancel.setEnabled(is_capturing)
        if is_capturing:
            self.progress_bar.setValue(0)
