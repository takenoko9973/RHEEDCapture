from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

from rheed_capture.application.capture.frame_capturer import CapturedFrame, FrameCapture
from rheed_capture.application.ports.motor import DEFAULT_MOTOR_SPEED_RPM
from rheed_capture.data_formats.angle_scan_document import (
    AngleScanDocument,
    AngleScanDocumentSettings,
    CaptureExecutionSettings,
)
from rheed_capture.data_formats.angle_scan_document import (
    CaptureCondition as DocumentCaptureCondition,
)
from rheed_capture.domain.angle_scan.model import AngleScanDirection, validate_direction
from rheed_capture.domain.angle_scan.plan import (
    AngleMove,
    AngleScanPlan,
    MotorAngleCalibration,
    build_angle_scan_plan,
)
from rheed_capture.domain.capture_defaults import DEFAULT_CAPTURE_RETRY_LIMIT

if TYPE_CHECKING:
    from rheed_capture.application.capture.cancellation import CancellationToken
    from rheed_capture.application.ports.motor import RotationMotor
    from rheed_capture.application.ports.storage import AngleScanSession
    from rheed_capture.domain.capture_condition import CaptureCondition

JST = ZoneInfo("Asia/Tokyo")

AngleProgressCallback = Callable[[int, int, float], None]
FrameCallback = Callable[[CapturedFrame], None]


@dataclass(frozen=True)
class AngleScanSettings:
    """Angle Scan実行に必要な、UIや保存形式から独立した設定値。"""

    range_deg: float
    interval_deg: float
    direction: AngleScanDirection
    settling_time_ms: int
    return_to_start_after_scan: bool
    position_units_per_deg: float
    motor_speed_rpm: float = DEFAULT_MOTOR_SPEED_RPM
    motion_timeout: float = 10.0

    def __post_init__(self) -> None:
        """実行前にDomain制約として扱う設定値を検証する。"""
        validate_direction(self.direction)

        if self.motor_speed_rpm <= 0:
            msg = "モーター速度は正の値にしてください。"
            raise ValueError(msg)

        if self.settling_time_ms < 0:
            msg = "移動後待機時間は0以上にしてください。"
            raise ValueError(msg)


@dataclass(frozen=True)
class AngleScanHooks:
    """Application層から外側へ通知するためのQt非依存Hook群。"""

    on_motion_started: Callable[[], None] | None = None
    before_capture_batch: Callable[[], None] | None = None
    on_progress: AngleProgressCallback | None = None
    on_frame_captured: FrameCallback | None = None


