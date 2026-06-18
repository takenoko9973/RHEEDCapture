from PySide6.QtCore import Signal, Slot
from PySide6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QWidget,
)

from rheed_capture.presentation.qt.widgets.capture_controls import (
    configure_capture_buttons,
    configure_next_capture_label,
)


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
        # 次回撮影で使用される保存先 image_xxx を表示する。
        self.lbl_next_sequence_preview = QLabel("image_001")
        configure_next_capture_label(self.lbl_next_sequence_preview)
        self.btn_start = QPushButton("Start Sequence Capture")
        self.btn_cancel = QPushButton("Cancel")
        configure_capture_buttons(self.btn_start, self.btn_cancel)
        self.lbl_progress_status = QLabel("Condition: -")
        self.lbl_progress_status.setMinimumWidth(140)
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)

        layout.addRow("Exposures (ms):", self.edit_seq_expo)
        layout.addRow("Gains:", self.edit_seq_gain)
        layout.addRow(self._create_button_row())
        layout.addRow(self._create_progress_row())

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

    @Slot(str)
    def update_next_sequence_preview(self, text: str) -> None:
        self.lbl_next_sequence_preview.setText(text)

    @Slot(int, int, float, int)
    def update_progress(
        self,
        current: int,
        total: int,
        exposure_ms: float,
        gain: int,
    ) -> None:
        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(current)
        self.progress_bar.setFormat(f"{current}/{total}")
        self.lbl_progress_status.setText(f"Condition: {exposure_ms:g} ms, gain {gain}")

    def set_capturing_state(self, is_capturing: bool) -> None:
        self.btn_start.setEnabled(not is_capturing)
        self.btn_cancel.setEnabled(is_capturing)
        if is_capturing:
            self.progress_bar.setValue(0)
            self.progress_bar.setFormat("0/%m")
            self.lbl_progress_status.setText("Condition: -")

    def _create_button_row(self) -> QWidget:
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QLabel("Next:"))
        layout.addWidget(self.lbl_next_sequence_preview)
        layout.addStretch(1)
        layout.addWidget(self.btn_start)
        layout.addWidget(self.btn_cancel)
        return widget

    def _create_progress_row(self) -> QWidget:
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.progress_bar, 1)
        layout.addWidget(self.lbl_progress_status)
        return widget
