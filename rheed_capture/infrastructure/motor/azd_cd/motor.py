from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from rheed_capture.application.ports.motor import DEFAULT_MOTOR_SPEED_RPM
from rheed_capture.infrastructure.motor.azd_cd import AzdCdAdapter, AzdCdConfig, CompletionMode
from rheed_capture.infrastructure.motor.defaults import (
    DEFAULT_POSITION_UNITS_PER_DEG,
)


@dataclass(frozen=True)
class MotorConnectionConfig:
    port: str
    slave: int

    baudrate: int = 115200
    parity: str = "E"
    stopbits: int = 1
    timeout: float = 1.0
    position_units_per_deg: float = DEFAULT_POSITION_UNITS_PER_DEG

    completion_mode: str = "move-ready"
    stable_reads: int = 2
    poll_interval: float = 0.05


class AzdCdRotationMotor:
    def __init__(self, config: MotorConnectionConfig) -> None:
        if not config.port.strip():
            msg = "モーターのCOMポートを入力してください。"
            raise ValueError(msg)

        self.config = config
        self._adapter = self._create_adapter(config)

    def _create_adapter(self, config: MotorConnectionConfig) -> AzdCdAdapter:
        motor_config = AzdCdConfig(
            port=config.port,
            slave=config.slave,
            baudrate=config.baudrate,
            parity=config.parity,
            stopbits=config.stopbits,
            timeout=config.timeout,
        )
        return AzdCdAdapter(
            motor_config,
            position_units_per_deg=config.position_units_per_deg,
        )

    def move_relative_units(
        self,
        position_units: int,
        motor_speed_rpm: float = DEFAULT_MOTOR_SPEED_RPM,
        *,
        timeout: float = 10.0,
    ) -> object | None:
        return self._adapter.move_relative_units(
            position_units,
            motor_speed_rpm,
            timeout=timeout,
            poll_interval=self.config.poll_interval,
            completion_mode=self._completion_mode(),
            stable_reads=self.config.stable_reads,
        )

    def _completion_mode(self) -> CompletionMode:
        if self.config.completion_mode not in {
            "move-only",
            "move-ready",
            "move-ready-in-pos",
        }:
            msg = f"未対応のモーター完了判定です: {self.config.completion_mode}"
            raise ValueError(msg)

        return cast("CompletionMode", self.config.completion_mode)