class AngleScanCapture:
    """角度走査の移動順序、撮影順序、復帰処理だけを担当する実行クラス。"""

    def __init__(
        self,
        frame_capturer: FrameCapture,
        session: AngleScanSession,
        motor: RotationMotor,
        conditions: list[CaptureCondition],
        settings: AngleScanSettings,
    ) -> None:
        """撮影、保存、モータ操作の依存を受け取り、走査計画を確定する。"""
        self.frame_capturer = frame_capturer
        self.session = session
        self.motor = motor
        self.settings = settings

        self.calibration = MotorAngleCalibration(settings.position_units_per_deg)
        self.plan = self._build_plan(settings)
        # 呼び出し元のリスト変更が撮影中に影響しないよう、開始時点の条件をコピーする。
        self.conditions = list(conditions)
        if not self.conditions:
            # 空条件では総撮影枚数もscan.jsonの意味も成立しないため、実行前に止める。
            msg = "撮影条件がありません。"
            raise ValueError(msg)
        self.total_shots = len(self.plan.capture_angles) * len(self.conditions)
        self._current_target_units = 0

    def _build_plan(self, settings: AngleScanSettings) -> AngleScanPlan:
        """設定値からDomainの角度走査計画を構築する。"""
        return build_angle_scan_plan(
            range_deg=settings.range_deg,
            interval_deg=settings.interval_deg,
            direction=settings.direction,
            calibration=self.calibration,
        )

    def run(
        self,
        cancellation_token: CancellationToken,
        *,
        hooks: AngleScanHooks | None = None,
    ) -> None:
        """計画順にモータ移動と撮影を行い、必要なら最後に開始位置へ戻す。"""
        hooks = hooks or AngleScanHooks()
        shot_count = 0

        for move in self.plan.moves:
            cancellation_token.raise_if_cancelled()
            self._execute_move(move, hooks)

            if not move.capture:
                continue

            shot_count = self._capture_at_move(move, shot_count, cancellation_token, hooks)

        if self.settings.return_to_start_after_scan:
            self._return_to_start(hooks)

    def _execute_move(self, move: AngleMove, hooks: AngleScanHooks) -> None:
        """1つの移動指示を実行し、移動中プレビュー再開Hookを必要時だけ呼ぶ。"""
        if move.delta_units != 0:
            if hooks.on_motion_started is not None:
                hooks.on_motion_started()

            self.motor.move_relative_units(
                move.delta_units,
                self.settings.motor_speed_rpm,
                timeout=self.settings.motion_timeout,
            )

        self._current_target_units = move.target_units

    def _capture_at_move(
        self,
        move: AngleMove,
        shot_count: int,
        cancellation_token: CancellationToken,
        hooks: AngleScanHooks,
    ) -> int:
        """1つの撮影角度で全条件を撮影し、保存とRawフレーム通知を分離して行う。"""
        self._wait_settling()

        if hooks.before_capture_batch is not None:
            hooks.before_capture_batch()

        for condition in self.conditions:
            cancellation_token.raise_if_cancelled()
            shot_count += 1
            if hooks.on_progress is not None:
                hooks.on_progress(shot_count, self.total_shots, move.angle_deg)

            captured_frame = self.frame_capturer.capture(condition)
            self.session.save_frame(captured_frame, move.angle_deg)

            if hooks.on_frame_captured is not None:
                hooks.on_frame_captured(captured_frame)

        return shot_count

    def _wait_settling(self) -> None:
        """モータ移動後の機械的な落ち着き時間を待つ。"""
        if self.settings.settling_time_ms > 0:
            time.sleep(self.settings.settling_time_ms / 1000)

    def _return_to_start(self, hooks: AngleScanHooks) -> None:
        """設定されている場合、最後の目標位置から開始位置へ相対移動で戻す。"""
        if self._current_target_units == 0:
            return

        if hooks.on_motion_started is not None:
            hooks.on_motion_started()

        self.motor.move_relative_units(
            -self._current_target_units,
            self.settings.motor_speed_rpm,
            timeout=self.settings.motion_timeout,
        )
        self._current_target_units = 0

    def build_scan_document(
        self,
        *,
        retry_limit: int = DEFAULT_CAPTURE_RETRY_LIMIT,
    ) -> AngleScanDocument:
        """この実行クラスが使う計画と条件から保存用scan.jsonモデルを生成する。"""
        return build_angle_scan_document(
            settings=self.settings,
            plan=self.plan,
            conditions=self.conditions,
            retry_limit=retry_limit,
        )


def build_angle_scan_document(
    *,
    settings: AngleScanSettings,
    plan: AngleScanPlan,
    conditions: list[CaptureCondition],
    retry_limit: int = DEFAULT_CAPTURE_RETRY_LIMIT,
) -> AngleScanDocument:
    """角度走査計画と撮影条件をscan.json保存モデルへ変換する。"""
    return AngleScanDocument(
        schema_version=1,
        scan_id="",
        created_at=datetime.now(JST).isoformat(),
        angle_scan=AngleScanDocumentSettings(
            coordinate="relative",
            reference="current_position_at_scan_start",
            range_deg=settings.range_deg,
            interval_deg=settings.interval_deg,
            direction=settings.direction,
            position_units_per_deg=settings.position_units_per_deg,
            capture_angles_deg=plan.capture_angles,
            wait_after_move_ms=settings.settling_time_ms,
            motor_speed_rpm=settings.motor_speed_rpm,
            return_to_start=settings.return_to_start_after_scan,
        ),
        capture_conditions=[
            DocumentCaptureCondition(
                exposure_ms=condition.exposure_ms,
                gain=condition.gain,
            )
            for condition in conditions
        ],
        capture=CaptureExecutionSettings(retry_limit=retry_limit),
    )


def build_angle_scan_document_from_conditions(
    *,
    settings: AngleScanSettings,
    conditions: list[CaptureCondition],
    retry_limit: int = DEFAULT_CAPTURE_RETRY_LIMIT,
) -> AngleScanDocument:
    """角度計画と撮影条件からscan.jsonモデルを事前生成する。"""
    calibration = MotorAngleCalibration(settings.position_units_per_deg)
    plan = build_angle_scan_plan(
        range_deg=settings.range_deg,
        interval_deg=settings.interval_deg,
        direction=settings.direction,
        calibration=calibration,
    )

    return build_angle_scan_document(
        settings=settings,
        plan=plan,
        conditions=conditions,
        retry_limit=retry_limit,
    )
