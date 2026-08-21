import os
from typing import cast
from unittest.mock import MagicMock

import numpy as np
import pytest

# pypylonのロード前にエミュレータを有効化する (1台のエミュレータカメラを作成)
os.environ["PYLON_CAMEMU"] = "1"

from pypylon import genicam, pylon

from rheed_capture.application.ports.camera import CameraError, TriggerSettings
from rheed_capture.infrastructure.camera import basler_camera as basler_module
from rheed_capture.infrastructure.camera import basler_frame_readback as readback_module
from rheed_capture.infrastructure.camera.basler_camera import CameraDevice, CameraState
from rheed_capture.infrastructure.camera.basler_configurators import (
    CAMERA_EMULATION_ROI,
    BaslerMandatorySettings,
)
from rheed_capture.infrastructure.camera.basler_frame_readback import (
    ChunkFrameReadbackProvider,
    SimulationFrameReadbackProvider,
)

SOFTWARE_TRIGGER_SETTINGS = TriggerSettings(
    mode="software",
    hardware_source="Line1",
    hardware_activation="RisingEdge",
    hardware_delay_us=0.0,
    fps_limit=None,
)


class _PixelFormatNode:
    """PixelFormat必須設定テスト用のnode double。"""

    def __init__(
        self,
        value: str = "Mono8",
        *,
        available: bool = True,
        writable: bool = True,
        readable: bool = True,
        write_error: Exception | None = None,
        update_value: bool = True,
    ) -> None:
        """node状態と書込み時の任意エラーを保持する。"""
        self.value = value
        self.available = available
        self.writable = writable
        self.readable = readable
        self.write_error = write_error
        self.update_value = update_value

    def FromString(self, value: str, verify: bool = True) -> None:  # noqa: ARG002, N802
        """PixelFormatの書込み値を記録する。"""
        if self.write_error is not None:
            raise self.write_error
        if self.update_value:
            self.value = value

    def ToString(self) -> str:  # noqa: N802
        """PixelFormatの読戻し値を返す。"""
        return self.value


class _PixelFormatNodeMap:
    """PixelFormatだけを返すnode map double。"""

    def __init__(self, node: _PixelFormatNode | None) -> None:
        """テスト対象のPixelFormat nodeを保持する。"""
        self.node = node

    def GetNode(self, name: str) -> _PixelFormatNode | None:  # noqa: N802
        """PixelFormat以外のnodeを未実装として返す。"""
        return self.node if name == "PixelFormat" else None


def _make_pixel_format_camera(
    device_class: str,
    node: _PixelFormatNode | None,
) -> MagicMock:
    """PixelFormat設定検証に必要な最小camera doubleを作る。"""
    camera = MagicMock()
    camera.GetDeviceInfo().GetDeviceClass.return_value = device_class
    camera.GetNodeMap.return_value = _PixelFormatNodeMap(node)
    return camera


