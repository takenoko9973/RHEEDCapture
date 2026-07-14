from unittest.mock import MagicMock

import numpy as np
import pytest
from pytestqt.qtbot import QtBot

from rheed_capture.application.ports.camera import CameraFrame, FrameReadback
from rheed_capture.domain.capture_condition import CaptureCondition
from rheed_capture.infrastructure.camera.basler_camera import CameraDevice
from rheed_capture.infrastructure.storage.experiment_storage import ExperimentStorage
from rheed_capture.presentation.qt.workers.capture_service import CaptureService


@pytest.fixture
def mock_camera() -> MagicMock:
    """カメラデバイスのモックフィクスチャ"""
    camera = MagicMock(spec=CameraDevice)

    def start_session(*, expected_frames: int | None) -> MagicMock:
        """1フレーム取得に成功するソフトトリガーSessionを返す。"""
        assert expected_frames == 1
        session = MagicMock()
        session.retrieve_frame.return_value = CameraFrame(
            image=np.zeros((10, 10), dtype=np.uint16),
            readback=FrameReadback(
                exposure_ms=10.0,
                gain=0,
                camera_timestamp_ticks=1,
                camera_timestamp_frequency_hz=125_000_000,
                source="camera",
            ),
        )
        return session

    camera.start_software_trigger_session.side_effect = start_session
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

    assert mock_camera.start_software_trigger_session.call_count == 4
    assert mock_storage.start_sequence_session.return_value.save_frame.call_count == 4


def test_capture_retry_logic(qtbot: QtBot, mock_camera: MagicMock, mock_storage: MagicMock) -> None:
    """エラー時にリトライが行われ、3回目で失敗する場合は中断されるかテスト"""
    conditions = [CaptureCondition(exposure_ms=10.0, gain=0)]

    def start_failing_session(*, expected_frames: int | None) -> MagicMock:
        """取得時に通信相当エラーを返す新しいSessionを作る。"""
        assert expected_frames == 1
        session = MagicMock()
        msg = "Mock Camera Error"
        session.retrieve_frame.side_effect = RuntimeError(msg)
        return session

    mock_camera.start_software_trigger_session.side_effect = start_failing_session

    service = CaptureService(mock_camera, mock_storage, conditions)

    with qtbot.waitSignal(service.sequence_finished, timeout=5000) as blocker:
        service.start()

    assert blocker.args is not None
    assert blocker.args[0] is False, "失敗シグナルがFalseであること"

    assert mock_camera.start_software_trigger_session.call_count == 3
    mock_storage.start_sequence_session.return_value.save_frame.assert_not_called()
