"""
ユーザー向けの高レベルAdapter。

Adapterは、位置単位での相対移動、完了待ち、操作ごとの自動接続/切断を担当する。
低レベルのレジスタ操作やシリアル通信は `AzdCdDriver` に委譲する。
角度から位置単位への換算は、角度走査計画側の責務として扱う。
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Literal

from rheed_capture.application.ports.motor import DEFAULT_MOTOR_SPEED_RPM
from rheed_capture.infrastructure.motor.defaults import (
    DEFAULT_POSITION_UNITS_PER_DEG,
    motor_rpm_to_speed_units,
)

from .driver import AzdCdConfig, AzdCdDriver, AzdCdStatus
from .protocol import OP_RELATIVE_POSITIONING

CompletionMode = Literal["move-only", "move-ready", "move-ready-in-pos"]


@dataclass(frozen=True)
class MoveResult:
    """モーター相対移動の実行結果。"""

    target_units: int
    elapsed_seconds: float
    final_status: AzdCdStatus
    completed: bool = True


class MotionTimeoutError(TimeoutError):
    """運転開始待ち、または完了待ちがタイムアウトしたことを表す例外。"""

    def __init__(self, message: str, last_status: AzdCdStatus | None = None) -> None:
        """最後に読めた状態を保持して例外を作る。"""
        super().__init__(message)
        self.last_status = last_status


class AzdCdAdapter:
    """操作ごとに接続して閉じる、高レベル操作用Adapter。"""

    def __init__(
        self,
        config: AzdCdConfig,
        *,
        position_units_per_deg: float = DEFAULT_POSITION_UNITS_PER_DEG,
    ) -> None:
        """接続設定と装置の角度換算条件を保持する。"""
        self.config = config
        self.position_units_per_deg = position_units_per_deg

    def read_status(self) -> AzdCdStatus:
        """現在のドライバ出力状態を読む。"""
        with AzdCdDriver(self.config) as driver:
            return driver.read_status()

    def start_relative_units(
        self, position_units: int, motor_speed_rpm: float = DEFAULT_MOTOR_SPEED_RPM
    ) -> int:
        """指定位置単位の相対位置決めをrpm指定で開始し、完了待ちはしない。"""
        with AzdCdDriver(self.config) as driver:
            return self._start_relative_units(driver, position_units, motor_speed_rpm)

    def move_relative_units(
        self,
        position_units: int,
        motor_speed_rpm: float = DEFAULT_MOTOR_SPEED_RPM,
        *,
        wait: bool = True,
        timeout: float = 10.0,
        poll_interval: float = 0.05,
        completion_mode: CompletionMode = "move-ready",
        stable_reads: int = 2,
    ) -> MoveResult | None:
        """指定位置単位の相対位置決めをrpm指定で実行する。"""
        started_at = time.monotonic()

        # COMポートを長時間占有しないよう、1操作ごとに開閉する。
        with AzdCdDriver(self.config) as driver:
            moved_units = self._start_relative_units(
                driver=driver,
                position_units=position_units,
                motor_speed_rpm=motor_speed_rpm,
            )

            if not wait:
                return None

            final_status = self._wait_motion_complete(
                driver=driver,
                timeout=timeout,
                poll_interval=poll_interval,
                completion_mode=completion_mode,
                stable_reads=stable_reads,
            )

        return MoveResult(
            target_units=moved_units,
            elapsed_seconds=time.monotonic() - started_at,
            final_status=final_status,
        )

    def _start_relative_units(
        self, driver: AzdCdDriver, position_units: int, motor_speed_rpm: float
    ) -> int:
        """接続済みDriverへ相対位置決めの設定を書き込み、STARTを入れる。"""
        # Driverはレジスタ書き込みだけを知る。運転データの意味付けはAdapter側で行う。
        driver.set_operation_type(OP_RELATIVE_POSITIONING)
        driver.set_speed_units(
            motor_rpm_to_speed_units(
                motor_speed_rpm,
                position_units_per_deg=self.position_units_per_deg,
            )
        )
        driver.set_position_units(position_units)
        self._start_and_confirm(driver)

        return position_units

    def _start_and_confirm(self, driver: AzdCdDriver) -> AzdCdStatus:
        """STARTをONにし、運転開始確認後にOFFへ戻す。"""
        driver.start_on()

        try:
            return self._wait_motion_started(
                driver=driver,
                timeout=self.config.start_ack_timeout,
            )
        finally:
            # START入力をONのまま残さないため、開始確認の成否に関わらずOFFへ戻す。
            driver.start_off()

    def _wait_motion_started(self, driver: AzdCdDriver, timeout: float) -> AzdCdStatus:
        """接続済みDriverで、運転が始まったことを待つ。"""
        deadline = time.monotonic() + timeout
        last_status: AzdCdStatus | None = None

        while True:
            last_status = driver.read_status()

            # 短い移動ではMOVEを見逃す場合があるため、READYが落ちた状態も開始とみなす。
            if last_status.moving or not last_status.ready:
                return last_status

            if time.monotonic() >= deadline:
                msg = "motion did not start before timeout"
                raise MotionTimeoutError(msg, last_status)

            time.sleep(self.config.inter_frame_delay)

    def _wait_motion_complete(
        self,
        driver: AzdCdDriver,
        timeout: float = 10.0,
        poll_interval: float = 0.05,
        completion_mode: CompletionMode = "move-ready",
        stable_reads: int = 2,
    ) -> AzdCdStatus:
        """接続済みDriverで、完了条件を満たすまで状態をポーリングする。"""
        deadline = time.monotonic() + timeout
        stable_count = 0
        last_status: AzdCdStatus | None = None

        while True:
            last_status = driver.read_status()

            # ノイズや状態遷移の瞬間を避けるため、完了状態を複数回連続で確認する。
            if self._is_complete(last_status, completion_mode):
                stable_count += 1
                if stable_count >= max(1, stable_reads):
                    return last_status
            else:
                stable_count = 0

            if time.monotonic() >= deadline:
                msg = "motion did not complete before timeout"
                raise MotionTimeoutError(msg, last_status)

            time.sleep(poll_interval)

    def _is_complete(self, status: AzdCdStatus, completion_mode: CompletionMode) -> bool:
        """指定された完了モードで、現在状態が完了条件を満たすか判定する。"""
        if completion_mode == "move-only":
            return not status.moving

        if completion_mode == "move-ready":
            return not status.moving and status.ready

        if completion_mode == "move-ready-in-pos":
            return not status.moving and status.ready and status.in_pos

        msg = f"unknown completion mode: {completion_mode}"
        raise ValueError(msg)
