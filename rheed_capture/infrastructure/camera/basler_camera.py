# BaslerCameraと取得Sessionは同一アダプターを分割した協調クラスとして内部状態を共有する。
# ruff: noqa: SLF001

from __future__ import annotations

import logging
import threading
import time
from enum import Enum
from typing import TYPE_CHECKING, Protocol, Self

import numpy as np
from pypylon import genicam, pylon
from pypylon.pylon import GenericException, InstantCamera, TlFactory

from rheed_capture.application.ports.camera import (
    SAVED_BIT_DEPTH_12,
    SENSOR_BIT_DEPTH_8,
    SENSOR_BIT_DEPTH_12,
    CameraError,
    CameraFrame,
    ImageFormatSnapshot,
    TriggerSettings,
)
from rheed_capture.domain.acquisition_statistics import AcquisitionSample
from rheed_capture.infrastructure.camera.basler_configurators import (
    CAMERA_EMULATION_DEVICE_CLASS,
    BaslerCameraConfigurator,
    BaslerCameraEmulationSettings,
    BaslerMandatorySettings,
    _set_required_pixel_format,
    pixel_format_for_sensor_bit_depth,
)
from rheed_capture.infrastructure.camera.basler_frame_readback import (
    BaslerFrameReadbackProvider,
    ChunkFrameReadbackProvider,
    SimulationFrameReadbackProvider,
)

if TYPE_CHECKING:
    from collections.abc import Sequence
    from types import TracebackType

logger = logging.getLogger(__name__)


class _GenicamNode(Protocol):
    """Sessionで使うGenICam node操作の最小型。"""

    def FromString(self, value: str, verify: bool = True) -> None:  # noqa: N802
        """文字列表現の値を書き込む。"""
        ...

    def ToString(self) -> str:  # noqa: N802
        """現在値を文字列表現で返す。"""
        ...

    def GetValue(self) -> object:  # noqa: N802
        """現在値を返す。"""
        ...


class _GenicamNodeMap(Protocol):
    """node名からGenICam nodeを取得する最小型。"""

    def GetNode(self, name: str) -> _GenicamNode | None:  # noqa: N802
        """指定名のnodeを返す。"""
        ...


class CameraState(Enum):
    """BaslerCameraが所有する排他的な取得状態。"""

    DISCONNECTED = "disconnected"
    IDLE = "idle"
    PREVIEW = "preview"
    TRIGGER_CAPTURE = "trigger_capture"


