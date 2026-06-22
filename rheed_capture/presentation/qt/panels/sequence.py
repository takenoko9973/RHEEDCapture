from PySide6.QtCore import Signal, Slot
from PySide6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QWidget,
)

from rheed_capture.presentation.qt.widgets.capture_controls import (
    configure_capture_buttons,
    configure_next_capture_label,
)
from rheed_capture.presentation.qt.widgets.chip_selector import ChipSelector, ChipValue


class SequencePanel(QGroupBox):
    """Sequence撮影の操作パネル。"""

    start_requested = Signal()
    cancel_requested = Signal()

    exposure_selection_changed = Signal(list)
    gain_selection_changed = Signal(list)

    def __init__(self) -> None:
        super().__init__("Sequence Capture")
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QFormLayout(self)

        self.exposure_selector = ChipSelector()
        self.gain_selector = ChipSelector()
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

        # チップ内には単位を出さない。
        layout.addRow("Exposure (ms):", self.exposure_selector)
        layout.addRow("Gain:", self.gain_selector)
        layout.addRow(self._create_button_row())
        layout.addRow(self._create_progress_row())

        self.exposure_selector.selection_changed.connect(self.exposure_selection_changed.emit)
        self.gain_selector.selection_changed.connect(self.gain_selection_changed.emit)
        self.btn_start.clicked.connect(self._on_start_clicked)
        self.btn_cancel.clicked.connect(self.cancel_requested.emit)

    @Slot(object, object)
    def update_exposure_values(
        self,
        values: list[ChipValue],
        selected_values: list[ChipValue],
    ) -> None:
        """候補値と選択値を受け取り、露光時間チップを再描画する。"""
        self.exposure_selector.set_values(values, selected_values)

    @Slot(object, object)
    def update_gain_values(
        self,
        values: list[ChipValue],
        selected_values: list[ChipValue],
    ) -> None:
        """候補値と選択値を受け取り、ゲインチップを再描画する。"""
        self.gain_selector.set_values(values, selected_values)

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
        # 撮影中は条件変更を止める。
        self.exposure_selector.setEnabled(not is_capturing)
        self.gain_selector.setEnabled(not is_capturing)
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
