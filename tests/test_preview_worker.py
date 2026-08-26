import threading
import time
from collections import deque
from typing import TYPE_CHECKING, cast

import numpy as np
from pytestqt.qtbot import QtBot

from rheed_capture.application.ports.camera import CameraFrame, FrameReadback
from rheed_capture.domain.acquisition_statistics import AcquisitionSample
from rheed_capture.infrastructure.config.schema import AcquisitionSettings
from rheed_capture.presentation.qt.workers.preview_worker import PreviewWorker

if TYPE_CHECKING:
    from rheed_capture.infrastructure.camera import basler_camera


def _frame(value: int) -> CameraFrame:
    """指定値の1画素Raw frameを作る。"""
    return CameraFrame(
        image=np.array([[value]], dtype=np.uint16),
        readback=FrameReadback(
            exposure_ms=1.0,
            gain=0,
            camera_timestamp_ticks=0,
            camera_timestamp_frequency_hz=1,
            source="simulation",
        ),
    )


class FakeSession:
    """PreviewのTrigger Sessionを呼出順とthread ID付きで記録する。"""

    def __init__(
        self,
        responses: list[CameraFrame | TimeoutError],
        *,
        default_response: CameraFrame | TimeoutError | None = None,
    ) -> None:
        """取得応答列と、列消費後の既定応答を保持する。"""
        self.responses = deque(responses)
        self.default_response = default_response
        self.calls: list[tuple[str, int]] = []
        self.closed = False
        self.close_thread_id: int | None = None
        self._software_ready = True

    def wait_until_ready(self, timeout_ms: int) -> None:
        """Software ready待機の呼出を記録する。"""
        self.calls.append((f"wait:{timeout_ms}", threading.get_ident()))
        if not self._software_ready:
            raise TimeoutError

    def execute_software_trigger(self) -> None:
        """Software triggerの呼出を記録する。"""
        self.calls.append(("execute", threading.get_ident()))

    def retrieve_frame(self, timeout_ms: int) -> CameraFrame:
        """応答列からframeまたはtimeoutを返す。"""
        self.calls.append((f"retrieve:{timeout_ms}", threading.get_ident()))
        response = (
            self.responses.popleft()
            if self.responses
            else self.default_response
        )
        if isinstance(response, TimeoutError):
            raise response
        if response is None:
            raise TimeoutError
        self._software_ready = False
        return response

    def close(self) -> None:
        """closeの呼出と所有threadを記録する。"""
        self.calls.append(("close", threading.get_ident()))
        self.closed = True
        self.close_thread_id = threading.get_ident()


class FakeCamera:
    """Trigger Sessionを生成し、露光・Gain設定順を検証できるfake camera。"""

    def __init__(self, sessions: list[FakeSession]) -> None:
        """指定Sessionを開始順に返すcameraを作る。"""
        self.sessions = deque(sessions)
        self.started_sessions: list[tuple[object, FakeSession]] = []
        self.active_session: FakeSession | None = None
        self.exposure_ms = 50.0
        self.gain = 0
        self._sample: AcquisitionSample | None = None

    def start_trigger_session(
        self,
        *,
        settings: object,
        expected_frames: int | None,
    ) -> FakeSession:
        """Session開始条件を記録し、次のfake Sessionを返す。"""
        assert expected_frames is None
        session = self.sessions.popleft()
        self.started_sessions.append((settings, session))
        self.active_session = session
        return session

    def set_exposure(self, exposure_ms: float) -> None:
        """Session close後に露光時間を更新する。"""
        assert self.active_session is None or self.active_session.closed
        self.exposure_ms = exposure_ms

    def set_gain(self, gain: int) -> None:
        """Session close後にGainを更新する。"""
        assert self.active_session is None or self.active_session.closed
        self.gain = gain

    def take_acquisition_sample(self) -> AcquisitionSample:
        """直前Rawに対応するsimulation sampleを返す。"""
        if self._sample is None:
            self._sample = AcquisitionSample(time.perf_counter(), 1000)
        sample = self._sample
        self._sample = None
        return sample