class BaslerCamera:
    """接続状態とプレビュー/保存取得の排他所有権を管理する。"""

    _camera: InstantCamera | None

    def __init__(
        self,
        configurators: Sequence[BaslerCameraConfigurator] | None = None,
    ) -> None:
        """カメラデバイスラッパーを未接続状態で初期化する。"""
        self._camera = None
        self._lock = threading.RLock()
        self._configurators = tuple(configurators or (BaslerMandatorySettings(),))
        self._state = CameraState.DISCONNECTED
        self._owner_thread_id: int | None = None
        self._active_trigger_session: _BaslerTriggerCaptureSession | None = None
        self._latest_acquisition_sample: AcquisitionSample | None = None
        self._image_format: ImageFormatSnapshot | None = None
        self._frame_readback_provider_factory: (
            type[ChunkFrameReadbackProvider | SimulationFrameReadbackProvider]
        )

        self.converter = pylon.ImageFormatConverter()
        self.converter.OutputPixelFormat = pylon.PixelType_Mono16
        self.converter.OutputBitAlignment = pylon.OutputBitAlignment_MsbAligned

    @property
    def camera(self) -> pylon.InstantCamera:
        """接続済みのpypylonカメラインスタンスを返す。"""
        if self._camera is None or not self._camera.IsOpen():
            msg = "カメラが接続されていません。"
            raise CameraError(msg)

        return self._camera

    @property
    def state(self) -> CameraState:
        """現在の所有状態を返す。"""
        return self._state

    def take_acquisition_sample(self) -> AcquisitionSample | None:
        """直前の正常取得sampleを1回だけ返す。"""
        with self._lock:
            sample = self._latest_acquisition_sample
            self._latest_acquisition_sample = None
            return sample

    def connect(self) -> None:
        """最初に見つかったBaslerカメラへ接続して初期設定を適用する。"""
        with self._lock:
            if self.is_connected():
                return

            try:
                tl_factory = TlFactory.GetInstance()
                devices = tl_factory.EnumerateDevices()
                if not devices:
                    msg = "カメラが見つかりません。"
                    raise CameraError(msg)  # noqa: TRY301

                self._camera = InstantCamera(tl_factory.CreateFirstDevice())
                self._camera.Open()
                device_info = self.camera.GetDeviceInfo()

                # PYLON_CAMEMUは列挙台数であり、実際の接続先はDeviceClassで判定する。
                is_emulation = (
                    device_info.GetDeviceClass() == CAMERA_EMULATION_DEVICE_CLASS
                )
                self._frame_readback_provider_factory = (
                    SimulationFrameReadbackProvider
                    if is_emulation
                    else ChunkFrameReadbackProvider
                )

                for configurator in self._configurators:
                    configurator.apply(self.camera)
                # BaslerMandatorySettingsが同じ値を設定・読戻し済みなので、ここでは
                # その成功した値に対応するsnapshotだけを確定する。
                self._image_format = ImageFormatSnapshot(
                    bit_depth_sensor=SENSOR_BIT_DEPTH_12,
                    bit_depth_saved=SAVED_BIT_DEPTH_12,
                    pixel_format=pixel_format_for_sensor_bit_depth(
                        device_info.GetDeviceClass(),
                        SENSOR_BIT_DEPTH_12,
                    ),
                    alignment="MsbAligned",
                )
                if is_emulation:
                    BaslerCameraEmulationSettings().apply(self.camera)

                self._state = CameraState.IDLE
                logger.info(
                    "Connected to camera: model=%s serial=%s class=%s version=%s",
                    device_info.GetModelName(),
                    device_info.GetSerialNumber(),
                    device_info.GetDeviceClass(),
                    device_info.GetDeviceVersion(),
                )

            except CameraError:
                self._cleanup_failed_connection()
                raise
            except GenericException as e:
                self._cleanup_failed_connection()
                msg = f"カメラへの接続に失敗しました: {e}"
                raise CameraError(msg) from e

    def _cleanup_failed_connection(self) -> None:
        """接続初期化に失敗したカメラを閉じて未接続状態へ戻す。"""
        camera = self._camera
        try:
            if camera is not None and camera.IsOpen():
                camera.Close()
        except GenericException:
            # 初期化失敗の原因を置き換えず、Close失敗はログへ残す。
            logger.exception("接続初期化失敗後のカメラ切断にも失敗しました")
        finally:
            self._camera = None
            self._state = CameraState.DISCONNECTED
            self._latest_acquisition_sample = None
            self._image_format = None

    def disconnect(self) -> None:
        """IDLE状態のカメラを切断する。"""
        with self._lock:
            if not self.is_connected():
                return
            self._require_state(CameraState.IDLE, "カメラ切断")
            self.camera.Close()
            self._camera = None
            self._state = CameraState.DISCONNECTED
            self._latest_acquisition_sample = None
            self._image_format = None

    def is_connected(self) -> bool:
        """カメラがオープン済みかどうかを返す。"""
        return self._camera is not None and self._camera.IsOpen()

    def get_exposure_bounds(self) -> tuple[float, float]:
        """露光時間の設定可能範囲をミリ秒単位で返す。"""
        min_us = self.camera.ExposureTimeAbs.GetMin()
        max_us = self.camera.ExposureTimeAbs.GetMax()
        return (min_us / 1000.0, max_us / 1000.0)

    def get_gain_bounds(self) -> tuple[int, int]:
        """ゲインの設定可能範囲を返す。"""
        min_gain = self.camera.GainRaw.GetMin()
        max_gain = self.camera.GainRaw.GetMax()
        return (min_gain, max_gain)

    def set_exposure(self, exposure_ms: float) -> None:
        """IDLE状態で露光時間をミリ秒単位に設定する。"""
        with self._lock:
            self._require_state(CameraState.IDLE, "露光時間設定")
            exposure_us = exposure_ms * 1000.0
            self.camera.ExposureTimeAbs.SetValue(exposure_us)

    def get_exposure(self) -> float:
        """現在の露光時間をミリ秒単位で返す。"""
        with self._lock:
            exposure_us = self.camera.ExposureTimeAbs.GetValue()
            return exposure_us / 1000.0

    def set_gain(self, gain: int) -> None:
        """IDLE状態でゲインを設定する。"""
        with self._lock:
            self._require_state(CameraState.IDLE, "ゲイン設定")
            self.camera.GainRaw.SetValue(gain)

    def configure_image_format(self, sensor_bit_depth: int) -> ImageFormatSnapshot:
        """IDLE状態でPixelFormatとconverterを設定し、読戻しsnapshotを返す。"""
        with self._lock:
            self._require_state(CameraState.IDLE, "画像形式設定")
            return self._ensure_image_format(sensor_bit_depth)

    def _configure_image_format(
        self,
        sensor_bit_depth: int,
    ) -> ImageFormatSnapshot:
        """カメラのPixelFormatとconverterを設定する。"""
        device_class = self.camera.GetDeviceInfo().GetDeviceClass()
        expected_pixel_format = pixel_format_for_sensor_bit_depth(
            device_class,
            sensor_bit_depth,
        )
        nodemap = self.camera.GetNodeMap()
        actual_pixel_format = _set_required_pixel_format(nodemap, expected_pixel_format)

        if sensor_bit_depth == SENSOR_BIT_DEPTH_8:
            self.converter.OutputPixelFormat = pylon.PixelType_Mono8
            saved_bit_depth = 8
            alignment = None
        else:
            self.converter.OutputPixelFormat = pylon.PixelType_Mono16
            self.converter.OutputBitAlignment = pylon.OutputBitAlignment_MsbAligned
            saved_bit_depth = 16
            alignment = "MsbAligned"

        snapshot = ImageFormatSnapshot(
            bit_depth_sensor=sensor_bit_depth,
            bit_depth_saved=saved_bit_depth,
            pixel_format=actual_pixel_format,
            alignment=alignment,
        )
        self._image_format = snapshot
        return snapshot

    def _ensure_image_format(self, sensor_bit_depth: int) -> ImageFormatSnapshot:
        """必要なときだけIDLE状態で画像形式を設定し、現在のsnapshotを返す。"""
        image_format = self._image_format
        if image_format is None or image_format.bit_depth_sensor != sensor_bit_depth:
            return self._configure_image_format(sensor_bit_depth)
        return image_format

    def get_gain(self) -> float:
        """現在のゲインを返す。"""
        with self._lock:
            return self.camera.GainRaw.GetValue()

    def start_preview_grab(self) -> None:
        """TriggerMode=Offを確認してプレビュー連続取得を開始する。"""
        with self._lock:
            if self._state is CameraState.PREVIEW:
                self._require_owner_thread("プレビュー継続")
                return

            self._require_state(CameraState.IDLE, "プレビュー開始")
            trigger_mode = _read_required_node_string(
                self.camera.GetNodeMap(),
                "TriggerMode",
            )
            if trigger_mode != "Off":
                msg = f"TriggerModeがOffではないためプレビューを開始できません: {trigger_mode}"
                raise CameraError(msg)

            try:
                self.camera.StartGrabbing(pylon.GrabStrategy_LatestImageOnly)
            except GenericException as e:
                msg = f"プレビュー取得の開始に失敗しました: {e}"
                raise CameraError(msg) from e

            self._state = CameraState.PREVIEW
            self._owner_thread_id = threading.get_ident()
            self._latest_acquisition_sample = None
            # 既存プレビューの開始直後に空応答が続くのを避けるための待機を維持する。
            time.sleep(0.1)

    def stop_grabbing(self) -> None:
        """所有中のプレビュー取得を停止してIDLEへ戻す。"""
        with self._lock:
            if self._state is CameraState.DISCONNECTED:
                return
            if self._state is CameraState.IDLE:
                return
            if self._state is CameraState.TRIGGER_CAPTURE:
                msg = "Trigger取得はSession.close()で停止してください。"
                raise CameraError(msg)

            self._require_owner_thread("プレビュー停止")
            try:
                if self.camera.IsGrabbing():
                    self.camera.StopGrabbing()
            except GenericException as e:
                msg = f"プレビュー取得の停止に失敗しました: {e}"
                raise CameraError(msg) from e
            finally:
                self._state = CameraState.IDLE
                self._owner_thread_id = None
                self._latest_acquisition_sample = None

    def start_trigger_session(
        self,
        *,
        settings: TriggerSettings,
        expected_frames: int | None,
    ) -> _BaslerTriggerCaptureSession:
        """IDLE状態から指定modeのTrigger Sessionを開始する。"""
        if expected_frames is not None and expected_frames <= 0:
            msg = "expected_framesは正の整数またはNoneにしてください。"
            raise ValueError(msg)

        with self._lock:
            self._require_state(CameraState.IDLE, "Trigger Session開始")
            image_format = self._ensure_image_format(settings.sensor_bit_depth)
            session = _BaslerTriggerCaptureSession(
                self,
                settings=settings,
                expected_frames=expected_frames,
                image_format=image_format,
            )
            try:
                session._start()
            except (CameraError, GenericException):
                session._cleanup_after_failed_start()
                raise

            self._state = CameraState.TRIGGER_CAPTURE
            self._owner_thread_id = threading.get_ident()
            self._active_trigger_session = session
            self._latest_acquisition_sample = None
            return session

    def _is_valid_grab_result(self, result: object) -> bool:
        """RetrieveResultの戻り値が有効な結果かどうかを返す。"""
        is_valid = getattr(result, "IsValid", None)
        if callable(is_valid):
            return bool(is_valid())
        return result is not None

    def retrieve_preview_frame(self, timeout_ms: int = 1000) -> np.ndarray | None:
        """プレビュー連続取得中の次フレームを返す。"""
        with self._lock:
            if self._state is not CameraState.PREVIEW:
                return None
            self._require_owner_thread("プレビューフレーム取得")
            self._latest_acquisition_sample = None

            try:
                with self.camera.RetrieveResult(
                    timeout_ms,
                    pylon.TimeoutHandling_Return,
                ) as result:
                    if not self._is_valid_grab_result(result):
                        return None

                    if result.GrabSucceeded():
                        self._record_successful_acquisition(result)
                        return self._convert_result(result)

                    return None

            except GenericException as e:
                logger.exception("プレビュー画像の取得中にエラーが発生しました")
                msg = f"プレビュー画像の取得に失敗しました: {e}"
                raise CameraError(msg) from e

    def _record_successful_acquisition(self, result: object) -> None:
        """正常GrabResultの到着時刻と転送payloadを保存する。"""
        payload_bytes = _read_payload_bytes(self.camera, result)
        self._latest_acquisition_sample = AcquisitionSample(
            timestamp=time.perf_counter(),
            payload_bytes=payload_bytes,
        )

    def _convert_result(self, result: object) -> np.ndarray:
        """現在のconverterでGrabResultを変換し、期待dtypeを検証する。"""
        image_format = self._require_image_format()
        try:
            converted = self.converter.Convert(result)
            image = converted.GetArray()
        except GenericException as e:
            msg = "画像変換に失敗しました。"
            raise CameraError(msg) from e

        expected_dtype = (
            np.dtype(np.uint8)
            if image_format.bit_depth_sensor == SENSOR_BIT_DEPTH_8
            else np.dtype(np.uint16)
        )
        if not isinstance(image, np.ndarray) or image.dtype != expected_dtype:
            msg = (
                "converterの出力dtypeが期待値と異なります: "
                f"actual={getattr(image, 'dtype', None)}, expected={expected_dtype}"
            )
            raise CameraError(msg)
        return image

    def _require_image_format(self) -> ImageFormatSnapshot:
        """接続済みcameraで確定した画像形式snapshotを返す。"""
        if self._image_format is None:
            msg = "画像形式がcameraへ設定されていません。"
            raise CameraError(msg)
        return self._image_format

    def _require_state(self, expected: CameraState, operation: str) -> None:
        """操作に必要な状態でなければ暗黙切替せず失敗させる。"""
        if self._state is not expected:
            msg = f"{operation}は{expected.value}状態でのみ実行できます: {self._state.value}"
            raise CameraError(msg)

    def _require_owner_thread(self, operation: str) -> None:
        """取得を開始したスレッド以外からの同時操作を拒否する。"""
        if self._owner_thread_id != threading.get_ident():
            msg = f"{operation}はカメラを所有するスレッドから実行してください。"
            raise CameraError(msg)


