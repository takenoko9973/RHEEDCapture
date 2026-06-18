from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QDoubleSpinBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QToolButton,
    QWidget,
)

from rheed_capture.application.ports.motor import DEFAULT_MOTOR_SPEED_RPM
from rheed_capture.domain.angle_scan.model import MAX_SCAN_ANGLE_DEG, MIN_ANGLE_INTERVAL_DEG
from rheed_capture.infrastructure.config.defaults import (
    DEFAULT_ANGLE_SCAN_RANGE_DEG,
    DEFAULT_ANGLE_SCAN_WAIT_AFTER_MOVE_MS,
    DEFAULT_EXPOSURE_MS_VALUES,
    DEFAULT_GAIN_VALUES,
)


class AngleScanPanel(QGroupBox):
    start_requested = Signal()
    cancel_requested = Signal()

    expo_text_edited = Signal(str)
    gain_text_edited = Signal(str)
    range_angle_changed = Signal(float)
    interval_angle_changed = Signal(float)
    settling_time_changed = Signal(int)
    motor_speed_changed = Signal(float)
    return_to_start_changed = Signal(bool)
    scan_direction_changed = Signal(str)

    def __init__(self) -> None:
        super().__init__("Angle Scan Capture")
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QGridLayout(self)
        layout.setHorizontalSpacing(8)
        layout.setVerticalSpacing(6)

        self._create_controls()
        self._populate_layout(layout)
        self._connect_signals()

    def _create_controls(self) -> None:
        self.edit_expo = QLineEdit(self._format_default_values(DEFAULT_EXPOSURE_MS_VALUES))
        self.edit_gain = QLineEdit(self._format_default_values(DEFAULT_GAIN_VALUES))

        self.spin_range_deg = self._create_scan_range_spinbox(DEFAULT_ANGLE_SCAN_RANGE_DEG)
        self.spin_interval_deg = QDoubleSpinBox()
        self.spin_interval_deg.setRange(MIN_ANGLE_INTERVAL_DEG, 360.0)
        self.spin_interval_deg.setDecimals(1)
        self.spin_interval_deg.setSingleStep(MIN_ANGLE_INTERVAL_DEG)
        self.spin_interval_deg.setValue(MIN_ANGLE_INTERVAL_DEG)

        self.spin_settling_ms = QDoubleSpinBox()
        self.spin_settling_ms.setRange(0, 600_000)
        self.spin_settling_ms.setDecimals(0)
        self.spin_settling_ms.setValue(DEFAULT_ANGLE_SCAN_WAIT_AFTER_MOVE_MS)
        self.spin_settling_ms.setSingleStep(100)
        self.spin_settling_ms.setToolTip("Wait after each motor move before capture.")

        self.spin_motor_speed_rpm = QDoubleSpinBox()
        self.spin_motor_speed_rpm.setRange(0.1, 60.0)
        self.spin_motor_speed_rpm.setDecimals(1)
        self.spin_motor_speed_rpm.setSingleStep(1.0)
        self.spin_motor_speed_rpm.setValue(DEFAULT_MOTOR_SPEED_RPM)
        self.spin_motor_speed_rpm.setToolTip("Motor speed used during angle scan.")

        self.chk_return_to_start = QCheckBox("Return to Start")
        self.chk_return_to_start.setToolTip("Move back to 0 deg after the scan.")

        self.direction_buttons = QButtonGroup(self)
        self.direction_buttons.setExclusive(True)
        self.btn_direction_positive = self._create_direction_button("+", "positive")
        self.btn_direction_negative = self._create_direction_button("-", "negative")
        self.btn_direction_both = self._create_direction_button("±", "both")
        self.btn_direction_both.setChecked(True)

        self.lbl_next_angle_scan_preview = QLabel("angle_scan_001")
        self.btn_start = QPushButton("Start Angle Scan")
        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.setEnabled(False)
        self.lbl_progress_status = QLabel("Angle: -")
        self.lbl_progress_status.setMinimumWidth(90)
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)

    def _format_default_values(self, values: tuple[float, ...] | tuple[int, ...]) -> str:
        """設定デフォルトの条件リストを、編集欄のカンマ区切り文字列へ変換する。"""
        return ", ".join(f"{value:g}" for value in values)

    def _populate_layout(self, layout: QGridLayout) -> None:
        layout.addWidget(QLabel("Range (deg):"), 0, 0)
        layout.addWidget(self.spin_range_deg, 0, 1)
        layout.addWidget(QLabel("Interval (deg):"), 0, 2)
        layout.addWidget(self.spin_interval_deg, 0, 3)
        layout.addWidget(QLabel("Wait after move (ms):"), 1, 0)
        layout.addWidget(self.spin_settling_ms, 1, 1)
        layout.addWidget(QLabel("Motor speed (rpm):"), 1, 2)
        layout.addWidget(self.spin_motor_speed_rpm, 1, 3)
        layout.addWidget(QLabel("Direction:"), 2, 0)
        layout.addWidget(self._create_direction_widget(), 2, 1, 1, 3)

        layout.addWidget(
            self.chk_return_to_start,
            3,
            0,
            1,
            2,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
        )

        layout.addWidget(QLabel("Exposures (ms):"), 4, 0)
        layout.addWidget(self.edit_expo, 4, 1, 1, 3)
        layout.addWidget(QLabel("Gains:"), 5, 0)
        layout.addWidget(self.edit_gain, 5, 1, 1, 3)
        layout.addWidget(QLabel("Next:"), 6, 0)
        layout.addWidget(self.lbl_next_angle_scan_preview, 6, 1)
        layout.addWidget(self.btn_start, 6, 2)
        layout.addWidget(self.btn_cancel, 6, 3)
        layout.addWidget(self.progress_bar, 7, 0, 1, 3)
        layout.addWidget(
            self.lbl_progress_status,
            7,
            3,
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
        )
        layout.setColumnStretch(1, 1)
        layout.setColumnStretch(3, 1)

    def _connect_signals(self) -> None:
        self.edit_expo.editingFinished.connect(
            lambda: self.expo_text_edited.emit(self.edit_expo.text())
        )
        self.edit_gain.editingFinished.connect(
            lambda: self.gain_text_edited.emit(self.edit_gain.text())
        )
        self.spin_range_deg.valueChanged.connect(self.range_angle_changed.emit)
        self.spin_interval_deg.valueChanged.connect(self.interval_angle_changed.emit)
        self.spin_settling_ms.valueChanged.connect(
            lambda value: self.settling_time_changed.emit(round(value))
        )
        self.spin_motor_speed_rpm.valueChanged.connect(self.motor_speed_changed.emit)
        self.chk_return_to_start.toggled.connect(self.return_to_start_changed.emit)
        self.direction_buttons.idClicked.connect(self._emit_direction_from_id)
        self.btn_start.clicked.connect(self.start_requested.emit)
        self.btn_cancel.clicked.connect(self.cancel_requested.emit)

    def _create_scan_range_spinbox(self, value: float) -> QDoubleSpinBox:
        spinbox = QDoubleSpinBox()
        spinbox.setRange(MIN_ANGLE_INTERVAL_DEG, MAX_SCAN_ANGLE_DEG)
        spinbox.setDecimals(1)
        spinbox.setSingleStep(MIN_ANGLE_INTERVAL_DEG)
        spinbox.setValue(value)
        return spinbox

    def _create_direction_button(self, text: str, direction: str) -> QToolButton:
        button = QToolButton()
        button.setText(text)
        button.setCheckable(True)
        button.setMinimumWidth(36)
        self.direction_buttons.addButton(button, self._direction_to_id(direction))
        return button

    def _create_direction_widget(self) -> QWidget:
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(self.btn_direction_positive)
        layout.addWidget(self.btn_direction_negative)
        layout.addWidget(self.btn_direction_both)
        layout.addStretch(1)
        return widget

    def _emit_direction_from_id(self, button_id: int) -> None:
        self.scan_direction_changed.emit(self._id_to_direction(button_id))

    @staticmethod
    def _direction_to_id(direction: str) -> int:
        return {"positive": 1, "negative": 2, "both": 3}[direction]

    @staticmethod
    def _id_to_direction(button_id: int) -> str:
        return {1: "positive", 2: "negative", 3: "both"}[button_id]

    @Slot(str)
    def update_expo_ui(self, text: str) -> None:
        self.edit_expo.setText(text)

    @Slot(str)
    def update_gain_ui(self, text: str) -> None:
        self.edit_gain.setText(text)

    @Slot(float)
    def update_range_angle_ui(self, value: float) -> None:
        self.spin_range_deg.setValue(value)

    @Slot(float)
    def update_interval_angle_ui(self, value: float) -> None:
        self.spin_interval_deg.setValue(value)

    @Slot(int)
    def update_settling_time_ui(self, value: int) -> None:
        self.spin_settling_ms.setValue(value)

    @Slot(float)
    def update_motor_speed_ui(self, value: float) -> None:
        self.spin_motor_speed_rpm.setValue(value)

    @Slot(bool)
    def update_return_to_start_ui(self, value: bool) -> None:
        self.chk_return_to_start.setChecked(value)

    @Slot(str)
    def update_scan_direction_ui(self, value: str) -> None:
        button = self.direction_buttons.button(self._direction_to_id(value))
        if button:
            button.setChecked(True)

    @Slot(str)
    def update_next_angle_scan_preview(self, text: str) -> None:
        self.lbl_next_angle_scan_preview.setText(text)

    @Slot(int, int, float)
    def update_progress(self, current: int, total: int, angle_deg: float) -> None:
        self.progress_bar.setMaximum(total)
        self.progress_bar.setValue(current)
        self.progress_bar.setFormat(f"{current}/{total}")
        self.lbl_progress_status.setText(f"Angle: {angle_deg:+.1f} deg")

    def set_capturing_state(self, is_capturing: bool) -> None:
        self.btn_start.setEnabled(not is_capturing)
        self.btn_cancel.setEnabled(is_capturing)
        if is_capturing:
            self.progress_bar.setValue(0)
            self.progress_bar.setFormat("0/%m")
            self.lbl_progress_status.setText("Angle: -")
