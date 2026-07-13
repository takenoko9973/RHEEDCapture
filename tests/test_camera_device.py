import os
from typing import cast

import numpy as np
import pytest

# pypylonのロード前にエミュレータを有効化する (1台のエミュレータカメラを作成)
os.environ["PYLON_CAMEMU"] = "1"

from pypylon import genicam, pylon

from rheed_capture.application.ports.camera import CameraError
from rheed_capture.infrastructure.camera import basler_camera as basler_module
from rheed_capture.infrastructure.camera.basler_camera import CameraDevice, CameraState
from rheed_capture.infrastructure.camera.basler_configurators import (
    CAMERA_EMULATION_ROI,
    BaslerCameraEmulationSettings,
    BaslerMandatorySettings,
)


@pytest.fixture
def camera_device():  # noqa: ANN201
    """テスト用のカメラデバイスフィクスチャ"""
    dev = CameraDevice(
        configurators=[
            BaslerMandatorySettings(),
            BaslerCameraEmulationSettings(),
        ],
        exposure_timestamp_source="simulation",
    )
    dev.connect()
    yield dev
    dev.disconnect()


def test_camera_connection_and_mandatory_settings(camera_device: CameraDevice) -> None:
    """接続と強制初期化設定(Mono12等)が正しく適用されるかのテスト"""
    assert camera_device.is_connected()

    # 実際のpylonカメラオブジェクトのノードにアクセスして検証
    cam = camera_device.camera
    assert cam.PixelFormat.GetValue() == "Mono12"

    # エミュレータでサポートされている範囲で強制設定が反映されているか
    if genicam.IsWritable(cam.ExposureAuto):
        assert cam.ExposureAuto.GetValue() == "Off"


def test_camera_emulation_roi(camera_device: CameraDevice) -> None:
    """エミュレータカメラのROIがシミュレーション用サイズに設定されるかのテスト"""
    expected_width, expected_height = CAMERA_EMULATION_ROI

    assert camera_device.camera.Width.GetValue() == expected_width
    assert camera_device.camera.Height.GetValue() == expected_height


def test_camera_bounds(camera_device: CameraDevice) -> None:
    """カメラから設定可能な最小・最大値が取得できるかのテスト"""
    expo_min, expo_max = camera_device.get_exposure_bounds()
    assert isinstance(expo_min, float)
    assert isinstance(expo_max, float)
    assert expo_min < expo_max

    if genicam.IsReadable(camera_device.camera.Gain):
        gain_min, gain_max = camera_device.get_gain_bounds()
        assert isinstance(gain_min, int)
        assert isinstance(gain_max, int)
        assert gain_min < gain_max


def test_set_exposure_and_gain(camera_device: CameraDevice) -> None:
    """露光時間とゲインの設定テスト"""
    # UIからの入力として 10.5 ms を設定
    camera_device.set_exposure(10.5)
    # Baslerカメラ内部のExposureTimeノードには 10500.0 us として書き込まれている
    assert camera_device.camera.ExposureTimeAbs.GetValue() == 10500.0

    # ゲインを設定 (エミュレータが対応している場合)
    if genicam.IsWritable(camera_device.camera.Gain):
        camera_device.set_gain(400)
        assert camera_device.camera.GainRaw.GetValue() == 400


def test_emulator_captures_with_simulation_timestamp(
    camera_device: CameraDevice,
) -> None:
    """Timestamp Chunk非対応エミュレータでもシミュレーション時刻で撮影する。"""
    with camera_device.start_software_trigger_session(expected_frames=1) as session:
        session.wait_until_ready(1000)
        session.execute_trigger()
        frame = session.retrieve_frame(1000)

    assert frame.image.shape == (540, 720)
    assert frame.exposure_started_ticks > 0
    assert frame.exposure_timestamp_frequency_hz == 1_000_000_000
    assert frame.exposure_timestamp_source == "simulation"
    assert camera_device.state is CameraState.IDLE
    assert camera_device.camera.TriggerMode.GetValue() == "Off"