def _start_worker(worker: PreviewWorker) -> None:
    """workerを開始する。"""
    worker.start()


def _stop_worker(worker: PreviewWorker) -> None:
    """workerへ停止要求を送り、所有threadの終了を待つ。"""
    worker.stop()
    assert worker.wait(1000)


def _as_camera_device(
    camera: FakeCamera,
) -> "basler_camera.CameraDevice":
    """部分実装のfakeをPreviewWorkerの実機型として扱う。"""
    return cast("basler_camera.CameraDevice", camera)


def _is_waiting_for_trigger(worker: PreviewWorker) -> bool:
    """Preview統計がHardware trigger待機中か返す。"""
    statistics = worker.statistics_snapshot()
    return statistics is not None and statistics.waiting_for_trigger


def _has_frame_count(worker: PreviewWorker, minimum: int) -> bool:
    """Preview統計のRaw frame数が指定値以上か返す。"""
    statistics = worker.statistics_snapshot()
    return statistics is not None and statistics.frame_count >= minimum


def test_preview_worker_software_trigger_call_order_and_count(qtbot: QtBot) -> None:
    """Software PreviewはRawごとにready、execute、retrieveを順に呼ぶ。"""
    session = FakeSession([_frame(100)], default_response=TimeoutError())
    camera = FakeCamera([session])
    worker = PreviewWorker(_as_camera_device(camera))

    with qtbot.waitSignal(worker.image_ready, timeout=2000):
        _start_worker(worker)
    _stop_worker(worker)

    names = [name.split(":", 1)[0] for name, _thread_id in session.calls]
    assert names[:3] == ["wait", "execute", "retrieve"]
    assert names.count("execute") == 1
    assert names.count("retrieve") == 1
    assert session.close_thread_id == session.calls[-1][1]


def test_preview_worker_hardware_no_trigger_is_waiting_without_error(
    qtbot: QtBot,
) -> None:
    """Hardware無信号はErrorにせずwaiting状態とRaw count 0を保持する。"""
    session = FakeSession([], default_response=TimeoutError())
    camera = FakeCamera([session])
    worker = PreviewWorker(_as_camera_device(camera))
    worker.set_acquisition_settings(AcquisitionSettings(mode="hardware"))
    errors: list[str] = []
    worker.error_occurred.connect(errors.append)

    _start_worker(worker)
    qtbot.waitUntil(lambda: _is_waiting_for_trigger(worker), timeout=2000)
    statistics = worker.statistics_snapshot()
    _stop_worker(worker)

    assert statistics is not None
    assert statistics.frame_count == 0
    assert statistics.waiting_for_trigger is True
    assert errors == []
    assert all(name.split(":", 1)[0] != "execute" for name, _ in session.calls)


def test_preview_worker_hardware_frame_increments_raw_count(qtbot: QtBot) -> None:
    """Hardware frame到着時だけRaw countが増え、Software triggerを呼ばない。"""
    session = FakeSession([TimeoutError(), _frame(100)], default_response=TimeoutError())
    camera = FakeCamera([session])
    worker = PreviewWorker(_as_camera_device(camera))
    worker.set_acquisition_settings(AcquisitionSettings(mode="hardware"))

    _start_worker(worker)
    qtbot.waitUntil(lambda: _has_frame_count(worker, 1), timeout=2000)
    statistics = worker.statistics_snapshot()
    _stop_worker(worker)

    assert statistics is not None
    assert statistics.waiting_for_trigger in (False, True)
    assert all(name.split(":", 1)[0] != "execute" for name, _ in session.calls)


def test_preview_worker_accumulation_clips_without_wraparound(qtbot: QtBot) -> None:
    """40000+40000の積算はuint16 wrapせず65535へclipする。"""
    session = FakeSession(
        [_frame(40_000), _frame(40_000)],
        default_response=TimeoutError(),
    )
    camera = FakeCamera([session])
    worker = PreviewWorker(_as_camera_device(camera))
    worker.set_acquisition_settings(
        AcquisitionSettings(
            mode="hardware",
            accumulation_enabled=True,
            accumulation_frames=2,
        )
    )

    with qtbot.waitSignal(worker.raw_frame_ready, timeout=2000) as blocker:
        _start_worker(worker)
    _stop_worker(worker)

    assert blocker.args is not None
    accumulated = blocker.args[0]
    assert accumulated.dtype == np.uint16
    assert accumulated.item() == 65_535


