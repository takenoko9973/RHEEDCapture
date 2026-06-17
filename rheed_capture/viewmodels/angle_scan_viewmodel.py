from typing import cast

from PySide6.QtCore import QObject, Signal, Slot

from rheed_capture.models.domain.angle_scan import (
    validate_direction,
    validate_interval,
    validate_interval_within_range,
    validate_range,
)
from rheed_capture.models.hardware.camera_device import CameraDevice
from rheed_capture.models.hardware.rotation_motor import (
    AzdCdRotationMotor,
    MotorConnectionConfig,
)
from rheed_capture.models.io.settings import (
    AngleScanCaptureSettings,
    AngleScanDirection,
    AppSettingsData,
    DeviceSettings,
    MotorDeviceSettings,
)
from rheed_capture.models.io.storage import ExperimentStorage
from rheed_capture.services.angle_scan_service import (
    AngleScanService,
    AngleScanSettings,
)
from rheed_capture.utils import parse_numbers


class AngleScanViewModel(QObject):
    """角度走査UIの状態管理と、角度走査サービスの起動を担当するViewModel。"""

    # ===== 走査実行状態の通知 =====
    progress_updated = Signal(int, int, float)
    angle_scan_finished = Signal(bool, str)
    error_occurred = Signal(str)

    # ===== 入力値を整形してViewへ戻すための通知 =====
    expo_text_updated = Signal(str)
    gain_text_updated = Signal(str)
    motor_port_updated = Signal(str)
    motor_slave_updated = Signal(int)
    motor_speed_updated = Signal(float)
    position_units_per_deg_updated = Signal(float)
    range_angle_updated = Signal(float)
    interval_angle_updated = Signal(float)
    settling_time_updated = Signal(int)
    return_to_start_updated = Signal(bool)
    scan_direction_updated = Signal(str)

    # ===== プレビュー制御要求 =====
    # 実際にPreviewViewModelを操作するのはMainWindow。
    # ここでは角度走査サービスからの要求をUI層へ中継するだけにして、依存方向を保つ。
    preview_resume_requested = Signal()
    preview_pause_requested = Signal()

    def __init__(self, camera: CameraDevice, storage: ExperimentStorage) -> None:
        super().__init__()
        self._camera = camera
        self._storage = storage
        self._angle_scan_service: AngleScanService | None = None

        # 撮影条件。通常撮影と同じく露光時間とゲインの全組み合わせを使う。
        self._expo_list: list[float] = [10.0, 50.0, 100.0]
        self._gain_list: list[int] = [0]

        # モーター装置設定。通信先と角度換算は装置側の条件として保存する。
        motor_defaults = MotorDeviceSettings()
        self._motor_port = motor_defaults.port
        self._motor_slave = motor_defaults.slave
        self._position_units_per_deg = motor_defaults.position_units_per_deg

        # 角度走査設定。開始時のモーター現在位置を常に相対0degとして扱う。
        scan_defaults = AngleScanCaptureSettings()
        self._range_deg = scan_defaults.range_deg
        self._interval_deg = scan_defaults.interval_deg
        self._scan_direction: AngleScanDirection = scan_defaults.direction
        self._settling_time_ms = scan_defaults.wait_after_move_ms
        self._motor_speed_rpm = scan_defaults.motor_speed_rpm
        self._return_to_start = scan_defaults.return_to_start

    def load_settings(self, settings: AppSettingsData) -> None:
        """保存済み設定を読み込み、内部状態とUI表示を同期する。"""
        scan_settings = settings.angle_scan
        motor_settings = settings.device.motor

        self._update_expo_state(scan_settings.exposure_ms_list)
        self._update_gain_state(scan_settings.gain_list)
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
        """アプリ終了時に保存する角度走査設定を返す。"""
        return AngleScanCaptureSettings(
            exposure_ms_list=self._expo_list,
            gain_list=self._gain_list,
            range_deg=self._range_deg,
            interval_deg=self._interval_deg,
            direction=self._scan_direction,
            wait_after_move_ms=self._settling_time_ms,
            motor_speed_rpm=self._motor_speed_rpm,
            return_to_start=self._return_to_start,
        )

    def get_device_settings(self) -> DeviceSettings:
        """角度走査で使用するモーター装置設定を返す。"""
        return DeviceSettings(
            motor=MotorDeviceSettings(
                port=self._motor_port,
                slave=self._motor_slave,
                position_units_per_deg=self._position_units_per_deg,
            )
        )

    def _empty_list_error(self) -> None:
        """露光時間やゲインの入力が空だった場合に共通エラーを出す。"""
        msg = "リストが空です"
        raise ValueError(msg)

    @Slot(str)
    def update_expo_from_text(self, text: str) -> None:
        """露光時間リストの入力を解析し、正しければ状態へ反映する。"""
        try:
            vals = parse_numbers(text, float)
            if not vals:
                self._empty_list_error()

            self._update_expo_state(vals)
        except ValueError:
            self.error_occurred.emit(
                "角度走査の露光時間の形式が正しくありません。\nカンマ区切りの数値を入力してください。"
            )
            self._update_expo_state(self._expo_list)

    @Slot(str)
    def update_gain_from_text(self, text: str) -> None:
        """ゲインリストの入力を解析し、正しければ状態へ反映する。"""
        try:
            vals = parse_numbers(text, int)
            if not vals:
                self._empty_list_error()

            self._update_gain_state(vals)
        except ValueError:
            self.error_occurred.emit(
                "角度走査のゲインの形式が正しくありません。\nカンマ区切りの整数を入力してください。"
            )
            self._update_gain_state(self._gain_list)

    def _update_expo_state(self, vals: list[float]) -> None:
        """露光時間リストを更新し、Viewへ正規化済みテキストを返す。"""
        self._expo_list = vals
        self.expo_text_updated.emit(", ".join(map(str, vals)))

    def _update_gain_state(self, vals: list[int]) -> None:
        """ゲインリストを更新し、Viewへ正規化済みテキストを返す。"""
        self._gain_list = vals
        self.gain_text_updated.emit(", ".join(map(str, vals)))

    @Slot(str)
    def update_motor_port(self, value: str) -> None:
        """COMポート名を更新する。空白は保存前に取り除く。"""
        self._motor_port = value.strip()
        self.motor_port_updated.emit(self._motor_port)

    @Slot(int)
    def update_motor_slave(self, value: int) -> None:
        """ModbusスレーブIDを更新する。"""
        self._motor_slave = value
        self.motor_slave_updated.emit(value)

    @Slot(float)
    def update_motor_speed(self, value: float) -> None:
        """角度走査中のモーター速度[rpm]を更新する。"""
        if value <= 0:
            self.error_occurred.emit("モーター速度は正の値にしてください。")
            self.motor_speed_updated.emit(self._motor_speed_rpm)
            return

        self._motor_speed_rpm = value
        self.motor_speed_updated.emit(value)

    @Slot(float)
    def update_position_units_per_deg(self, value: float) -> None:
        """1degあたりのモーター位置単位を更新する。"""
        if value <= 0:
            self.error_occurred.emit("1degあたりのモーター位置単位は正の値にしてください。")
            self.position_units_per_deg_updated.emit(self._position_units_per_deg)
            return

        self._position_units_per_deg = value
        self.position_units_per_deg_updated.emit(value)

    @Slot(float)
    def update_range_angle(self, value: float) -> None:
        """現在位置からの走査範囲を更新する。"""
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
        """撮影角度の間隔を更新する。"""
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
        """モーター移動後、撮影前に待つ時間を更新する。"""
        self._settling_time_ms = value
        self.settling_time_updated.emit(value)

    @Slot(bool)
    def update_return_to_start(self, value: bool) -> None:
        """走査完了後に開始位置へ戻るかどうかを更新する。"""
        self._return_to_start = value
        self.return_to_start_updated.emit(value)

    @Slot(str)
    def update_scan_direction(self, value: str) -> None:
        """走査方向を更新する。"""
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
        """現在のUI状態からモーターと角度走査サービスを作成して開始する。"""
        try:
            motor = AzdCdRotationMotor(
                MotorConnectionConfig(
                    port=self._motor_port,
                    slave=self._motor_slave,
                    position_units_per_deg=self._position_units_per_deg,
                )
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
        except ValueError as e:
            self.error_occurred.emit(str(e))
            self.angle_scan_finished.emit(False, "")
            return
        except RuntimeError as e:
            self.error_occurred.emit(str(e))
            self.angle_scan_finished.emit(False, "")
            return

        try:
            self._angle_scan_service = AngleScanService(
                self._camera,
                self._storage,
                motor,
                self._expo_list,
                self._gain_list,
                settings,
            )
        except ValueError as e:
            self.error_occurred.emit(str(e))
            self.angle_scan_finished.emit(False, "")
            return

        self._connect_angle_scan_service(self._angle_scan_service)
        self._angle_scan_service.start()

    def _connect_angle_scan_service(self, service: AngleScanService) -> None:
        """サービスの通知をViewModelの信号へ中継する。"""
        service.progress_update.connect(self.progress_updated)
        service.scan_finished.connect(self.angle_scan_finished)
        service.error_occurred.connect(self.error_occurred)
        service.preview_resume_requested.connect(self.preview_resume_requested)
        service.preview_pause_requested.connect(self.preview_pause_requested)

    @Slot()
    def notify_preview_paused(self) -> None:
        """PreviewWorkerの停止完了を、待機中の角度走査サービスへ伝える。"""
        if self._angle_scan_service:
            self._angle_scan_service.notify_preview_paused()

    @Slot()
    def cancel_angle_scan(self) -> None:
        """実行中の角度走査にキャンセルを要求する。"""
        if self.is_running() and self._angle_scan_service:
            self._angle_scan_service.cancel()

    def is_running(self) -> bool:
        """角度走査サービスが実行中かどうかを返す。"""
        return self._angle_scan_service is not None and self._angle_scan_service.isRunning()
