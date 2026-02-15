import numpy as np
from pytestqt.qtbot import QtBot

from rheed_capture.models.hardware.camera_device import CameraDevice
from rheed_capture.viewmodels.preview_worker import PreviewWorker


class MockCamera(CameraDevice):
    """テスト用のモックカメラ (ハードウェアに依存せず一定ペースで画像を返す)"""

    def __init__(self) -> None:
        self.is_grabbing = True

    def is_connected(self) -> bool:
        return True

    def start_preview_grab(self) -> None:
        self.is_grabbing = True

    def stop_grabbing(self) -> None:
        self.is_grabbing = False

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


def test_preview_worker_pause_resume(qtbot: QtBot) -> None:
    """シーケンス撮影時の一時停止・再開ロジックが正しく機能するかテスト"""
    mock_camera = MockCamera()
    worker = PreviewWorker(camera_device=mock_camera)

    worker.start()

    # 一時停止をリクエストし、ワーカーから完了シグナルが返ってくるのを待つ
    with qtbot.waitSignal(worker.preview_paused, timeout=2000):
        worker.request_pause()

    # 一時停止状態の検証
    assert worker._is_paused is True  # noqa: SLF001
    assert mock_camera.is_grabbing is False, "カメラの取得状態が停止していること"

    # 再開リクエスト
    worker.resume()
    assert worker._is_paused is False  # noqa: SLF001

    # ワーカーを安全に停止
    worker.stop()
    worker.wait(1000)
