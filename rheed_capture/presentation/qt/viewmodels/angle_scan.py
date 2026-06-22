from __future__ import annotations

from typing import TYPE_CHECKING, cast

from PySide6.QtCore import QObject, Signal, Slot

from rheed_capture.domain.angle_scan.model import (
    AngleScanDirection,
    validate_direction,
    validate_interval,
    validate_interval_within_range,
    validate_range,
)
from rheed_capture.domain.capture_condition import CaptureCondition
from rheed_capture.infrastructure.config.schema import (
    AngleScanCaptureSettings,
    AppSettingsData,
    DeviceSettings,
    MotorDeviceSettings,
    filter_existing_float_values,
    filter_existing_int_values,
)
from rheed_capture.presentation.qt.workers.angle_scan_service import (
    AngleScanService,
    AngleScanSettings,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from rheed_capture.application.ports.motor import RotationMotor
    from rheed_capture.infrastructure.camera.basler_camera import CameraDevice
    from rheed_capture.infrastructure.storage.experiment_storage import ExperimentStorage


class AngleScanViewModel(QObject):
    """角度走査UIの状態管理と、角度走査サービスの起動を担当するViewModel。"""

    progress_updated = Signal(int, int, float)
    frame_captured = Signal(object)
    angle_scan_finished = Signal(bool, str)
    error_occurred = Signal(str)

    exposure_values_updated = Signal(object, object)
    gain_values_updated = Signal(object, object)
    motor_port_updated = Signal(str)
    motor_slave_updated = Signal(int)
    motor_speed_updated = Signal(float)
    position_units_per_deg_updated = Signal(float)
    range_angle_updated = Signal(float)
    interval_angle_updated = Signal(float)
    settling_time_updated = Signal(int)
    return_to_start_updated = Signal(bool)
    scan_direction_updated = Signal(str)

    preview_resume_requested = Signal()
    preview_pause_requested = Signal()

    def __init__(
        self,
        camera: CameraDevice,
        storage: ExperimentStorage,
        motor_factory: Callable[[str, int, float], RotationMotor] | None = None,
    ) -> None:
        super().__init__()
        self._camera = camera
        self._storage = storage
        self._motor_factory = motor_factory
        self._angle_scan_service: AngleScanService | None = None

        defaults = AppSettingsData()
        scan_defaults = defaults.angle_scan
        # 候補値はSettingsタブと共有、選択値はAngle Scan専用として保持する。
        self._exposure_ms_values = defaults.exposure_ms_values
        self._gain_values = defaults.gain_values
        self._selected_exposure_ms_values = scan_defaults.selected_exposure_ms_values
        self._selected_gain_values = scan_defaults.selected_gain_values

        motor_defaults = MotorDeviceSettings()
        self._motor_port = motor_defaults.port
        self._motor_slave = motor_defaults.slave
        self._position_units_per_deg = motor_defaults.position_units_per_deg

        self._range_deg = scan_defaults.range_deg
        self._interval_deg = scan_defaults.interval_deg
        self._scan_direction: AngleScanDirection = scan_defaults.direction
        self._settling_time_ms = scan_defaults.wait_after_move_ms
        self._motor_speed_rpm = scan_defaults.motor_speed_rpm
        self._return_to_start = scan_defaults.return_to_start

    def load_settings(self, settings: AppSettingsData) -> None:
        scan_settings = settings.angle_scan
        motor_settings = settings.device.motor

        self.update_candidate_values(settings.exposure_ms_values, settings.gain_values)
        self.update_selected_exposure_ms_values(
            scan_settings.selected_exposure_ms_values
        )
        self.update_selected_gain_values(scan_settings.selected_gain_values)
        self.update_motor_port(motor_settings.port)
        self.update_motor_slave(motor_settings.slave)
        self.update_position_units_per_deg(motor_settings.position_units_per_deg)
        self.update_range_angle(scan_settings.range_deg)
        self.update_interval_angle(scan_settings.interval_deg)
        self.update_scan_direction(scan_settings.direction)
        self.update_settling_time_ms(scan_settings.wait_after_move_ms)
        self.update_motor_speed(scan_settings.motor_speed_rpm)
        self.update_return_to_start(scan_settings.return_to_start)

    def get_angle_scan_settings(self) -> AngleScanCaptureSettings:
        return AngleScanCaptureSettings(
            selected_exposure_ms_values=self._selected_exposure_ms_values,
            selected_gain_values=self._selected_gain_values,
            range_deg=self._range_deg,
            interval_deg=self._interval_deg,
            direction=self._scan_direction,
            wait_after_move_ms=self._settling_time_ms,
            motor_speed_rpm=self._motor_speed_rpm,
            return_to_start=self._return_to_start,
        )

    def get_device_settings(self) -> DeviceSettings:
        return DeviceSettings(
            motor=MotorDeviceSettings(
                port=self._motor_port,
                slave=self._motor_slave,
                position_units_per_deg=self._position_units_per_deg,
            )
        )

    @Slot(object, object)
    def update_candidate_values(
        self,
        exposure_ms_values: list[float],
        gain_values: list[int],
    ) -> None:
        """候補値の変更をAngle Scan側の選択状態へ反映する。"""
        self._exposure_ms_values = list(exposure_ms_values)
        self._gain_values = list(gain_values)
        # 候補から消えた値は選択状態から除外する。別候補の自動選択はしない。
        self._selected_exposure_ms_values = filter_existing_float_values(
            self._selected_exposure_ms_values,
            set(self._exposure_ms_values),
        )
        self._selected_gain_values = filter_existing_int_values(
            self._selected_gain_values,
            set(self._gain_values),
        )
        self._emit_value_state()

    @Slot(list)
    def update_selected_exposure_ms_values(self, selected_values: list[float]) -> None:
        """露光時間チップのクリック結果を保存可能な選択値へ正規化する。"""
        self._selected_exposure_ms_values = filter_existing_float_values(
            [float(value) for value in selected_values],
            set(self._exposure_ms_values),
        )
        self.exposure_values_updated.emit(
            self._exposure_ms_values,
            self._selected_exposure_ms_values,
        )

    @Slot(list)
    def update_selected_gain_values(self, selected_values: list[int]) -> None:
        """ゲインチップのクリック結果を保存可能な選択値へ正規化する。"""
        self._selected_gain_values = filter_existing_int_values(
            [int(value) for value in selected_values],
            set(self._gain_values),
        )
        self.gain_values_updated.emit(self._gain_values, self._selected_gain_values)

    @Slot(str)
    def update_motor_port(self, value: str) -> None:
        self._motor_port = value.strip()
        self.motor_port_updated.emit(self._motor_port)

    @Slot(int)
    def update_motor_slave(self, value: int) -> None:
        self._motor_slave = value
        self.motor_slave_updated.emit(value)

    @Slot(float)
    def update_motor_speed(self, value: float) -> None:
        if value <= 0:
            self.error_occurred.emit("モーター速度は正の値にしてください。")
            self.motor_speed_updated.emit(self._motor_speed_rpm)
            return

        self._motor_speed_rpm = value
        self.motor_speed_updated.emit(value)

    @Slot(float)
    def update_position_units_per_deg(self, value: float) -> None:
        if value <= 0:
            self.error_occurred.emit("1degあたりのモーター位置単位は正の値にしてください。")
            self.position_units_per_deg_updated.emit(self._position_units_per_deg)
            return

        self._position_units_per_deg = value
        self.position_units_per_deg_updated.emit(value)

    @Slot(float)
    def update_range_angle(self, value: float) -> None:
        try:
            validate_range(value)
            validate_interval_within_range(value, self._interval_deg)
        except ValueError as e:
            self.error_occurred.emit(str(e))
            self.range_angle_updated.emit(self._range_deg)
            return

        self._range_deg = value
        self.range_angle_updated.emit(value)

    @Slot(float)
    def update_interval_angle(self, value: float) -> None:
        try:
            validate_interval(value)
            validate_interval_within_range(self._range_deg, value)
        except ValueError as e:
            self.error_occurred.emit(str(e))
            self.interval_angle_updated.emit(self._interval_deg)
            return

        self._interval_deg = value
        self.interval_angle_updated.emit(value)

    @Slot(int)
    def update_settling_time_ms(self, value: int) -> None:
        self._settling_time_ms = value
        self.settling_time_updated.emit(value)

    @Slot(bool)
    def update_return_to_start(self, value: bool) -> None:
        self._return_to_start = value
        self.return_to_start_updated.emit(value)

    @Slot(str)
    def update_scan_direction(self, value: str) -> None:
        try:
            validate_direction(value)
        except ValueError as e:
            self.error_occurred.emit(str(e))
            self.scan_direction_updated.emit(self._scan_direction)
            return

        self._scan_direction = cast("AngleScanDirection", value)
        self.scan_direction_updated.emit(value)

    @Slot()
    def start_angle_scan(self) -> None:
        try:
            # UIの選択値をService層へ渡す前に、最終的なCaptureConditionへ解決する。
            conditions = self._build_capture_conditions()
            motor = self._require_motor_factory()(
                self._motor_port,
                self._motor_slave,
                self._position_units_per_deg,
            )
            settings = AngleScanSettings(
                range_deg=self._range_deg,
                interval_deg=self._interval_deg,
                direction=self._scan_direction,
                settling_time_ms=self._settling_time_ms,
                return_to_start_after_scan=self._return_to_start,
                motor_speed_rpm=self._motor_speed_rpm,
                position_units_per_deg=self._position_units_per_deg,
            )
        except (ValueError, RuntimeError) as e:
            self.error_occurred.emit(str(e))
            self.angle_scan_finished.emit(False, "")
            return

        try:
            # AngleScanServiceより下では、チップ候補や選択値ではなく撮影条件だけを扱う。
            self._angle_scan_service = AngleScanService(
                self._camera,
                self._storage,
                motor,
                conditions,
                settings,
            )
        except ValueError as e:
            self.error_occurred.emit(str(e))
            self.angle_scan_finished.emit(False, "")
            return

        self._connect_angle_scan_service(self._angle_scan_service)
        self._angle_scan_service.start()

    def _require_motor_factory(self) -> Callable[[str, int, float], RotationMotor]:
        if self._motor_factory is None:
            msg = "モーター生成処理が設定されていません。"
            raise RuntimeError(msg)

        return self._motor_factory

    def _connect_angle_scan_service(self, service: AngleScanService) -> None:
        service.progress_update.connect(self.progress_updated)
        service.frame_captured.connect(self.frame_captured)
        service.scan_finished.connect(self.angle_scan_finished)
        service.error_occurred.connect(self.error_occurred)
        service.preview_resume_requested.connect(self.preview_resume_requested)
        service.preview_pause_requested.connect(self.preview_pause_requested)

    @Slot()
    def notify_preview_paused(self) -> None:
        if self._angle_scan_service:
            self._angle_scan_service.notify_preview_paused()

    @Slot()
    def cancel_angle_scan(self) -> None:
        if self.is_running() and self._angle_scan_service:
            self._angle_scan_service.cancel()

    def is_running(self) -> bool:
        return self._angle_scan_service is not None and self._angle_scan_service.isRunning()

    def _build_capture_conditions(self) -> list[CaptureCondition]:
        """選択された露光時間とゲインの直積から撮影条件を生成する。"""
        if not self._selected_exposure_ms_values:
            msg = "露光時間が選択されていません。\n1つ以上の露光時間を選択してください。"
            raise ValueError(msg)
        if not self._selected_gain_values:
            msg = "ゲインが選択されていません。\n1つ以上のゲインを選択してください。"
            raise ValueError(msg)

        return [
            CaptureCondition(exposure_ms=exposure_ms, gain=gain)
            for exposure_ms in self._selected_exposure_ms_values
            for gain in self._selected_gain_values
        ]

    def _emit_value_state(self) -> None:
        """候補値と選択値をセットでViewへ通知する。"""
        self.exposure_values_updated.emit(
            self._exposure_ms_values,
            self._selected_exposure_ms_values,
        )
        self.gain_values_updated.emit(self._gain_values, self._selected_gain_values)
