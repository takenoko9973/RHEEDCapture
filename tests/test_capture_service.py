from unittest.mock import MagicMock

import numpy as np
import pytest
from pytestqt.qtbot import QtBot

from rheed_capture.domain.capture_condition import CaptureCondition
from rheed_capture.infrastructure.camera.basler_camera import CameraDevice
from rheed_capture.infrastructure.storage.experiment_storage import ExperimentStorage
from rheed_capture.presentation.qt.workers.capture_service import CaptureService


@pytest.fixture
def mock_camera() -> MagicMock:
    """カメラデバイスのモックフィクスチャ"""
    camera = MagicMock(spec=CameraDevice)
    # grab_oneが呼ばれたらダミー画像を返すように設定
    camera.grab_one.return_value = np.zeros((10, 10), dtype=np.uint16)
    return camera


@pytest.fixture
def mock_storage() -> MagicMock:
    """ストレージ管理のモックフィクスチャ"""
    storage = MagicMock(spec=ExperimentStorage)
    storage.start_sequence_session.return_value.dir_name = "image_001"
    return storage


def test_successful_capture_sequence(
    qtbot: QtBot, mock_camera: MagicMock, mock_storage: MagicMock
) -> None:
    """正常な撮影シーケンスが仕様通りに実行されるかテスト"""
    conditions = [
        CaptureCondition(exposure_ms=10.0, gain=0),
        CaptureCondition(exposure_ms=10.0, gain=1),
        CaptureCondition(exposure_ms=100.0, gain=0),
        CaptureCondition(exposure_ms=100.0, gain=1),
    ]

    service = CaptureService(mock_camera, mock_storage, conditions)

    with qtbot.waitSignal(service.sequence_finished, timeout=5000) as blocker:
        service.start()

    assert blocker.args is not None
    assert blocker.args[0] is True, "成功シグナルがTrueであること"

    # 呼び出し回数の検証
    mock_storage.start_sequence_session.assert_called_once()

    assert mock_camera.grab_one.call_count == 4  # 2条件 * 2条件
    assert mock_storage.start_sequence_session.return_value.save_frame.call_count == 4


def test_capture_retry_logic(qtbot: QtBot, mock_camera: MagicMock, mock_storage: MagicMock) -> None:
    """エラー時にリトライが行われ、3回目で失敗する場合は中断されるかテスト"""
    conditions = [CaptureCondition(exposure_ms=10.0, gain=0)]

    # grab_one が常に例外を投げるように設定
    mock_camera.grab_one.side_effect = RuntimeError("Mock Camera Error")

    service = CaptureService(mock_camera, mock_storage, conditions)

    with qtbot.waitSignal(service.sequence_finished, timeout=5000) as blocker:
        service.start()

    assert blocker.args is not None
    assert blocker.args[0] is False, "失敗シグナルがFalseであること"

    assert mock_camera.grab_one.call_count == 3  # 最大3回リトライ
    mock_storage.start_sequence_session.return_value.save_frame.assert_not_called()
