import numpy as np
from pytestqt.qtbot import QtBot

from rheed_capture.core.camera_device import CameraDevice
from rheed_capture.core.preview_worker import PreviewWorker


class MockCamera(CameraDevice):
    """テスト用のモックカメラ (ハードウェアに依存せず一定ペースで画像を返す)"""

    def __init__(self) -> None:
        self.is_grabbing = True

    def retrieve_preview_frame(self, timeout_ms: int = 1000) -> np.ndarray | None:  # noqa: ARG002
        if not self.is_grabbing:
            return None

        # 12bitのダミーRaw画像を返す
        rng = np.random.default_rng(1234)
        return rng.integers(0, 4096, (512, 512), dtype=np.uint16)


def test_preview_worker_signals(qtbot: QtBot) -> None:
    """PreviewWorkerが別スレッドで動作し、正しく画像シグナルをエミットするかテスト"""
    mock_camera = MockCamera()
    worker = PreviewWorker(camera_device=mock_camera)

    # 処理フラグのテスト(初期状態はFalse=Rawスケーリングのみ)
    assert not worker.enable_processing

    # qtbotを使って、シグナルが発火するのを待機 (timeout 2秒)
    with qtbot.waitSignal(worker.image_ready, timeout=2000) as blocker:
        worker.start()

    # エミットされた引数(画像)を検証
    assert blocker.args is not None
    emitted_image: np.ndarray = blocker.args[0]

    assert emitted_image is not None
    assert emitted_image.dtype == np.uint8, "UI表示用に8bit化されていること"

    # ワーカーを安全に停止
    worker.stop()
    worker.wait(1000)  # スレッド終了待機
    assert not worker.isRunning()
