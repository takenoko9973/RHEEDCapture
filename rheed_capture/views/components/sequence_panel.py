from PySide6.QtCore import Signal, Slot
from PySide6.QtWidgets import QFormLayout, QGroupBox, QLineEdit, QProgressBar, QPushButton


class SequencePanel(QGroupBox):
    start_requested = Signal(list, list)  # exp_list, gain_list
    cancel_requested = Signal()
    validation_error = Signal(str)

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

        self.btn_start.clicked.connect(self._on_start_clicked)
        self.btn_cancel.clicked.connect(self.cancel_requested.emit)

    @Slot()
    def _on_start_clicked(self) -> None:
        try:
            expo_list = [
                float(x.strip()) for x in self.edit_seq_expo.text().split(",") if x.strip()
            ]
            gain_list = [
                float(x.strip()) for x in self.edit_seq_gain.text().split(",") if x.strip()
            ]
            self._check_expo_and_gain_empty(expo_list, gain_list)

            self.start_requested.emit(expo_list, gain_list)
        except ValueError:
            self.validation_error.emit("Invalid input. Please enter numbers separated by commas.")

    def _check_expo_and_gain_empty(self, expo_list: list, gain_list: list) -> None:
        if not expo_list or not gain_list:
            msg = "List cannot be empty."
            raise ValueError(msg)

    def set_capturing_state(self, is_capturing: bool) -> None:
        self.btn_start.setEnabled(not is_capturing)
        self.btn_cancel.setEnabled(is_capturing)
        if is_capturing:
            self.progress_bar.setValue(0)

    @Slot(int, int)
    def update_progress(self, current: int, total: int) -> None:
        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(current)

    def set_values(self, exp_text: str, gain_text: str) -> None:
        self.edit_seq_expo.setText(exp_text)
        self.edit_seq_gain.setText(gain_text)

    def get_values(self) -> dict:
        return {
            "seq_expo_list": self.edit_seq_expo.text(),
            "seq_gain_list": self.edit_seq_gain.text(),
        }