class _BaslerTriggerCaptureSession:
    """Basler固有のGenICam設定とtrigger取得ライフサイクルを所有する。"""

    def __init__(
        self,
        camera_device: BaslerCamera,
        *,
        settings: TriggerSettings,
        expected_frames: int | None,
        image_format: ImageFormatSnapshot,
    ) -> None:
        """対象カメラと予定フレーム数を保持する。"""
        self._camera_device = camera_device
        self._settings = settings
        self._expected_frames = expected_frames
        self._closed = False
        self._readback_provider: BaslerFrameReadbackProvider = (
            camera_device._frame_readback_provider_factory()
        )
        self._image_format = image_format

    def __enter__(self) -> Self:
        """開始済みSession自身を返す。"""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """取得例外を保持しつつ、Sessionを必ず閉じる。"""
        try:
            self.close()
        except CameraError:
            if exc_value is None:
                raise
            logger.exception("取得失敗後のTrigger Session終了にも失敗しました")

    def _start(self) -> None:
        """必須nodeを検証・設定し、OneByOne取得を開始する。"""
        camera = self._camera_device.camera
        nodemap = camera.GetNodeMap()

        _set_required_node_value(nodemap, "AcquisitionMode", "Continuous")
        _apply_frame_rate_limit(nodemap, self._settings.fps_limit)
        _set_required_node_value(nodemap, "TriggerSelector", "FrameStart")
        _set_required_node_value(nodemap, "TriggerMode", "On")
        if self._settings.mode == "software":
            _set_required_node_value(nodemap, "TriggerSource", "Software")
        else:
            _set_required_node_value(
                nodemap,
                "TriggerSource",
                self._settings.hardware_source,
            )
            _set_required_node_value(
                nodemap,
                "TriggerActivation",
                self._settings.hardware_activation,
            )
            _set_required_node_value(
                nodemap,
                "TriggerDelayAbs",
                self._settings.hardware_delay_us,
            )
        self._readback_provider.prepare(camera)

        try:
            # pypylonでは予定枚数つき取得は別APIを使い、SDK内部のRetrieveResult待機を起動しない。
            if self._expected_frames is None:
                camera.StartGrabbing(
                    pylon.GrabStrategy_OneByOne,
                    pylon.GrabLoop_ProvidedByUser,
                )
            else:
                camera.StartGrabbingMax(
                    self._expected_frames,
                    pylon.GrabStrategy_OneByOne,
                    pylon.GrabLoop_ProvidedByUser,
                )
        except GenericException as e:
            msg = f"StartGrabbing(GrabStrategy_OneByOne)に失敗しました: {e}"
            raise CameraError(msg) from e

    def wait_until_ready(self, timeout_ms: int) -> None:
        """カメラがFrameStart triggerを受理できるまで待つ。"""
        with self._camera_device._lock:
            self._require_active("TriggerReady待機")
            if self._settings.mode != "software":
                msg = "Hardware modeではTriggerReady待機を実行できません。"
                raise CameraError(msg)
            try:
                ready = self._camera_device.camera.WaitForFrameTriggerReady(
                    timeout_ms,
                    pylon.TimeoutHandling_ThrowException,
                )
            except pylon.TimeoutException as e:
                msg = f"WaitForFrameTriggerReadyが{timeout_ms} msでタイムアウトしました。"
                raise TimeoutError(msg) from e
            except GenericException as e:
                msg = f"WaitForFrameTriggerReadyに失敗しました: {e}"
                raise CameraError(msg) from e

            if not ready:
                msg = f"WaitForFrameTriggerReadyが{timeout_ms} msで失敗しました。"
                raise TimeoutError(msg)

    def execute_software_trigger(self) -> None:
        """ソフトウェアFrameStart triggerを1回発行する。"""
        with self._camera_device._lock:
            self._require_active("ソフトトリガー発行")
            if self._settings.mode != "software":
                msg = "Hardware modeではSoftware Triggerを発行できません。"
                raise CameraError(msg)
            try:
                self._camera_device.camera.ExecuteSoftwareTrigger()
                self._readback_provider.on_trigger_executed()
            except GenericException as e:
                msg = f"ExecuteSoftwareTriggerに失敗しました: {e}"
                raise CameraError(msg) from e

    def retrieve_frame(self, timeout_ms: int) -> CameraFrame:
        """発行済みtriggerに対応するRaw画像とcamera timestampを返す。"""
        with self._camera_device._lock:
            self._require_active("トリガーフレーム取得")
            self._camera_device._latest_acquisition_sample = None
            try:
                with self._camera_device.camera.RetrieveResult(
                    timeout_ms,
                    pylon.TimeoutHandling_ThrowException,
                ) as result:
                    if not self._camera_device._is_valid_grab_result(result):
                        msg = "RetrieveResultが無効なGrabResultを返しました。"
                        raise CameraError(msg)
                    if not result.GrabSucceeded():
                        msg = f"GrabSucceeded=False: {result.GetErrorDescription()}"
                        raise CameraError(msg)

                    self._camera_device._record_successful_acquisition(result)
                    readback = self._readback_provider.read(
                        self._camera_device.camera,
                        result,
                    )
                    image = self._camera_device._convert_result(result)

                    return CameraFrame(
                        image=image,
                        readback=readback,
                        image_format=self._image_format,
                    )

            except pylon.TimeoutException as e:
                msg = f"RetrieveResultが{timeout_ms} msでタイムアウトしました。"
                raise TimeoutError(msg) from e
            except GenericException as e:
                msg = f"RetrieveResultに失敗しました: {e}"
                raise CameraError(msg) from e

    def close(self) -> None:
        """取得停止とnode復元を行い、冪等にIDLEへ戻す。"""
        with self._camera_device._lock:
            if self._closed:
                return
            self._camera_device._require_owner_thread("Trigger Session終了")
            self._closed = True

            cleanup_error: CameraError | None = None
            try:
                if self._camera_device.camera.IsGrabbing():
                    self._camera_device.camera.StopGrabbing()
            except GenericException as e:
                cleanup_error = CameraError(f"StopGrabbingに失敗しました: {e}")

            try:
                self._restore_nodes()
            except CameraError as e:
                if cleanup_error is None:
                    cleanup_error = e
                else:
                    logger.exception("StopGrabbing失敗後のtrigger node復元にも失敗しました")
            finally:
                self._camera_device._active_trigger_session = None
                self._camera_device._owner_thread_id = None
                self._camera_device._state = CameraState.IDLE

            if cleanup_error is not None:
                raise cleanup_error

    def _cleanup_after_failed_start(self) -> None:
        """Session開始途中で変更済みのnodeと取得状態を可能な範囲で戻す。"""
        camera = self._camera_device.camera
        try:
            if camera.IsGrabbing():
                camera.StopGrabbing()
            self._restore_nodes()
        except (CameraError, GenericException):
            logger.exception("Trigger Session開始失敗後の復元に失敗しました")
        finally:
            self._closed = True

    def _restore_nodes(self) -> None:
        """読戻し設定を復元してからtriggerを無効化する。"""
        camera = self._camera_device.camera
        try:
            self._readback_provider.restore(camera)
        finally:
            # Chunk復元に失敗しても、プレビュー再開に必要なTriggerModeはOffへ戻す。
            _set_required_node_value(camera.GetNodeMap(), "TriggerMode", "Off")

    def _require_active(self, operation: str) -> None:
        """このSessionが現在のカメラ所有者であることを確認する。"""
        self._camera_device._require_state(CameraState.TRIGGER_CAPTURE, operation)
        self._camera_device._require_owner_thread(operation)
        if self._closed or self._camera_device._active_trigger_session is not self:
            msg = f"{operation}に使用したTrigger Sessionは終了済みです。"
            raise CameraError(msg)