def test_preview_grabbing(camera_device: CameraDevice) -> None:
    """プレビュー用非同期取得(StartGrabbing)のテスト"""
    camera_device.start_preview_grab()
    assert camera_device.camera.IsGrabbing()

    with pytest.raises(CameraError, match="idle状態"):
        camera_device.set_exposure(20.0)

    with pytest.raises(CameraError, match="idle状態"):
        camera_device.start_software_trigger_session(expected_frames=1)

    # 1フレームだけ手動で取り出してみる
    grab_result = camera_device.camera.RetrieveResult(1000, pylon.TimeoutHandling_ThrowException)
    assert grab_result.GrabSucceeded()
    grab_result.Release()

    camera_device.stop_grabbing()
    assert not camera_device.camera.IsGrabbing()


def test_retrieve_preview_frame(camera_device: CameraDevice) -> None:
    """プレビュー連続取得中のフレーム取り出し(RetrieveResult)のテスト"""
    camera_device.start_preview_grab()

    # 連続してフレームが取得できるかテスト
    for _ in range(3):
        img_data = camera_device.retrieve_preview_frame(timeout_ms=1000)
        assert img_data is not None
        assert isinstance(img_data, np.ndarray)
        assert img_data.dtype == np.uint16
        assert img_data.shape == (540, 720)

    camera_device.stop_grabbing()

    # 停止中に取得しようとした場合はNoneが返ること
    assert camera_device.retrieve_preview_frame() is None


class _FakeNode:
    """Basler trigger unit test用の読み書き可能なGenICam node。"""

    def __init__(self, value: str | int) -> None:
        """初期node値を保持する。"""
        self.value = value

    def is_available(self) -> bool:
        """利用可能なnodeとして扱う。"""
        return True

    def FromString(self, value: str, verify: bool = True) -> None:  # noqa: ARG002, N802
        """GenICam文字列表現からnode値を更新する。"""
        if isinstance(self.value, int):
            self.value = int(value)
        else:
            self.value = value

    def ToString(self) -> str:  # noqa: N802
        """現在値をGenICam文字列表現で返す。"""
        return str(self.value)

    def GetValue(self) -> str | int:  # noqa: N802
        """現在値を返す。"""
        return self.value


class _FakeNodeMap:
    """node名で_FakeNodeを返す最小NodeMap。"""

    def __init__(self, nodes: dict[str, _FakeNode]) -> None:
        """node辞書を保持する。"""
        self.nodes = nodes

    def GetNode(self, name: str) -> _FakeNode | None:  # noqa: N802
        """指定名のnodeを返す。"""
        return self.nodes.get(name)


class _FakeGrabResult:
    """camera timestamp付きの成功GrabResult。"""

    def __init__(self, timestamp_ticks: int) -> None:
        """返却するcamera timestampを保持する。"""
        self.timestamp_ticks = timestamp_ticks

    def __enter__(self):  # noqa: ANN204
        """GrabResult自身を返す。"""
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:  # noqa: ANN001
        """test doubleでは解放処理を行わない。"""

    def IsValid(self) -> bool:  # noqa: N802
        """有効なGrabResultであることを返す。"""
        return True

    def GrabSucceeded(self) -> bool:  # noqa: N802
        """取得成功を返す。"""
        return True

    def GetTimeStamp(self) -> int:  # noqa: N802
        """camera timestampを返す。"""
        return self.timestamp_ticks


