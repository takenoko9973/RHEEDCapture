import time

import numpy as np
from pytestqt.qtbot import QtBot

from rheed_capture.domain.acquisition_statistics import AcquisitionSample
from rheed_capture.infrastructure.camera.basler_camera import CameraDevice
from rheed_capture.presentation.qt.workers.preview_worker import PreviewWorker


class MockCamera(CameraDevice):
    """テスト用のモックカメラ (ハードウェアに依存せず一定ペースで画像を返す)"""

    def __init__(self) -> None:
        """プレビュー状態と撮影条件を初期化する。"""
        self.is_grabbing = True
        self.exposure_ms = 100.0
        self.gain = 120
        self.return_frames = True
        self._acquisition_sample: AcquisitionSample | None = None

    def is_connected(self) -> bool:
        """接続済みとして扱う。"""
        return True

    def get_exposure(self) -> float:
        """現在の露光時間を返す。"""
        return self.exposure_ms

    def get_gain(self) -> float:
        """現在のGainを返す。"""
        return self.gain

    def set_exposure(self, exposure_ms: float) -> None:
        """停止中だけ露光時間を更新する。"""
        assert not self.is_grabbing
        self.exposure_ms = exposure_ms

    def set_gain(self, gain: int) -> None:
        """停止中だけGainを更新する。"""
        assert not self.is_grabbing
        self.gain = gain

    def start_preview_grab(self) -> None:
        """プレビュー取得中の状態へ切り替える。"""
        self.is_grabbing = True

    def stop_grabbing(self) -> None:
        """プレビュー停止中の状態へ切り替える。"""
        self.is_grabbing = False

    def retrieve_preview_frame(self, timeout_ms: int = 1000) -> np.ndarray | None:  # noqa: ARG002
        """成功時だけ取得sampleと16bit画像を返す。"""
        if not self.is_grabbing or not self.return_frames:
            return None

        self._acquisition_sample = AcquisitionSample(
            timestamp=time.perf_counter(),
            payload_bytes=1000,
        )
        # 12bitのダミーRaw画像を返す
        rng = np.random.default_rng(1234)
        return rng.integers(0, 4096, (512, 512), dtype=np.uint16)

    def take_acquisition_sample(self) -> AcquisitionSample | None:
        """直前の成功フレームに対応するsampleを1回だけ返す。"""
        sample = self._acquisition_sample
        self._acquisition_sample = None
        return sample


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
    assert not mock_camera.is_grabbing


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
    assert not mock_camera.is_grabbing


def test_preview_worker_applies_settings_only_after_stopping(qtbot: QtBot) -> None:
    """プレビュー中の条件変更は所有スレッドで停止してから適用する。"""
    mock_camera = MockCamera()
    worker = PreviewWorker(camera_device=mock_camera)
    worker.start()

    worker.request_exposure(25.0)
    worker.request_gain(10)
    qtbot.waitUntil(
        lambda: mock_camera.exposure_ms == 25.0 and mock_camera.gain == 10,
        timeout=2000,
    )

    worker.stop()
    worker.wait(1000)

    assert not mock_camera.is_grabbing


def test_preview_statistics_count_successful_frames_and_reset_on_pause(
    qtbot: QtBot,
) -> None:
    """成功フレームだけを計上し、pauseとresumeで統計を初期化する。"""
    mock_camera = MockCamera()
    worker = PreviewWorker(camera_device=mock_camera)
    worker.start()

    def has_multiple_frames() -> bool:
        """複数フレームが取得されるまで待機する。"""
        statistics = worker.statistics_snapshot()
        return statistics is not None and statistics.frame_count >= 2

    qtbot.waitUntil(has_multiple_frames, timeout=2000)

    statistics = worker.statistics_snapshot()
    assert statistics is not None
    assert statistics.current_fps is not None
    assert statistics.average_fps is None

    with qtbot.waitSignal(worker.preview_paused, timeout=2000):
        worker.request_pause()
    assert worker.statistics_snapshot() is None

    # 失敗結果だけの再開では、以前の成功フレームを持ち越さない。
    mock_camera.return_frames = False
    worker.resume()
    resumed_statistics = worker.statistics_snapshot()
    assert resumed_statistics is not None
    assert resumed_statistics.frame_count == 0
    assert resumed_statistics.current_fps is None

    worker.stop()
    worker.wait(1000)
    assert worker.statistics_snapshot() is None
