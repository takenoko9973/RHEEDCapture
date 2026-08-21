from __future__ import annotations

import time
from typing import Protocol, cast

from pypylon import genicam, pylon

from rheed_capture.application.ports.camera import CameraError, FrameReadback

_REQUIRED_CHUNK_SELECTORS = (
    "ExposureTime",
    "GainAll",
)
_TIMESTAMP_CHUNK_SELECTOR = "Timestamp"
_SIMULATION_TIMESTAMP_FREQUENCY_HZ = 1_000_000_000


class _GenicamNode(Protocol):
    """読戻しProviderが使うGenICam node操作の最小型。"""

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


class _ChunkGrabResult(Protocol):
    """ChunkDataのNodeMapを提供するGrabResult型。"""

    def GetChunkDataNodeMap(self) -> _GenicamNodeMap:  # noqa: N802
        """取得フレームのChunkData node mapを返す。"""
        ...


class BaslerFrameReadbackProvider(Protocol):
    """Basler撮影Sessionへフレーム読戻し処理を提供する。"""

    def prepare(self, camera: pylon.InstantCamera) -> None:
        """Session開始前に読戻しに必要な設定を適用する。"""
        ...

    def on_trigger_executed(self) -> None:
        """ソフトウェアトリガー成功直後の状態を記録する。"""
        ...

    def read(
        self,
        camera: pylon.InstantCamera,
        result: _ChunkGrabResult,
    ) -> FrameReadback:
        """取得フレームに対応する読戻し値を返す。"""
        ...

    def restore(self, camera: pylon.InstantCamera) -> None:
        """Session開始前のカメラ設定へ戻す。"""
        ...


class ChunkFrameReadbackProvider:
    """実機の必須Chunkからフレーム読戻し値を取得する。"""

    def __init__(self) -> None:
        """SessionごとのChunk復元状態を初期化する。"""
        self._original_chunk_mode_active: str | None = None
        self._original_chunk_selector: str | None = None
        self._original_chunk_enabled: dict[str, str] = {}
        self._timestamp_frequency_hz: int | None = None
        self._use_camera_timestamp = False

    def prepare(self, camera: pylon.InstantCamera) -> None:
        """必須Chunkを有効化し、camera timestamp周波数を保持する。"""
        nodemap = camera.GetNodeMap()
        self._original_chunk_mode_active = _read_required_node_string(
            nodemap,
            "ChunkModeActive",
        )

        # ChunkSelectorがChunkMode有効化前は利用できない機種があるため、この順序を守る。
        _set_required_node_value(nodemap, "ChunkModeActive", True)
        self._original_chunk_selector = _read_required_node_string(
            nodemap,
            "ChunkSelector",
        )

        for selector in _REQUIRED_CHUNK_SELECTORS:
            _set_required_node_value(nodemap, "ChunkSelector", selector)
            self._original_chunk_enabled[selector] = _read_required_node_string(
                nodemap,
                "ChunkEnable",
            )
            _set_required_node_value(nodemap, "ChunkEnable", True)

        try:
            _set_required_node_value(nodemap, "ChunkSelector", _TIMESTAMP_CHUNK_SELECTOR)
            original_timestamp_enabled = _read_required_node_string(
                nodemap,
                "ChunkEnable",
            )
            _set_required_node_value(nodemap, "ChunkEnable", True)
            # enableの書込みが成功した場合だけ、復元対象として記録する。
            self._original_chunk_enabled[_TIMESTAMP_CHUNK_SELECTOR] = (
                original_timestamp_enabled
            )
            self._timestamp_frequency_hz = _read_required_node_int(
                nodemap,
                "GevTimestampTickFrequency",
            )
            self._use_camera_timestamp = True
        except CameraError:
            # Timestamp Chunkだけは任意とし、撮影値Chunkの必須契約は維持する。
            self._timestamp_frequency_hz = _SIMULATION_TIMESTAMP_FREQUENCY_HZ
            self._use_camera_timestamp = False

    def on_trigger_executed(self) -> None:
        """実機Chunkはtrigger発行時に追加状態を記録しない。"""

    def read(
        self,
        camera: pylon.InstantCamera,  # noqa: ARG002
        result: _ChunkGrabResult,
    ) -> FrameReadback:
        """取得フレームのExposure Time、Gain All、Timestamp Chunkを読む。"""
        timestamp_frequency_hz = self._timestamp_frequency_hz
        if timestamp_frequency_hz is None:
            msg = "frame timestamp周波数が記録されていません。"
            raise CameraError(msg)

        chunk_nodemap = result.GetChunkDataNodeMap()
        exposure_us = _read_required_node_float(
            chunk_nodemap,
            "ChunkExposureTime",
        )
        if self._use_camera_timestamp:
            try:
                timestamp_ticks = _read_required_node_int(
                    chunk_nodemap,
                    "ChunkTimestamp",
                )
            except CameraError:
                # Timestamp ChunkだけはGrabResultごとに欠落する機種があるため、
                # 必須のExposure/Gainを読んだ後にhost時刻へ切り替える。
                timestamp_ticks = time.time_ns()
                timestamp_frequency_hz = _SIMULATION_TIMESTAMP_FREQUENCY_HZ
                timestamp_source = "host"
            else:
                timestamp_source = "camera"
        else:
            timestamp_ticks = time.time_ns()
            timestamp_frequency_hz = _SIMULATION_TIMESTAMP_FREQUENCY_HZ
            timestamp_source = "host"

        return FrameReadback(
            exposure_ms=exposure_us / 1000.0,
            gain=_read_required_node_int(chunk_nodemap, "ChunkGainAll"),
            camera_timestamp_ticks=timestamp_ticks,
            camera_timestamp_frequency_hz=timestamp_frequency_hz,
            source=timestamp_source,
        )

    def restore(self, camera: pylon.InstantCamera) -> None:
        """記録済みのChunkEnable、Selector、Modeを開始前の値へ戻す。"""
        nodemap = camera.GetNodeMap()
        try:
            for selector, enabled in self._original_chunk_enabled.items():
                _set_required_node_value(nodemap, "ChunkSelector", selector)
                _set_required_node_value(nodemap, "ChunkEnable", enabled)
        finally:
            # 途中のChunk復元に失敗しても、依存元のselectorとmodeは復元を試みる。
            try:
                if self._original_chunk_selector is not None:
                    _set_required_node_value(
                        nodemap,
                        "ChunkSelector",
                        self._original_chunk_selector,
                    )
            finally:
                if self._original_chunk_mode_active is not None:
                    _set_required_node_value(
                        nodemap,
                        "ChunkModeActive",
                        self._original_chunk_mode_active,
                    )


