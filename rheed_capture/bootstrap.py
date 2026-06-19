from __future__ import annotations

from typing import TYPE_CHECKING

from rheed_capture.infrastructure.camera.basler_camera import BaslerCamera
from rheed_capture.infrastructure.motor.azd_cd.motor import (
    AzdCdRotationMotor,
    MotorConnectionConfig,
)
from rheed_capture.infrastructure.motor.mock import MockRotationMotor
from rheed_capture.infrastructure.storage.experiment_storage import ExperimentStorage
from rheed_capture.presentation.qt.main_window import MainWindow

if TYPE_CHECKING:
    from collections.abc import Callable

    from rheed_capture.application.ports.motor import RotationMotor


def create_motor_factory() -> Callable[[str, int, float], RotationMotor]:
    """ViewModelへ渡すAZD-CDモータ生成Factoryを作る。"""

    def factory(port: str, slave: int, position_units_per_deg: float) -> RotationMotor:
        """UIで確定した接続設定から具体的なモータ実装を生成する。"""
        normalized_port = port.strip().lower()
        if normalized_port in {"mock", "mock://motor"}:
            return MockRotationMotor(position_units_per_deg=position_units_per_deg)

        return AzdCdRotationMotor(
            MotorConnectionConfig(
                port=port,
                slave=slave,
                position_units_per_deg=position_units_per_deg,
            )
        )

    return factory


def create_main_window() -> MainWindow:
    """実機依存オブジェクトを組み立て、QtのMainWindowへ注入する。"""
    camera = BaslerCamera()
    camera.connect()

    storage = ExperimentStorage(root_dir="./Data_Root")
    return MainWindow(camera, storage, motor_factory=create_motor_factory())
