from __future__ import annotations

import itertools
import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Never
from zoneinfo import ZoneInfo

from pypylon import pylon
from PySide6.QtCore import QObject, QThread, Signal, Slot

from rheed_capture.models.domain.angle_scan import AngleScanDirection, validate_direction
from rheed_capture.models.hardware.motor_defaults import (
    DEFAULT_MOTOR_SPEED_RPM,
    DEFAULT_POSITION_UNITS_PER_DEG,
)
from rheed_capture.models.io.frame_metadata import AngleScanFrameMetadata
from rheed_capture.models.io.scan_document import (
    AngleScanDocument,
    AngleScanDocumentSettings,
    CaptureCondition,
    CaptureExecutionSettings,
)
from rheed_capture.services.angle_scan_plan import (
    AngleMove,
    AngleScanPlan,
    MotorAngleCalibration,
    build_angle_scan_plan,
)

if TYPE_CHECKING:
    from rheed_capture.models.hardware.camera_device import CameraDevice
    from rheed_capture.models.hardware.rotation_motor import RotationMotor
    from rheed_capture.models.io.storage import ExperimentStorage

logger = logging.getLogger(__name__)
JST = ZoneInfo("Asia/Tokyo")


@dataclass(frozen=True)
class AngleScanSettings:
    """角度走査1回分の実行設定。"""

    range_deg: float
    interval_deg: float
    direction: AngleScanDirection
    settling_time_ms: int
    return_to_start_after_scan: bool
    motor_speed_rpm: float = DEFAULT_MOTOR_SPEED_RPM
    motion_timeout: float = 10.0
    position_units_per_deg: float = DEFAULT_POSITION_UNITS_PER_DEG
    preview_pause_timeout: float = 5.0

    def __post_init__(self) -> None:
        validate_direction(self.direction)

        if self.motor_speed_rpm <= 0:
            msg = "モーター速度は正の値にしてください。"
            raise ValueError(msg)

        if self.settling_time_ms < 0:
            msg = "移動後待機時間は0以上にしてください。"
            raise ValueError(msg)


