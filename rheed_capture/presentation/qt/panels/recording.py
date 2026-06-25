from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QSignalBlocker, Signal, Slot
from PySide6.QtWidgets import (
    QButtonGroup,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QStackedWidget,
    QToolButton,
    QWidget,
)

from rheed_capture.presentation.qt.widgets.capture_controls import (
    configure_capture_buttons,
    configure_next_capture_label,
)

RATE_VALUE_LABEL_WIDTH = 82
RATE_VALUE_INPUT_WIDTH = 128

if TYPE_CHECKING:
    from rheed_capture.infrastructure.config.schema import RecordingCaptureSettings


class RecordingPanel(QGroupBox):
    """Recordingタブの入力欄と操作ボタンをまとめるQtパネル。"""

    start_requested = Signal()
    stop_requested = Signal()

    exposure_changed = Signal(float)
    gain_changed = Signal(int)
    rate_mode_changed = Signal(str)
    fps_changed = Signal(float)
    interval_changed = Signal(float)
    duration_changed = Signal(float)

    def __init__(
        self,
        exposure_bounds: tuple[float, float],
        gain_bounds: tuple[int, int],
    ) -> None:
        """露光時間とGainの許容範囲を受け取り、Recording UIを構築する。"""
        super().__init__("Recording Capture")
        self._exposure_bounds = exposure_bounds
        self._gain_bounds = gain_bounds
        self._rate_mode = "interval"
        self._setup_ui()

    def _setup_ui(self) -> None:
        """Widget作成、Layout配置、Signal接続を順に行う。"""
        layout = QFormLayout(self)
        self._create_controls()
        self._populate_layout(layout)
        self._connect_signals()

    def _create_controls(self) -> None:
        """Recordingパネル内で使う入力Widgetを生成する。"""
        self.spin_exposure_ms = QDoubleSpinBox()
        self.spin_exposure_ms.setRange(*self._exposure_bounds)
        self.spin_exposure_ms.setDecimals(3)
        self.spin_exposure_ms.setValue(50.0)
        self.spin_exposure_ms.setSingleStep(10.0)

        self.spin_gain = QSpinBox()
        self.spin_gain.setRange(*self._gain_bounds)
        self.spin_gain.setValue(0)

        self.rate_buttons = QButtonGroup(self)
        self.rate_buttons.setExclusive(True)
        self.btn_rate_interval = self._create_rate_button("Interval", "interval")
        self.btn_rate_fps = self._create_rate_button("FPS", "fps")
        self.btn_rate_interval.setChecked(True)

        self.spin_fps = QDoubleSpinBox()
        self.spin_fps.setRange(0.001, 10_000.0)
        self.spin_fps.setDecimals(3)
        self.spin_fps.setValue(10.0)
        # Stack切替で幅が変わると入力欄の位置がずれるため固定する。
        self.spin_fps.setFixedWidth(RATE_VALUE_INPUT_WIDTH)

        self.spin_interval_ms = QDoubleSpinBox()
        self.spin_interval_ms.setRange(0.001, 3_600_000.0)
        self.spin_interval_ms.setDecimals(3)
        self.spin_interval_ms.setValue(100.0)
        self.spin_interval_ms.setFixedWidth(RATE_VALUE_INPUT_WIDTH)

        self.spin_duration_sec = QDoubleSpinBox()
        self.spin_duration_sec.setRange(0.0, 86_400.0)
        self.spin_duration_sec.setDecimals(3)
        self.spin_duration_sec.setValue(0.0)

        self.lbl_next_recording_preview = QLabel("record-1")
        configure_next_capture_label(self.lbl_next_recording_preview)
        self.btn_start = QPushButton("Start Recording")
        self.btn_stop = QPushButton("Stop Recording")
        configure_capture_buttons(self.btn_start, self.btn_stop)
        self.lbl_saved_frames = QLabel("Saved frames: 0")
        self.lbl_expected_frames = QLabel("Expected frames: -")

    def _populate_layout(self, layout: QFormLayout) -> None:
        """作成済みWidgetをフォームLayoutへ配置する。"""
        layout.addRow("Exposure (ms):", self.spin_exposure_ms)
        layout.addRow("Gain:", self.spin_gain)
        layout.addRow("Rate:", self._create_rate_control_row())
        layout.addRow("Duration (s):", self.spin_duration_sec)
        layout.addRow(self._create_button_row())
        layout.addRow(self._create_status_row())

    def _connect_signals(self) -> None:
        """UIイベントを外部公開Signalへ接続する。"""
        self.spin_exposure_ms.valueChanged.connect(self.exposure_changed.emit)
        self.spin_gain.valueChanged.connect(self.gain_changed.emit)
        self.rate_buttons.idClicked.connect(self._on_rate_mode_button_clicked)
        self.spin_fps.valueChanged.connect(self.fps_changed.emit)
        self.spin_interval_ms.valueChanged.connect(self.interval_changed.emit)
        self.spin_duration_sec.valueChanged.connect(self.duration_changed.emit)
        self.btn_start.clicked.connect(self.start_requested.emit)
        self.btn_stop.clicked.connect(self.stop_requested.emit)

    def _create_rate_button(self, text: str, mode: str) -> QToolButton:
        """FPS/Interval切替用の排他ボタンを作る。"""
        button = QToolButton()
        button.setText(text)
        button.setCheckable(True)
        button.setMinimumWidth(72)
        self.rate_buttons.addButton(button, self._rate_mode_to_id(mode))
        return button

    def _create_rate_control_row(self) -> QWidget:
        """Rate切替ボタンと現在選択中の入力欄を横並びで作る。"""
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addWidget(self.btn_rate_interval)
        layout.addWidget(self.btn_rate_fps)
        layout.addSpacing(8)
        self.lbl_rate_value = QLabel("Interval (ms):")
        # Label幅も固定し、FPS/Intervalの文字数差で入力欄が動かないようにする。
        self.lbl_rate_value.setFixedWidth(RATE_VALUE_LABEL_WIDTH)
        self.rate_value_stack = QStackedWidget()
        self.rate_value_stack.setFixedWidth(RATE_VALUE_INPUT_WIDTH)
        self.rate_value_stack.addWidget(self.spin_interval_ms)
        self.rate_value_stack.addWidget(self.spin_fps)
        self._fix_rate_control_height(widget)
        layout.addWidget(self.lbl_rate_value)
        layout.addWidget(self.rate_value_stack)
        layout.addStretch(1)
        return widget

    def _fix_rate_control_height(self, row_widget: QWidget) -> None:
        """Rate行の高さをSpinBox基準に揃え、テーマ差による縦膨張を防ぐ。"""
        height = self.spin_interval_ms.sizeHint().height()
        row_widget.setFixedHeight(height)
        self.btn_rate_interval.setFixedHeight(height)
        self.btn_rate_fps.setFixedHeight(height)
        self.lbl_rate_value.setFixedHeight(height)
        self.rate_value_stack.setFixedHeight(height)

    def _create_button_row(self) -> QWidget:
        """次回保存先表示とStart/Stopボタンの行を作る。"""
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(QLabel("Next:"))
        layout.addWidget(self.lbl_next_recording_preview)
        layout.addStretch(1)
        layout.addWidget(self.btn_start)
        layout.addWidget(self.btn_stop)
        return widget

    def _create_status_row(self) -> QWidget:
        """保存済み枚数と見込み枚数の表示行を作る。"""
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.lbl_saved_frames)
        layout.addStretch(1)
        layout.addWidget(self.lbl_expected_frames)
        return widget

    def _on_rate_mode_button_clicked(self, button_id: int) -> None:
        """切替ボタンIDをrate_modeへ変換して入力表示を切り替える。"""
        self.set_rate_mode(self._id_to_rate_mode(button_id), convert_value=True)

    def set_rate_mode(self, mode: str, *, convert_value: bool) -> None:
        """FPS/Intervalの表示を切り替え、必要なら現在値を相互変換する。"""
        if mode == self._rate_mode:
            return

        # 表示中の値を基準に換算し、非表示側の古い値で開始しないようにする。
        if mode == "fps":
            value = (
                1000.0 / self.spin_interval_ms.value()
                if convert_value
                else self.spin_fps.value()
            )
            with QSignalBlocker(self.spin_fps):
                self.spin_fps.setValue(value)
            self._show_rate_input("fps")
            self.fps_changed.emit(value)
        else:
            value = (
                1000.0 / self.spin_fps.value()
                if convert_value
                else self.spin_interval_ms.value()
            )
            with QSignalBlocker(self.spin_interval_ms):
                self.spin_interval_ms.setValue(value)
            self._show_rate_input("interval")
            self.interval_changed.emit(value)

        self._rate_mode = mode
        self.rate_mode_changed.emit(mode)

    def _show_rate_input(self, mode: str) -> None:
        """選択中のRate入力欄だけを表示する。"""
        is_fps = mode == "fps"
        self.btn_rate_fps.setChecked(is_fps)
        self.btn_rate_interval.setChecked(not is_fps)
        self.rate_value_stack.setCurrentWidget(self.spin_fps if is_fps else self.spin_interval_ms)
        self.lbl_rate_value.setText("FPS:" if is_fps else "Interval (ms):")

    def apply_settings(self, settings: RecordingCaptureSettings) -> None:
        """保存済みRecording設定をUIへ反映する。"""
        with QSignalBlocker(self.spin_exposure_ms):
            self.spin_exposure_ms.setValue(settings.exposure_ms)
        with QSignalBlocker(self.spin_gain):
            self.spin_gain.setValue(settings.gain)
        with QSignalBlocker(self.spin_fps):
            self.spin_fps.setValue(settings.fps)
        with QSignalBlocker(self.spin_interval_ms):
            self.spin_interval_ms.setValue(settings.interval_ms)
        with QSignalBlocker(self.spin_duration_sec):
            self.spin_duration_sec.setValue(settings.duration_sec)

        self._rate_mode = settings.rate_mode
        self._show_rate_input(settings.rate_mode)

    @staticmethod
    def _rate_mode_to_id(mode: str) -> int:
        """rate_mode文字列をQButtonGroupのIDへ変換する。"""
        return {"interval": 1, "fps": 2}[mode]

    @staticmethod
    def _id_to_rate_mode(button_id: int) -> str:
        """QButtonGroupのIDをrate_mode文字列へ変換する。"""
        return {1: "interval", 2: "fps"}[button_id]

    @Slot(str)
    def update_next_recording_preview(self, text: str) -> None:
        """次に作成されるRecordingディレクトリ名を表示する。"""
        self.lbl_next_recording_preview.setText(text)

    @Slot(int)
    def update_saved_frames(self, count: int) -> None:
        """保存済みフレーム数を表示する。"""
        self.lbl_saved_frames.setText(f"Saved frames: {count}")

    @Slot(str)
    def update_expected_frames(self, text: str) -> None:
        """見込みフレーム数を表示する。"""
        self.lbl_expected_frames.setText(f"Expected frames: {text}")

    def set_capturing_state(self, is_capturing: bool) -> None:
        """録画中は条件入力をロックし、Start/Stopだけを切り替える。"""
        self.btn_start.setEnabled(not is_capturing)
        self.btn_stop.setEnabled(is_capturing)
        self.spin_exposure_ms.setEnabled(not is_capturing)
        self.spin_gain.setEnabled(not is_capturing)
        self.btn_rate_interval.setEnabled(not is_capturing)
        self.btn_rate_fps.setEnabled(not is_capturing)
        self.spin_fps.setEnabled(not is_capturing)
        self.spin_interval_ms.setEnabled(not is_capturing)
        self.spin_duration_sec.setEnabled(not is_capturing)
        if is_capturing:
            self.update_saved_frames(0)