def _apply_frame_rate_limit(
    nodemap: _GenicamNodeMap,
    fps_limit: float | None,
) -> None:
    """camera側FPS LimitをUnlimitedまたは指定正値へ設定する。"""
    if fps_limit is None:
        _set_required_node_value(nodemap, "AcquisitionFrameRateEnable", False)
        return

    _set_required_node_value(nodemap, "AcquisitionFrameRateEnable", True)
    _set_required_node_value(nodemap, "AcquisitionFrameRateAbs", fps_limit)


def _get_required_node(nodemap: _GenicamNodeMap, node_name: str) -> _GenicamNode:
    """必須GenICam nodeを取得し、欠落時はnode名付きCameraErrorにする。"""
    try:
        node = nodemap.GetNode(node_name)
    except genicam.LogicalErrorException as e:
        msg = f"必須GenICam node '{node_name}' が存在しません: {e}"
        raise CameraError(msg) from e

    if node is None or not genicam.IsAvailable(node):
        msg = f"必須GenICam node '{node_name}' が利用できません。"
        raise CameraError(msg)
    return node


def _set_required_node_value(
    nodemap: _GenicamNodeMap,
    node_name: str,
    value: object,
) -> None:
    """必須GenICam nodeへ値を書き、未対応値や書込不可を明示的に失敗させる。"""
    node = _get_required_node(nodemap, node_name)
    if not genicam.IsWritable(node):
        msg = f"必須GenICam node '{node_name}' は書き込みできません。"
        raise CameraError(msg)

    # GenICam IBoolean.FromStringはPython表記のTrue/Falseではなく1/0を要求する。
    serialized_value = str(int(value)) if isinstance(value, bool) else str(value)
    try:
        node.FromString(serialized_value)
    except genicam.LogicalErrorException as e:
        msg = f"必須GenICam node '{node_name}' に値 '{value}' を設定できません: {e}"
        raise CameraError(msg) from e