class AngleScanService(QThread):
    """計画済みの角度走査を、モーター移動と画像保存として実行する。"""

    progress_update = Signal(int, int, float)
    scan_finished = Signal(bool, str)
    error_occurred = Signal(str)
    preview_resume_requested = Signal()
    preview_pause_requested = Signal()

    def __init__(
        self,
        camera_device: CameraDevice,
        storage: ExperimentStorage,
        motor: RotationMotor,
        exposure_list: list[float],
        gain_list: list[int],
        settings: AngleScanSettings,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.camera = camera_device
        self.storage = storage
        self.motor = motor
        self.settings = settings

        # 角度列と丸め補正済みの移動量は、撮影開始前に確定させる。
        self.calibration = MotorAngleCalibration(settings.position_units_per_deg)
        self.plan = self._build_plan(settings)

        # 露光とゲインは既存の通常撮影と同じく、全組み合わせを撮影する。
        self.conditions = list(itertools.product(sorted(exposure_list), sorted(gain_list)))
        self.total_shots = len(self.plan.capture_angles) * len(self.conditions)

        self.max_retries = 3
        self._is_cancelled = False
        self._scan_id = ""
        self._current_target_units = 0
        self._preview_pause_event = threading.Event()

    def _build_plan(self, settings: AngleScanSettings) -> AngleScanPlan:
        """設定値から、サービスが順に実行する走査計画を作る。"""
        return build_angle_scan_plan(
            range_deg=settings.range_deg,
            interval_deg=settings.interval_deg,
            direction=settings.direction,
            calibration=self.calibration,
        )

    def run(self) -> None:
        success = False
        saved_dir_name = ""

        try:
            logger.info("角度走査撮影を開始します...")

            scan_document = self._build_scan_document()
            self._scan_id, scan_dir = self.storage.start_new_angle_scan(scan_document)
            saved_dir_name = scan_dir.name

            self._execute_scan_plan()

            success = True
            logger.info("角度走査撮影が正常に完了しました。")

        except InterruptedError as e:
            logger.warning(str(e))
            self.error_occurred.emit(str(e))

        except (
            pylon.GenericException,
            RuntimeError,
            TimeoutError,
            ValueError,
            FileExistsError,
        ) as e:
            logger.exception("角度走査中断")
            self.error_occurred.emit(str(e))

        finally:
            self.scan_finished.emit(success, saved_dir_name)

    def _execute_scan_plan(self) -> None:
        """走査計画に従って、移動、待機、撮影を順に実行する。"""
        shot_count = 0

        for move in self.plan.moves:
            self._check_cancelled()
            self._execute_move(move)

            # both走査の2本目に入る前の0deg戻りは、内部移動なので撮影しない。
            if not move.capture:
                continue

            shot_count = self._capture_at_move(move, shot_count)

        if self.settings.return_to_start_after_scan:
            self._return_to_start()

    def _capture_at_move(self, move: AngleMove, shot_count: int) -> int:
        """1つの撮影角度で、露光時間とゲインの全組み合わせを撮影する。"""
        self._wait_settling()
        self._pause_preview_before_capture()

        for expo_ms, gain in self.conditions:
            self._check_cancelled()
            shot_count += 1
            self.progress_update.emit(shot_count, self.total_shots, move.angle_deg)
            self._capture_with_retry(move.angle_deg, expo_ms, gain)

        return shot_count

    def _build_scan_document(self) -> AngleScanDocument:
        """解析側が撮影順を再現できるscan.jsonを作る。"""
        return AngleScanDocument(
            schema_version=1,
            scan_id="",
            created_at=datetime.now(JST).isoformat(),
            angle_scan=AngleScanDocumentSettings(
                coordinate="relative",
                reference="current_position_at_scan_start",
                range_deg=self.settings.range_deg,
                interval_deg=self.settings.interval_deg,
                direction=self.settings.direction,
                position_units_per_deg=self.settings.position_units_per_deg,
                capture_angles_deg=self.plan.capture_angles,
                wait_after_move_ms=self.settings.settling_time_ms,
                motor_speed_rpm=self.settings.motor_speed_rpm,
                return_to_start=self.settings.return_to_start_after_scan,
            ),
            capture_conditions=[
                CaptureCondition(exposure_ms=exposure, gain=gain)
                for exposure, gain in self.conditions
            ],
            capture=CaptureExecutionSettings(retry_limit=self.max_retries),
        )

    def _execute_move(self, move: AngleMove) -> None:
        """計画済みのdelta unitだけモーターを動かす。"""
        if move.delta_units != 0:
            # モーターが動いている間だけプレビューを再開し、回転中の様子を見えるようにする。
            self.preview_resume_requested.emit()

            self.motor.move_relative_units(
                move.delta_units,
                self.settings.motor_speed_rpm,
                timeout=self.settings.motion_timeout,
            )

        self._current_target_units = move.target_units

    def _pause_preview_before_capture(self) -> None:
        """撮影前にプレビュー停止を要求し、カメラが空くまで待つ。"""
        self._preview_pause_event.clear()
        self.preview_pause_requested.emit()

        if self._preview_pause_event.wait(self.settings.preview_pause_timeout):
            return

        msg = "撮影前にプレビューを停止できませんでした。"
        raise TimeoutError(msg)

    @Slot()
    def notify_preview_paused(self) -> None:
        """PreviewWorkerからの停止完了通知を角度走査スレッドへ渡す。"""
        self._preview_pause_event.set()

    def _wait_settling(self) -> None:
        if self.settings.settling_time_ms > 0:
            time.sleep(self.settings.settling_time_ms / 1000)

    def _return_to_start(self) -> None:
        """走査開始時の相対0degへ戻す。"""
        if self._current_target_units == 0:
            return

        # 開始位置へ戻る移動も、ユーザーが見えるようにプレビューを再開する。
        self.preview_resume_requested.emit()

        self.motor.move_relative_units(
            -self._current_target_units,
            self.settings.motor_speed_rpm,
            timeout=self.settings.motion_timeout,
        )
        self._current_target_units = 0

    def _capture_with_retry(self, target_angle_deg: float, expo_ms: float, gain: int) -> None:
        last_error = None

        for attempt in range(1, self.max_retries + 1):
            try:
                self._execute_single_capture(target_angle_deg, expo_ms, gain)
                return
            except (pylon.GenericException, RuntimeError, TimeoutError) as e:
                logger.warning(
                    "角度走査撮影エラー (Attempt %d/%d): %s", attempt, self.max_retries, e
                )
                last_error = e
                time.sleep(0.5)

        self._raise_max_retry_error(target_angle_deg, expo_ms, gain, last_error)

    def _execute_single_capture(self, target_angle_deg: float, expo_ms: float, gain: int) -> None:
        timeout_ms = int(expo_ms + 500)

        self.camera.set_exposure(expo_ms)
        self.camera.set_gain(gain)

        raw_data = self.camera.grab_one(timeout_ms)
        if raw_data is None:
            self._raise_grab_none_error()

        metadata = AngleScanFrameMetadata(
            scan_id=self._scan_id,
            target_angle_deg=target_angle_deg,
            exposure_ms=expo_ms,
            gain=gain,
            timestamp=datetime.now(JST).isoformat(),
        )
        self.storage.save_angle_scan_frame(
            raw_data,
            self._scan_id,
            target_angle_deg,
            expo_ms,
            gain,
            metadata.to_dict(),
        )

    def _raise_max_retry_error(
        self, target_angle_deg: float, expo_ms: float, gain: int, error: Exception | None
    ) -> Never:
        msg = (
            f"最大リトライ回数に達しました。角度={target_angle_deg}deg, "
            f"露光={expo_ms}ms, ゲイン={gain}"
        )
        if error:
            raise RuntimeError(msg) from error

        raise RuntimeError(msg)

    def _raise_grab_none_error(self) -> Never:
        msg = "画像データがNoneとして返されました。"
        raise RuntimeError(msg)

    def _check_cancelled(self) -> None:
        if self._is_cancelled:
            msg = "ユーザーによって角度走査撮影がキャンセルされました。"
            raise InterruptedError(msg)

    def cancel(self) -> None:
        self._is_cancelled = True