@pytest.fixture
def camera_device():  # noqa: ANN201
    """テスト用のカメラデバイスフィクスチャ"""
    dev = CameraDevice(
        configurators=[BaslerMandatorySettings()],
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


def test_camera_connection_failure_closes_open_camera(monkeypatch) -> None:  # noqa: ANN001
    """Open後の初期化失敗時はカメラを閉じて未接続状態へ戻す。"""
    factory = MagicMock()
    factory.EnumerateDevices.return_value = [object()]
    factory.CreateFirstDevice.return_value = object()
    factory_type = MagicMock()
    factory_type.GetInstance.return_value = factory

    instant_camera = MagicMock()
    instant_camera.IsOpen.return_value = True
    device_info = instant_camera.GetDeviceInfo.return_value
    device_info.GetDeviceClass.return_value = "BaslerGigE"

    configurator = MagicMock()
    configurator.apply.side_effect = basler_module.GenericException("initialization failed")
    monkeypatch.setattr(basler_module, "TlFactory", factory_type)
    monkeypatch.setattr(basler_module, "InstantCamera", MagicMock(return_value=instant_camera))
    camera_device = CameraDevice(configurators=[configurator])

    with pytest.raises(CameraError, match="接続に失敗"):
        camera_device.connect()

    instant_camera.Close.assert_called_once_with()
    assert not camera_device.is_connected()
    assert camera_device.state is CameraState.DISCONNECTED


@pytest.mark.parametrize(
    ("device_class", "expected_pixel_format"),
    [
        ("BaslerCamEmu", "Mono12"),
        ("BaslerGigE", "Mono12Packed"),
    ],
)
def test_mandatory_settings_select_pixel_format_by_device_class(
    monkeypatch: pytest.MonkeyPatch,
    device_class: str,
    expected_pixel_format: str,
) -> None:
    """DeviceClassに応じた必須PixelFormatを設定する。"""
    node = _PixelFormatNode()
    camera = _make_pixel_format_camera(device_class, node)
    monkeypatch.setattr(genicam, "IsAvailable", lambda value: value.available)
    monkeypatch.setattr(genicam, "IsWritable", lambda value: value.writable)
    monkeypatch.setattr(genicam, "IsReadable", lambda value: value.readable)

    BaslerMandatorySettings().apply(camera)

    assert node.value == expected_pixel_format


@pytest.mark.parametrize(
    ("node", "message"),
    [
        (None, "存在しません"),
        (_PixelFormatNode(available=False), "利用できません"),
        (_PixelFormatNode(writable=False), "書き込みできません"),
    ],
)
def test_mandatory_pixel_format_rejects_unusable_node(
    monkeypatch: pytest.MonkeyPatch,
    node: _PixelFormatNode | None,
    message: str,
) -> None:
    """PixelFormat nodeの欠落・利用不可・書込不可をCameraErrorにする。"""
    camera = _make_pixel_format_camera("BaslerGigE", node)
    monkeypatch.setattr(genicam, "IsAvailable", lambda value: value.available)
    monkeypatch.setattr(genicam, "IsWritable", lambda value: value.writable)
    monkeypatch.setattr(genicam, "IsReadable", lambda value: value.readable)

    with pytest.raises(CameraError, match=rf"PixelFormat.*Mono12Packed.*{message}"):
        BaslerMandatorySettings().apply(camera)


def test_mandatory_pixel_format_reports_sdk_write_error(monkeypatch) -> None:  # noqa: ANN001
    """PixelFormat書込み失敗時にnode名・期待値・SDKエラーを報告する。"""
    node = _PixelFormatNode(write_error=genicam.LogicalErrorException("sdk failure"))
    camera = _make_pixel_format_camera("BaslerGigE", node)
    monkeypatch.setattr(genicam, "IsAvailable", lambda value: value.available)
    monkeypatch.setattr(genicam, "IsWritable", lambda value: value.writable)
    monkeypatch.setattr(genicam, "IsReadable", lambda value: value.readable)

    with pytest.raises(CameraError, match=r"PixelFormat.*Mono12Packed.*sdk failure"):
        BaslerMandatorySettings().apply(camera)


def test_mandatory_pixel_format_rejects_readback_mismatch(monkeypatch) -> None:  # noqa: ANN001
    """PixelFormat読戻し不一致時に現在値と期待値を報告する。"""
    node = _PixelFormatNode(update_value=False)
    camera = _make_pixel_format_camera("BaslerGigE", node)
    monkeypatch.setattr(genicam, "IsAvailable", lambda value: value.available)
    monkeypatch.setattr(genicam, "IsWritable", lambda value: value.writable)
    monkeypatch.setattr(genicam, "IsReadable", lambda value: value.readable)

    with pytest.raises(CameraError, match="PixelFormat") as exc_info:
        BaslerMandatorySettings().apply(camera)

    assert "Mono12Packed" in str(exc_info.value)
    assert "Mono8" in str(exc_info.value)


def test_camera_connection_failure_from_configurator_closes_camera(monkeypatch) -> None:  # noqa: ANN001
    """ConfiguratorのCameraErrorでもCloseと未接続状態への復帰を行う。"""
    factory = MagicMock()
    factory.EnumerateDevices.return_value = [object()]
    factory.CreateFirstDevice.return_value = object()
    factory_type = MagicMock()
    factory_type.GetInstance.return_value = factory

    instant_camera = MagicMock()
    instant_camera.IsOpen.return_value = True
    instant_camera.GetDeviceInfo.return_value.GetDeviceClass.return_value = "BaslerGigE"

    configurator = MagicMock()
    configurator.apply.side_effect = CameraError("PixelFormat initialization failed")
    monkeypatch.setattr(basler_module, "TlFactory", factory_type)
    monkeypatch.setattr(basler_module, "InstantCamera", MagicMock(return_value=instant_camera))
    camera_device = CameraDevice(configurators=[configurator])

    with pytest.raises(CameraError, match="PixelFormat initialization failed"):
        camera_device.connect()

    instant_camera.Close.assert_called_once_with()
    assert not camera_device.is_connected()
    assert camera_device.state is CameraState.DISCONNECTED


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


def test_emulator_captures_with_simulation_readback(
    camera_device: CameraDevice,
) -> None:
    """エミュレータ設定nodeと仮想timestampから読戻し値を取得する。"""
    camera_device.set_exposure(10.5)
    camera_device.set_gain(240)

    with camera_device.start_trigger_session(
        settings=SOFTWARE_TRIGGER_SETTINGS,
        expected_frames=1,
    ) as session:
        session.wait_until_ready(1000)
        session.execute_software_trigger()
        frame = session.retrieve_frame(1000)

    assert frame.image.shape == (540, 720)
    assert frame.image.dtype == np.uint16
    assert frame.readback.exposure_ms == 10.5
    assert frame.readback.gain == 240
    assert frame.readback.camera_timestamp_ticks > 0
    assert frame.readback.camera_timestamp_frequency_hz == 1_000_000_000
    assert frame.readback.source == "simulation"
    assert camera_device.state is CameraState.IDLE
    assert camera_device.camera.TriggerMode.GetValue() == "Off"


def test_simulation_readback_does_not_reuse_trigger_timestamp(
    camera_device: CameraDevice,
) -> None:
    """仮想timestampは対応する1フレームだけに使用する。"""
    provider = SimulationFrameReadbackProvider()
    provider.on_trigger_executed()

    provider.read(camera_device.camera, MagicMock())

    with pytest.raises(CameraError, match="camera timestamp"):
        provider.read(camera_device.camera, MagicMock())


def test_preview_grabbing(camera_device: CameraDevice) -> None:
    """プレビュー用非同期取得(StartGrabbing)のテスト"""
    camera_device.start_preview_grab()
    assert camera_device.camera.IsGrabbing()

    with pytest.raises(CameraError, match="idle状態"):
        camera_device.set_exposure(20.0)

    with pytest.raises(CameraError, match="idle状態"):
        camera_device.start_trigger_session(
            settings=SOFTWARE_TRIGGER_SETTINGS,
            expected_frames=1,
        )

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
        sample = camera_device.take_acquisition_sample()
        assert sample is not None
        assert sample.payload_bytes is not None
        assert sample.payload_bytes > 0

    camera_device.stop_grabbing()

    # 停止中に取得しようとした場合はNoneが返ること
    assert camera_device.retrieve_preview_frame() is None


class _FakeNode:
    """Basler trigger unit test用の読み書き可能なGenICam node。"""

    def __init__(
        self,
        value: str | float,
        *,
        available: bool = True,
        writable: bool = True,
        readable: bool = True,
        write_error: Exception | None = None,
    ) -> None:
        """初期node値と状態を保持する。"""
        self.value = value
        self.available = available
        self.writable = writable
        self.readable = readable
        self.write_error = write_error

    def is_available(self) -> bool:
        """利用可能なnodeとして扱う。"""
        return self.available

    def is_writable(self) -> bool:
        """書き込み可能なnodeとして扱う。"""
        return self.writable

    def is_readable(self) -> bool:
        """読み取り可能なnodeとして扱う。"""
        return self.readable

    def FromString(self, value: str, verify: bool = True) -> None:  # noqa: ARG002, N802
        """GenICam文字列表現からnode値を更新する。"""
        if self.write_error is not None:
            raise self.write_error
        if isinstance(self.value, int):
            self.value = int(value)
        elif isinstance(self.value, float):
            self.value = float(value)
        else:
            self.value = value

    def ToString(self) -> str:  # noqa: N802
        """現在値をGenICam文字列表現で返す。"""
        return str(self.value)

    def GetValue(self) -> str | int | float:  # noqa: N802
        """現在値を返す。"""
        return self.value


class _FakeChunkEnableNode(_FakeNode):
    """選択中のChunkごとに有効状態を保持するtest double。"""

    def __init__(self, selector: _FakeNode, values: dict[str, str]) -> None:
        """ChunkSelector nodeとselector別の初期状態を保持する。"""
        super().__init__("0")
        self.selector = selector
        self.values = values

    def is_available(self) -> bool:
        """利用可能なnodeとして扱う。"""
        return True

    def FromString(self, value: str, verify: bool = True) -> None:  # noqa: ARG002, N802
        """選択中Chunkの有効状態を更新する。"""
        self.values[str(self.selector.value)] = value

    def ToString(self) -> str:  # noqa: N802
        """選択中Chunkの有効状態を返す。"""
        return self.values[str(self.selector.value)]

    def GetValue(self) -> str:  # noqa: N802
        """選択中Chunkの有効状態を返す。"""
        return self.ToString()


class _RejectTimestampEnableNode(_FakeChunkEnableNode):
    """Timestamp Chunkのenable書込みだけを拒否するtest double。"""

    def __init__(self, selector: _FakeNode, values: dict[str, str]) -> None:
        """Timestamp enable書込み試行数を初期化する。"""
        super().__init__(selector, values)
        self.timestamp_enable_attempts = 0

    def FromString(self, value: str, verify: bool = True) -> None:  # noqa: ARG002, N802
        """Timestamp Chunkの有効化だけをSDK拒否として返す。"""
        if str(self.selector.value) == "Timestamp" and value == "1":
            self.timestamp_enable_attempts += 1
            msg = "timestamp chunk rejected"
            raise genicam.LogicalErrorException(msg)
        super().FromString(value)


class _FakeNodeMap:
    """node名で_FakeNodeを返す最小NodeMap。"""

    def __init__(self, nodes: dict[str, _FakeNode]) -> None:
        """node辞書を保持する。"""
        self.nodes = nodes

    def GetNode(self, name: str) -> _FakeNode | None:  # noqa: N802
        """指定名のnodeを返す。"""
        return self.nodes.get(name)


class _FakeGrabResult:
    """必須の撮影値Chunkを持つ成功GrabResult。"""

    def __init__(self, timestamp_ticks: int, payload_bytes: int = 123) -> None:
        """返却するcamera timestampとpayload byte数を保持する。"""
        self.payload_bytes = payload_bytes
        self.chunk_nodemap = _FakeNodeMap(
            {
                "ChunkExposureTime": _FakeNode(12_500.0),
                "ChunkGainAll": _FakeNode(240),
                "ChunkTimestamp": _FakeNode(timestamp_ticks),
            }
        )

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

    def GetChunkDataNodeMap(self) -> _FakeNodeMap:  # noqa: N802
        """撮影値を保持するChunkData node mapを返す。"""
        return self.chunk_nodemap

    def GetPayloadSize(self) -> int:  # noqa: N802
        """変換前GrabResultのpayload byte数を返す。"""
        return self.payload_bytes


class _FakeInstantCamera:
    """Basler software trigger lifecycleを観測するInstantCamera test double。"""

    def __init__(self) -> None:
        """必須nodeと取得履歴を初期化する。"""
        chunk_selector = _FakeNode("GainAll")
        self.original_chunk_enabled = {
            "ExposureTime": "0",
            "GainAll": "1",
            "Timestamp": "0",
        }
        self.nodemap = _FakeNodeMap(
            {
                "AcquisitionMode": _FakeNode("SingleFrame"),
                "TriggerSelector": _FakeNode("FrameStart"),
                "TriggerMode": _FakeNode("Off"),
                "TriggerSource": _FakeNode("Line1"),
                "TriggerActivation": _FakeNode("RisingEdge"),
                "TriggerDelayAbs": _FakeNode(0.0),
                "AcquisitionFrameRateEnable": _FakeNode(0),
                "AcquisitionFrameRateAbs": _FakeNode(100.0),
                "ChunkModeActive": _FakeNode("False"),
                "ChunkSelector": chunk_selector,
                "ChunkEnable": _FakeChunkEnableNode(
                    chunk_selector,
                    self.original_chunk_enabled.copy(),
                ),
                "GevTimestampTickFrequency": _FakeNode(125_000_000),
                "PayloadSize": _FakeNode(456),
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
    """実機相当Chunkから読戻し値を取得し、終了時にChunk設定を復元する。"""
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
    camera_device._frame_readback_provider_factory = (  # noqa: SLF001
        ChunkFrameReadbackProvider
    )
    camera_device.converter = cast("pylon.ImageFormatConverter", _FakeConverter())

    with camera_device.start_trigger_session(
        settings=SOFTWARE_TRIGGER_SETTINGS,
        expected_frames=1,
    ) as session:
        with pytest.raises(CameraError, match="idle状態"):
            camera_device.start_preview_grab()
        session.wait_until_ready(100)
        session.execute_software_trigger()
        frame = session.retrieve_frame(100)

        assert instant_camera.start_args == (
            1,
            pylon.GrabStrategy_OneByOne,
            pylon.GrabLoop_ProvidedByUser,
        )
        assert instant_camera.trigger_count == 1
        assert frame.readback.exposure_ms == 12.5
        assert frame.readback.gain == 240
        assert frame.readback.camera_timestamp_ticks == 987654
        assert frame.readback.camera_timestamp_frequency_hz == 125_000_000
        assert frame.readback.source == "camera"
        acquisition_sample = camera_device.take_acquisition_sample()
        assert acquisition_sample is not None
        assert acquisition_sample.payload_bytes == 123
        assert acquisition_sample.payload_bytes != frame.image.nbytes
        assert camera_device.take_acquisition_sample() is None

    assert instant_camera.stop_count == 1
    assert instant_camera.nodemap.nodes["TriggerMode"].value == "Off"
    assert instant_camera.nodemap.nodes["ChunkModeActive"].value == "False"
    assert instant_camera.nodemap.nodes["ChunkSelector"].value == "GainAll"
    chunk_enable = instant_camera.nodemap.nodes["ChunkEnable"]
    assert isinstance(chunk_enable, _FakeChunkEnableNode)
    assert chunk_enable.values == instant_camera.original_chunk_enabled
    assert camera_device.state is CameraState.IDLE


def test_hardware_trigger_session_applies_nodes_without_software_trigger(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Hardware設定を厳密に適用し、Software Triggerを発行しない。"""
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
    camera_device._frame_readback_provider_factory = (  # noqa: SLF001
        ChunkFrameReadbackProvider
    )
    camera_device.converter = cast("pylon.ImageFormatConverter", _FakeConverter())
    settings = TriggerSettings(
        mode="hardware",
        hardware_source="Line3",
        hardware_activation="FallingEdge",
        hardware_delay_us=12.5,
        fps_limit=25.0,
    )

    with camera_device.start_trigger_session(settings=settings, expected_frames=1) as session:
        frame = session.retrieve_frame(100)

        with pytest.raises(CameraError, match="Software Trigger"):
            session.execute_software_trigger()

    nodes = instant_camera.nodemap.nodes
    assert nodes["TriggerSource"].value == "Line3"
    assert nodes["TriggerActivation"].value == "FallingEdge"
    assert nodes["TriggerDelayAbs"].value == 12.5
    assert nodes["AcquisitionFrameRateEnable"].value == 1
    assert nodes["AcquisitionFrameRateAbs"].value == 25.0
    assert instant_camera.trigger_count == 0
    assert frame.readback.source == "camera"


@pytest.mark.parametrize(
    ("node_name", "settings"),
    [
        (
            "TriggerSource",
            TriggerSettings(
                mode="hardware",
                hardware_source="Line3",
                hardware_activation="FallingEdge",
                hardware_delay_us=12.5,
                fps_limit=None,
            ),
        ),
        (
            "TriggerActivation",
            TriggerSettings(
                mode="hardware",
                hardware_source="Line3",
                hardware_activation="FallingEdge",
                hardware_delay_us=12.5,
                fps_limit=None,
            ),
        ),
        (
            "TriggerDelayAbs",
            TriggerSettings(
                mode="hardware",
                hardware_source="Line3",
                hardware_activation="FallingEdge",
                hardware_delay_us=12.5,
                fps_limit=None,
            ),
        ),
        (
            "AcquisitionFrameRateAbs",
            TriggerSettings(
                mode="software",
                hardware_source="Line1",
                hardware_activation="RisingEdge",
                hardware_delay_us=0.0,
                fps_limit=25.0,
            ),
        ),
    ],
)
@pytest.mark.parametrize("failure_kind", ["unavailable", "nonwritable", "rejected"])
def test_trigger_setting_failures_raise_without_fallback(
    monkeypatch: pytest.MonkeyPatch,
    node_name: str,
    settings: TriggerSettings,
    failure_kind: str,
) -> None:
    """Trigger設定nodeの失敗を明示的に返し、別値へ変更しない。"""
    monkeypatch.setattr(
        basler_module.genicam,
        "IsAvailable",
        lambda node: node is not None and node.is_available(),
    )
    monkeypatch.setattr(
        basler_module.genicam,
        "IsWritable",
        lambda node: node is not None and node.is_writable(),
    )
    monkeypatch.setattr(
        basler_module.genicam,
        "IsReadable",
        lambda node: node is not None and node.is_readable(),
    )
    instant_camera = _FakeInstantCamera()
    node = instant_camera.nodemap.nodes[node_name]
    original_value = node.value
    if failure_kind == "unavailable":
        node.available = False
    elif failure_kind == "nonwritable":
        node.writable = False
    else:
        node.write_error = genicam.LogicalErrorException("rejected")

    camera_device = CameraDevice()
    camera_device._camera = cast("pylon.InstantCamera", instant_camera)  # noqa: SLF001
    camera_device._state = CameraState.IDLE  # noqa: SLF001
    camera_device._frame_readback_provider_factory = (  # noqa: SLF001
        ChunkFrameReadbackProvider
    )

    with pytest.raises(CameraError, match=node_name):
        camera_device.start_trigger_session(settings=settings, expected_frames=1)

    assert node.value == original_value
    assert camera_device.state is CameraState.IDLE


def test_grab_result_timestamp_falls_back_to_host_time(monkeypatch) -> None:  # noqa: ANN001
    """GrabResultのTimestamp Chunk欠落時はhost時刻へ限定fallbackする。"""
    monkeypatch.setattr(
        basler_module.genicam,
        "IsAvailable",
        lambda node: node is not None and node.is_available(),
    )
    monkeypatch.setattr(basler_module.genicam, "IsReadable", lambda node: node is not None)
    monkeypatch.setattr(basler_module.genicam, "IsWritable", lambda node: node is not None)
    monkeypatch.setattr(readback_module.time, "time_ns", lambda: 9876543210)
    instant_camera = _FakeInstantCamera()
    provider = ChunkFrameReadbackProvider()
    provider.prepare(cast("pylon.InstantCamera", instant_camera))
    result = _FakeGrabResult(123)
    result.chunk_nodemap.nodes.pop("ChunkTimestamp")

    frame = provider.read(
        cast("pylon.InstantCamera", instant_camera),
        result,
    )

    assert frame.exposure_ms == 12.5
    assert frame.gain == 240
    assert frame.camera_timestamp_ticks == 9876543210
    assert frame.camera_timestamp_frequency_hz == 1_000_000_000
    assert frame.source == "host"


def test_timestamp_prepare_failure_falls_back_to_host_time(monkeypatch) -> None:  # noqa: ANN001
    """Timestamp Chunk設定が利用不能でもExposure/Gain取得は継続する。"""
    monkeypatch.setattr(
        basler_module.genicam,
        "IsAvailable",
        lambda node: node is not None and node.is_available(),
    )
    monkeypatch.setattr(basler_module.genicam, "IsReadable", lambda node: node is not None)
    monkeypatch.setattr(basler_module.genicam, "IsWritable", lambda node: node is not None)
    monkeypatch.setattr(readback_module.time, "time_ns", lambda: 13579)
    instant_camera = _FakeInstantCamera()
    instant_camera.nodemap.nodes.pop("GevTimestampTickFrequency")
    provider = ChunkFrameReadbackProvider()
    provider.prepare(cast("pylon.InstantCamera", instant_camera))

    frame = provider.read(
        cast("pylon.InstantCamera", instant_camera),
        _FakeGrabResult(123),
    )

    assert frame.camera_timestamp_ticks == 13579
    assert frame.camera_timestamp_frequency_hz == 1_000_000_000
    assert frame.source == "host"


def test_timestamp_enable_rejection_is_not_retried_during_restore(monkeypatch) -> None:  # noqa: ANN001
    """Timestamp enable失敗後は未変更Chunkを復元対象に追加しない。"""
    monkeypatch.setattr(
        basler_module.genicam,
        "IsAvailable",
        lambda node: node is not None and node.is_available(),
    )
    monkeypatch.setattr(basler_module.genicam, "IsReadable", lambda node: node is not None)
    monkeypatch.setattr(basler_module.genicam, "IsWritable", lambda node: node is not None)
    instant_camera = _FakeInstantCamera()
    chunk_selector = instant_camera.nodemap.nodes["ChunkSelector"]
    original_values = instant_camera.nodemap.nodes["ChunkEnable"].values.copy()
    rejected_node = _RejectTimestampEnableNode(chunk_selector, original_values.copy())
    instant_camera.nodemap.nodes["ChunkEnable"] = rejected_node
    provider = ChunkFrameReadbackProvider()

    provider.prepare(cast("pylon.InstantCamera", instant_camera))
    provider.restore(cast("pylon.InstantCamera", instant_camera))

    assert rejected_node.timestamp_enable_attempts == 1
    assert rejected_node.values == original_values


@pytest.mark.parametrize(
    ("invalid_settings", "message"),
    [
        ({"mode": "free_run"}, "Trigger mode"),
        ({"hardware_source": ""}, "Hardware trigger source"),
        ({"hardware_activation": "   "}, "Hardware trigger activation"),
        ({"hardware_delay_us": float("nan")}, "Hardware trigger delay"),
        ({"hardware_delay_us": float("inf")}, "Hardware trigger delay"),
        ({"hardware_delay_us": -1.0}, "Hardware trigger delay"),
        ({"fps_limit": float("nan")}, "FPS Limit"),
        ({"fps_limit": float("inf")}, "FPS Limit"),
        ({"fps_limit": 0.0}, "FPS Limit"),
        ({"fps_limit": -1.0}, "FPS Limit"),
    ],
)
def test_trigger_settings_reject_non_finite_or_invalid_values(
    invalid_settings: dict[str, object],
    message: str,
) -> None:
    """TriggerSettingsは不正なmode、文字列、数値を生成時に拒否する。"""
    values: dict[str, object] = {
        "mode": "software",
        "hardware_source": "Line1",
        "hardware_activation": "RisingEdge",
        "hardware_delay_us": 0.0,
        "fps_limit": None,
    }
    values.update(invalid_settings)

    with pytest.raises(ValueError, match=message):
        TriggerSettings(**values)  # type: ignore[arg-type]


def test_unlimited_frame_rate_disables_camera_limit(monkeypatch) -> None:  # noqa: ANN001
    """Unlimitedではcamera側frame-rate enableを無効にする。"""
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
    camera_device._frame_readback_provider_factory = (  # noqa: SLF001
        ChunkFrameReadbackProvider
    )

    with camera_device.start_trigger_session(
        settings=SOFTWARE_TRIGGER_SETTINGS,
        expected_frames=1,
    ):
        assert instant_camera.nodemap.nodes["AcquisitionFrameRateEnable"].value == 0


def test_payload_size_falls_back_to_readable_camera_node(monkeypatch) -> None:  # noqa: ANN001
    """GrabResult値がない場合はcameraのPayloadSize nodeを使用する。"""
    monkeypatch.setattr(
        basler_module.genicam,
        "IsAvailable",
        lambda node: node is not None and node.is_available(),
    )
    monkeypatch.setattr(basler_module.genicam, "IsReadable", lambda node: node is not None)
    camera = _FakeInstantCamera()

    payload_bytes = basler_module._read_payload_bytes(  # noqa: SLF001
        cast("pylon.InstantCamera", camera),
        object(),
    )

    assert payload_bytes == 456


def test_missing_payload_size_does_not_fail_acquisition_statistics(monkeypatch) -> None:  # noqa: ANN001
    """両方のPayloadSizeを読めない場合は値だけを未定義にする。"""
    monkeypatch.setattr(basler_module.genicam, "IsAvailable", lambda node: node is not None)
    monkeypatch.setattr(basler_module.genicam, "IsReadable", lambda _: False)
    camera = _FakeInstantCamera()

    payload_bytes = basler_module._read_payload_bytes(  # noqa: SLF001
        cast("pylon.InstantCamera", camera),
        object(),
    )

    assert payload_bytes is None