class _FakeInstantCamera:
    """Basler software trigger lifecycleを観測するInstantCamera test double。"""

    def __init__(self) -> None:
        """必須nodeと取得履歴を初期化する。"""
        self.nodemap = _FakeNodeMap(
            {
                "AcquisitionMode": _FakeNode("SingleFrame"),
                "TriggerSelector": _FakeNode("FrameStart"),
                "TriggerMode": _FakeNode("Off"),
                "TriggerSource": _FakeNode("Line1"),
                "GevTimestampTickFrequency": _FakeNode(125_000_000),
            }
        )
        self.start_args: tuple[object, ...] | None = None
        self.grabbing = False
        self.trigger_count = 0
        self.stop_count = 0

    def IsOpen(self) -> bool:  # noqa: N802
        """接続済みとして扱う。"""
        return True

    def GetNodeMap(self) -> _FakeNodeMap:  # noqa: N802
        """必須trigger node mapを返す。"""
        return self.nodemap

    def StartGrabbing(self, strategy: object, grab_loop_type: object) -> None:  # noqa: N802
        """無制限取得のstrategyとgrab loopを記録する。"""
        self.start_args = (strategy, grab_loop_type)
        self.grabbing = True

    def StartGrabbingMax(  # noqa: N802
        self,
        max_images: int,
        strategy: object,
        grab_loop_type: object,
    ) -> None:
        """予定枚数つき取得の上限、strategy、grab loopを記録する。"""
        self.start_args = (max_images, strategy, grab_loop_type)
        self.grabbing = True

    def IsGrabbing(self) -> bool:  # noqa: N802
        """現在の取得状態を返す。"""
        return self.grabbing

    def WaitForFrameTriggerReady(self, timeout_ms: int, handling: object) -> bool:  # noqa: ARG002, N802
        """即座にtrigger readyを返す。"""
        return True

    def ExecuteSoftwareTrigger(self) -> None:  # noqa: N802
        """software trigger発行回数を記録する。"""
        self.trigger_count += 1

    def RetrieveResult(self, timeout_ms: int, handling: object) -> _FakeGrabResult:  # noqa: ARG002, N802
        """camera timestamp付きの1フレームを返す。"""
        return _FakeGrabResult(987654)

    def StopGrabbing(self) -> None:  # noqa: N802
        """取得を停止して呼出回数を記録する。"""
        self.grabbing = False
        self.stop_count += 1


class _FakeConvertedImage:
    """Mono16変換済み画像を返すtest double。"""

    def GetArray(self) -> np.ndarray:  # noqa: N802
        """uint16画像を返す。"""
        return np.ones((2, 2), dtype=np.uint16)


class _FakeConverter:
    """ImageFormatConverterのtest double。"""

    def Convert(self, result: object) -> _FakeConvertedImage:  # noqa: ARG002, N802
        """Mono16変換済み画像を返す。"""
        return _FakeConvertedImage()


def test_software_trigger_session_uses_user_grab_loop_and_restores_state(monkeypatch) -> None:  # noqa: ANN001
    """SDK内部の取得待機を使わず1枚とtimestampを取得し、終了時に設定を復元する。"""
    monkeypatch.setattr(
        basler_module.genicam,
        "IsAvailable",
        lambda node: node is not None and node.is_available(),
    )
    monkeypatch.setattr(basler_module.genicam, "IsReadable", lambda node: node is not None)
    monkeypatch.setattr(basler_module.genicam, "IsWritable", lambda node: node is not None)
    instant_camera = _FakeInstantCamera()
    camera_device = CameraDevice()
    camera_device._camera = cast("pylon.InstantCamera", instant_camera)  # noqa: SLF001
    camera_device._state = CameraState.IDLE  # noqa: SLF001
    camera_device.converter = cast("pylon.ImageFormatConverter", _FakeConverter())

    with camera_device.start_software_trigger_session(expected_frames=1) as session:
        with pytest.raises(CameraError, match="idle状態"):
            camera_device.start_preview_grab()
        session.wait_until_ready(100)
        session.execute_trigger()
        frame = session.retrieve_frame(100)

        assert instant_camera.start_args == (
            1,
            pylon.GrabStrategy_OneByOne,
            pylon.GrabLoop_ProvidedByUser,
        )
        assert instant_camera.trigger_count == 1
        assert frame.exposure_started_ticks == 987654
        assert frame.exposure_timestamp_frequency_hz == 125_000_000
        assert frame.exposure_timestamp_source == "camera"

    assert instant_camera.stop_count == 1
    assert instant_camera.nodemap.nodes["TriggerMode"].value == "Off"
    assert camera_device.state is CameraState.IDLE
