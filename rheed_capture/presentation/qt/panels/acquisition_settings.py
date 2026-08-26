from __future__ import annotations

from typing import cast

from PySide6.QtCore import QSignalBlocker, Signal, Slot
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QSpinBox,
    QWidget,
)

from rheed_capture.infrastructure.config.schema import (
    AcquisitionHardwareActivation,
    AcquisitionHardwareSource,
    AcquisitionMode,
    AcquisitionSettings,
)


class AcquisitionSettingsPanel(QGroupBox):
    """Settingsタブで共通Trigger取得条件を編集するパネル。"""

    settings_changed = Signal(object)

    def __init__(self) -> None:
        """共通Acquisition設定の入力Widgetを生成する。"""
        super().__init__("Acquisition Settings")
        self._controls_enabled = True
        self._setup_ui()
        self._update_control_state()

    def _setup_ui(self) -> None:
        """入力Widgetを作成し、Settingsモデルへ変換するSignalを結線する。"""
        layout = QFormLayout(self)

        self.cmb_mode = QComboBox()
        self.cmb_mode.addItem("Software", "software")
        self.cmb_mode.addItem("Hardware", "hardware")

        self.cmb_source = QComboBox()
        self.cmb_source.addItems(["Line1", "Line3", "Action1"])

        self.cmb_activation = QComboBox()
        self.cmb_activation.addItems(["RisingEdge", "FallingEdge"])

        self.spin_delay_us = QDoubleSpinBox()
        self.spin_delay_us.setRange(0.0, 1_000_000_000.0)
        self.spin_delay_us.setDecimals(3)
        self.spin_delay_us.setSuffix(" us")

        self.chk_fps_unlimited = QCheckBox("Unlimited")
        self.chk_fps_unlimited.setChecked(True)
        self.spin_fps_limit = QDoubleSpinBox()
        self.spin_fps_limit.setRange(0.001, 1_000_000.0)
        self.spin_fps_limit.setDecimals(3)
        self.spin_fps_limit.setSuffix(" FPS")
        self.spin_fps_limit.setValue(10.0)

        self.chk_accumulation = QCheckBox("On")
        self.spin_accumulation_frames = QSpinBox()
        self.spin_accumulation_frames.setRange(1, 1_000_000)
        self.spin_accumulation_frames.setValue(1)

        self.spin_trigger_wait_timeout_sec = QDoubleSpinBox()
        self.spin_trigger_wait_timeout_sec.setRange(0.0, 1_000_000_000.0)
        self.spin_trigger_wait_timeout_sec.setDecimals(3)
        self.spin_trigger_wait_timeout_sec.setSuffix(" s (0 = unlimited)")

        layout.addRow("Trigger Mode:", self.cmb_mode)
        layout.addRow("Hardware Source:", self.cmb_source)
        layout.addRow("Hardware Activation:", self.cmb_activation)
        layout.addRow("Trigger Delay:", self.spin_delay_us)
        layout.addRow("FPS Limit:", self._create_fps_row())
        layout.addRow("Accumulation:", self.chk_accumulation)
        layout.addRow("Accumulation Frames:", self.spin_accumulation_frames)
        layout.addRow("Trigger Wait Timeout:", self.spin_trigger_wait_timeout_sec)

        self.cmb_mode.currentIndexChanged.connect(self._on_mode_changed)
        self.cmb_source.currentIndexChanged.connect(self._emit_settings_changed)
        self.cmb_activation.currentIndexChanged.connect(self._emit_settings_changed)
        self.spin_delay_us.valueChanged.connect(self._emit_settings_changed)
        self.chk_fps_unlimited.toggled.connect(self._on_fps_unlimited_toggled)
        self.spin_fps_limit.valueChanged.connect(self._emit_settings_changed)
        self.chk_accumulation.toggled.connect(self._emit_settings_changed)
        self.spin_accumulation_frames.valueChanged.connect(self._emit_settings_changed)
        self.spin_trigger_wait_timeout_sec.valueChanged.connect(self._emit_settings_changed)

    def _create_fps_row(self) -> QWidget:
        """Unlimited切替と有限FPS入力を一行へ配置する。"""
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.chk_fps_unlimited)
        layout.addWidget(self.spin_fps_limit)
        return widget

    @Slot(int)
    def _on_mode_changed(self, _index: int) -> None:
        """Trigger Mode変更時にHardware専用入力の状態を更新する。"""
        self._update_control_state()
        self._emit_settings_changed()

    @Slot(bool)
    def _on_fps_unlimited_toggled(self, _enabled: bool) -> None:
        """FPS Limitの有限値入力状態を更新し、変更を通知する。"""
        self._update_control_state()
        self._emit_settings_changed()

    def _update_control_state(self) -> None:
        """Mode、Unlimited、撮影状態を合成して各入力のenable状態を決める。"""
        common_enabled = self._controls_enabled
        hardware_enabled = common_enabled and self.cmb_mode.currentData() == "hardware"
        finite_fps_enabled = common_enabled and not self.chk_fps_unlimited.isChecked()

        self.cmb_mode.setEnabled(common_enabled)
        self.cmb_source.setEnabled(hardware_enabled)
        self.cmb_activation.setEnabled(hardware_enabled)
        self.spin_delay_us.setEnabled(hardware_enabled)
        self.chk_fps_unlimited.setEnabled(common_enabled)
        self.spin_fps_limit.setEnabled(finite_fps_enabled)
        self.chk_accumulation.setEnabled(common_enabled)
        self.spin_accumulation_frames.setEnabled(common_enabled)
        self.spin_trigger_wait_timeout_sec.setEnabled(common_enabled)

    def get_settings_to_save(self) -> AcquisitionSettings:
        """現在の入力値を保存用AcquisitionSettingsへ変換する。"""
        return AcquisitionSettings(
            mode=cast("AcquisitionMode", self.cmb_mode.currentData()),
            hardware_source=cast("AcquisitionHardwareSource", self.cmb_source.currentText()),
            hardware_activation=cast(
                "AcquisitionHardwareActivation",
                self.cmb_activation.currentText(),
            ),
            hardware_delay_us=self.spin_delay_us.value(),
            fps_limit=(
                None
                if self.chk_fps_unlimited.isChecked()
                else self.spin_fps_limit.value()
            ),
            accumulation_enabled=self.chk_accumulation.isChecked(),
            accumulation_frames=self.spin_accumulation_frames.value(),
            trigger_wait_timeout_sec=self.spin_trigger_wait_timeout_sec.value(),
        )

    def apply_settings(self, settings: AcquisitionSettings) -> None:
        """保存済みAcquisition設定を入力Widgetへ反映する。"""
        with QSignalBlocker(self.cmb_mode):
            self.cmb_mode.setCurrentIndex(self.cmb_mode.findData(settings.mode))
        with QSignalBlocker(self.cmb_source):
            self.cmb_source.setCurrentText(settings.hardware_source)
        with QSignalBlocker(self.cmb_activation):
            self.cmb_activation.setCurrentText(settings.hardware_activation)
        with QSignalBlocker(self.spin_delay_us):
            self.spin_delay_us.setValue(settings.hardware_delay_us)
        with QSignalBlocker(self.spin_fps_limit):
            if settings.fps_limit is not None:
                self.spin_fps_limit.setValue(settings.fps_limit)
        with QSignalBlocker(self.chk_fps_unlimited):
            self.chk_fps_unlimited.setChecked(settings.fps_limit is None)
        with QSignalBlocker(self.chk_accumulation):
            self.chk_accumulation.setChecked(settings.accumulation_enabled)
        with QSignalBlocker(self.spin_accumulation_frames):
            self.spin_accumulation_frames.setValue(settings.accumulation_frames)
        with QSignalBlocker(self.spin_trigger_wait_timeout_sec):
            self.spin_trigger_wait_timeout_sec.setValue(settings.trigger_wait_timeout_sec)
        self._update_control_state()

    def set_controls_enabled(self, enabled: bool) -> None:
        """保存撮影中は共通Acquisition設定を一括でロックする。"""
        self._controls_enabled = enabled
        self._update_control_state()

    def _emit_settings_changed(self, *_args: object) -> None:
        """現在の設定モデルを外部へ通知する。"""
        self.settings_changed.emit(self.get_settings_to_save())