def _read_required_node_string(nodemap: _GenicamNodeMap, node_name: str) -> str:
    """必須GenICam nodeの現在値を文字列で取得する。"""
    node = _get_required_node(nodemap, node_name)
    if not genicam.IsReadable(node):
        msg = f"必須GenICam node '{node_name}' は読み取りできません。"
        raise CameraError(msg)
    try:
        return str(node.ToString())
    except genicam.LogicalErrorException as e:
        msg = f"必須GenICam node '{node_name}' の読み取りに失敗しました: {e}"
        raise CameraError(msg) from e


def _read_payload_bytes(camera: InstantCamera, result: object) -> int | None:
    """GrabResultを優先し、取得不能時だけcamera nodeからpayload byte数を読む。"""
    get_payload_size = getattr(result, "GetPayloadSize", None)
    if callable(get_payload_size):
        try:
            payload_bytes = int(get_payload_size())
        except (genicam.GenericException, TypeError, ValueError) as e:
            # Payload診断の取得失敗で、正常な画像取得自体を失敗させない。
            logger.debug("GrabResultのPayloadSize取得に失敗しました: %s", e)
        else:
            if payload_bytes >= 0:
                return payload_bytes

    return _read_camera_payload_bytes(camera)


def _read_camera_payload_bytes(camera: InstantCamera) -> int | None:
    """読み取り可能なPayloadSize nodeからpayload byte数を返す。"""
    try:
        node = camera.GetNodeMap().GetNode("PayloadSize")
        if (
            node is None
            or not genicam.IsAvailable(node)
            or not genicam.IsReadable(node)
        ):
            return None
        payload_bytes = int(node.GetValue())
    except (genicam.GenericException, TypeError, ValueError) as e:
        # node値も診断専用なので、取得不能時はPayload表示だけを省略する。
        logger.debug("camera nodeのPayloadSize取得に失敗しました: %s", e)
        return None

    return payload_bytes if payload_bytes >= 0 else None


CameraDevice = BaslerCamera