class SimulationFrameReadbackProvider:
    """エミュレータ設定nodeと仮想timestampから読戻し値を作る。"""

    def __init__(self) -> None:
        """Session内の仮想timestampを未発行状態で初期化する。"""
        self._trigger_timestamp_ns: int | None = None

    def prepare(self, camera: pylon.InstantCamera) -> None:
        """エミュレータではChunkを設定しない。"""

    def on_trigger_executed(self) -> None:
        """成功したソフトウェアトリガー直後を仮想timestampとして記録する。"""
        self._trigger_timestamp_ns = time.perf_counter_ns()

    def read(
        self,
        camera: pylon.InstantCamera,
        result: _ChunkGrabResult,  # noqa: ARG002
    ) -> FrameReadback:
        """エミュレータnodeの設定値と対応する仮想timestampを返す。"""
        if self._trigger_timestamp_ns is None:
            # 別フレームの時刻を再利用しないため、trigger未記録時は明示的に失敗させる。
            msg = "シミュレーションcamera timestampが記録されていません。"
            raise CameraError(msg)

        trigger_timestamp_ns = self._trigger_timestamp_ns
        self._trigger_timestamp_ns = None
        return FrameReadback(
            exposure_ms=float(camera.ExposureTimeAbs.GetValue()) / 1000.0,
            gain=int(camera.GainRaw.GetValue()),
            camera_timestamp_ticks=trigger_timestamp_ns,
            camera_timestamp_frequency_hz=_SIMULATION_TIMESTAMP_FREQUENCY_HZ,
            source="simulation",
        )

    def restore(self, camera: pylon.InstantCamera) -> None:
        """エミュレータでは復元対象のChunk設定を持たない。"""


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


def _read_required_node_int(nodemap: _GenicamNodeMap, node_name: str) -> int:
    """必須GenICam nodeの現在値を整数で取得する。"""
    value = _read_required_node_value(nodemap, node_name)
    try:
        return int(cast("int | float | str", value))
    except (TypeError, ValueError, OverflowError) as e:
        msg = f"必須GenICam node '{node_name}' の値を整数として読めません: {e}"
        raise CameraError(msg) from e


def _read_required_node_float(nodemap: _GenicamNodeMap, node_name: str) -> float:
    """必須GenICam nodeの現在値を浮動小数点数で取得する。"""
    value = _read_required_node_value(nodemap, node_name)
    try:
        return float(cast("int | float | str", value))
    except (TypeError, ValueError, OverflowError) as e:
        msg = f"必須GenICam node '{node_name}' の値を浮動小数点数として読めません: {e}"
        raise CameraError(msg) from e


def _read_required_node_value(nodemap: _GenicamNodeMap, node_name: str) -> object:
    """必須GenICam nodeの現在値を取得する。"""
    node = _get_required_node(nodemap, node_name)
    if not genicam.IsReadable(node):
        msg = f"必須GenICam node '{node_name}' は読み取りできません。"
        raise CameraError(msg)
    try:
        return node.GetValue()
    except genicam.LogicalErrorException as e:
        msg = f"必須GenICam node '{node_name}' の読み取りに失敗しました: {e}"
        raise CameraError(msg) from e