def test_preview_worker_keeps_previous_image_until_accumulation_complete(
    qtbot: QtBot,
) -> None:
    """N枚未満ではPreview signalを出さず、完成時だけ新画像を通知する。"""
    session = FakeSession(
        [_frame(100), _frame(200), _frame(300)],
        default_response=TimeoutError(),
    )
    camera = FakeCamera([session])
    worker = PreviewWorker(_as_camera_device(camera))
    worker.set_acquisition_settings(
        AcquisitionSettings(
            mode="hardware",
            accumulation_enabled=True,
            accumulation_frames=2,
        )
    )
    emitted: list[np.ndarray] = []
    worker.raw_frame_ready.connect(emitted.append)

    _start_worker(worker)
    qtbot.waitUntil(lambda: _has_frame_count(worker, 3), timeout=2000)
    qtbot.wait(50)
    _stop_worker(worker)

    assert len(emitted) == 1
    assert emitted[0].item() == 300


def test_preview_worker_rearms_with_new_acquisition_settings(qtbot: QtBot) -> None:
    """Acquisition変更は旧Session close後に新設定でPreviewを再armする。"""
    first_session = FakeSession([], default_response=TimeoutError())
    second_session = FakeSession([], default_response=TimeoutError())
    camera = FakeCamera([first_session, second_session])
    worker = PreviewWorker(_as_camera_device(camera))
    _start_worker(worker)
    qtbot.waitUntil(lambda: len(camera.started_sessions) == 1, timeout=2000)

    new_settings = AcquisitionSettings(mode="hardware", accumulation_frames=3)
    worker.set_acquisition_settings(new_settings)
    qtbot.waitUntil(lambda: len(camera.started_sessions) == 2, timeout=2000)
    _stop_worker(worker)

    assert first_session.closed
    assert camera.started_sessions[1][0] == new_settings.to_trigger_settings()
    assert second_session.closed


def test_preview_worker_pause_resume_closes_and_reopens_session(qtbot: QtBot) -> None:
    """既存pause/resume契約をTrigger Session close/reopenで維持する。"""
    first_session = FakeSession([], default_response=TimeoutError())
    second_session = FakeSession([], default_response=TimeoutError())
    camera = FakeCamera([first_session, second_session])
    worker = PreviewWorker(_as_camera_device(camera))
    _start_worker(worker)
    qtbot.waitUntil(lambda: len(camera.started_sessions) == 1, timeout=2000)

    with qtbot.waitSignal(worker.preview_paused, timeout=2000):
        worker.request_pause()
    assert worker._is_paused is True  # noqa: SLF001
    assert first_session.closed

    worker.resume()
    qtbot.waitUntil(lambda: len(camera.started_sessions) == 2, timeout=2000)
    assert worker._is_paused is False  # noqa: SLF001
    _stop_worker(worker)
    assert second_session.closed


def test_preview_worker_applies_exposure_and_gain_after_session_close(
    qtbot: QtBot,
) -> None:
    """露光とGainは旧Session close後にworker threadで適用する。"""
    session = FakeSession([], default_response=TimeoutError())
    rearmed_session = FakeSession([], default_response=TimeoutError())
    camera = FakeCamera([session, rearmed_session])
    worker = PreviewWorker(_as_camera_device(camera))
    _start_worker(worker)
    qtbot.waitUntil(lambda: len(camera.started_sessions) == 1, timeout=2000)

    worker.request_exposure(25.0)
    worker.request_gain(10)
    qtbot.waitUntil(lambda: camera.exposure_ms == 25.0 and camera.gain == 10, timeout=2000)
    _stop_worker(worker)

    assert session.closed
    assert camera.exposure_ms == 25.0
    assert camera.gain == 10
