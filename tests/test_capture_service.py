from unittest.mock import MagicMock

import numpy as np
import pytest
from pytestqt.qtbot import QtBot

from rheed_capture.core.camera_device import CameraDevice
from rheed_capture.core.capture_service import CaptureService
from rheed_capture.core.storage import ExperimentStorage


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
    return MagicMock(spec=ExperimentStorage)


def test_successful_capture_sequence(
    qtbot: QtBot, mock_camera: MagicMock, mock_storage: MagicMock
) -> None:
    """正常な撮影シーケンスが仕様通りに実行されるかテスト"""
    exposure_list = [10.0, 100.0]
    gain_list = [0.0, 1.0]

    service = CaptureService(mock_camera, mock_storage, exposure_list, gain_list)

    with qtbot.waitSignal(service.sequence_finished, timeout=5000) as blocker:
        service.start()

    assert blocker.args is not None
    assert blocker.args[0] is True, "成功シグナルがTrueであること"

    # 呼び出し回数の検証
    mock_camera.stop_grabbing.assert_called_once()  # プレビュー停止シグナル
    mock_storage.start_new_sequence.assert_called_once()  # シーケンス開始シグナル

    assert mock_camera.grab_one.call_count == 4  # 2条件 * 2条件
    assert mock_storage.save_frame.call_count == 4  # 保存が4回呼ばれたか

    # 最後にプレビューが再開されたか
    mock_camera.start_preview_grab.assert_called_once()


def test_capture_retry_logic(qtbot: QtBot, mock_camera: MagicMock, mock_storage: MagicMock) -> None:
    """エラー時にリトライが行われ、3回目で失敗する場合は中断されるかテスト"""
    exposure_list = [10.0]
    gain_list = [0.0]

    # grab_one が常に例外を投げるように設定
    mock_camera.grab_one.side_effect = RuntimeError("Mock Camera Error")

    service = CaptureService(mock_camera, mock_storage, exposure_list, gain_list)

    with qtbot.waitSignal(service.sequence_finished, timeout=5000) as blocker:
        service.start()

    assert blocker.args is not None
    assert blocker.args[0] is False, "失敗シグナルがFalseであること"

    assert mock_camera.grab_one.call_count == 3  # 最大3回リトライ
    mock_storage.save_frame.assert_not_called()  # 保存は呼ばれない
