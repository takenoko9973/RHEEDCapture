"""接続したBaslerカメラのGenICam node情報を表示してJSONへ保存する。"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, cast

from pypylon import genicam, pylon

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

DEFAULT_OUTPUT_PATH = Path("camera_nodes.json")
CAMERA_EMULATION_ENV_VAR = "PYLON_CAMEMU"

_INTERFACE_TYPE_NAMES = {
    genicam.intfIValue: "Value",
    genicam.intfIBase: "Base",
    genicam.intfIInteger: "Integer",
    genicam.intfIBoolean: "Boolean",
    genicam.intfICommand: "Command",
    genicam.intfIFloat: "Float",
    genicam.intfIString: "String",
    genicam.intfIRegister: "Register",
    genicam.intfICategory: "Category",
    genicam.intfIEnumeration: "Enumeration",
    genicam.intfIEnumEntry: "EnumEntry",
    genicam.intfIPort: "Port",
}

_ACCESS_MODE_NAMES = {
    genicam.NI: "not_implemented",
    genicam.NA: "not_available",
    genicam.WO: "write_only",
    genicam.RO: "read_only",
    genicam.RW: "read_write",
}

_VISIBILITY_NAMES = {
    genicam.Beginner: "beginner",
    genicam.Expert: "expert",
    genicam.Guru: "guru",
    genicam.Invisible: "invisible",
}

_VALUELESS_INTERFACE_TYPES = {
    genicam.intfICommand,
    genicam.intfIRegister,
    genicam.intfICategory,
    genicam.intfIPort,
}


class _NodeMetadata(Protocol):
    """一覧生成に必要なGenICam nodeメタデータの最小インターフェース。"""

    def GetName(self, fully_qualified: bool = False) -> str:  # noqa: N802
        """node名を返す。"""
        ...

    def GetDisplayName(self) -> str:  # noqa: N802
        """表示名を返す。"""
        ...

    def GetDescription(self) -> str:  # noqa: N802
        """説明を返す。"""
        ...

    def GetVisibility(self) -> int:  # noqa: N802
        """可視性を返す。"""
        ...

    def GetPrincipalInterfaceType(self) -> int:  # noqa: N802
        """主要インターフェース型を返す。"""
        ...

    def IsFeature(self) -> bool:  # noqa: N802
        """公開feature nodeかを返す。"""
        ...


class _ValueNode(Protocol):
    """値とメタデータを読み取れるGenICam nodeの最小インターフェース。"""

    def GetNode(self) -> _NodeMetadata:  # noqa: N802
        """nodeメタデータを返す。"""
        ...

    def GetAccessMode(self) -> int:  # noqa: N802
        """現在のアクセスモードを返す。"""
        ...

    def ToString(self, verify: bool = False, ignore_cache: bool = False) -> str:  # noqa: N802
        """現在値を文字列表現で返す。"""
        ...


class _NodeMap(Protocol):
    """feature nodeを列挙できるGenICam node map。"""

    def GetNodes(self) -> Iterable[_ValueNode]:  # noqa: N802
        """node map内の全nodeを返す。"""
        ...


class _DeviceInfo(Protocol):
    """カメラ識別情報の読み取りに必要な最小インターフェース。"""

    def GetVendorName(self) -> str:  # noqa: N802
        """ベンダー名を返す。"""
        ...

    def GetModelName(self) -> str:  # noqa: N802
        """モデル名を返す。"""
        ...

    def GetSerialNumber(self) -> str:  # noqa: N802
        """シリアル番号を返す。"""
        ...

    def GetDeviceClass(self) -> str:  # noqa: N802
        """デバイスクラスを返す。"""
        ...

    def GetDeviceVersion(self) -> str:  # noqa: N802
        """デバイスバージョンを返す。"""
        ...

    def GetFriendlyName(self) -> str:  # noqa: N802
        """人向けのデバイス名を返す。"""
        ...


class _TlFactory(Protocol):
    """カメラ列挙とデバイス生成に必要なtransport layer factory。"""

    def EnumerateDevices(self) -> Iterable[_DeviceInfo]:  # noqa: N802
        """検出済みカメラを返す。"""
        ...

    def CreateDevice(self, device_info: _DeviceInfo) -> pylon.DeviceInfo:  # noqa: N802
        """指定情報に対応するpylon deviceを生成する。"""
        ...


@dataclass(frozen=True)
class CameraInfo:
    """レポートへ保存するカメラ識別情報。"""

    vendor: str
    model: str
    serial_number: str
    device_class: str
    device_version: str
    friendly_name: str


@dataclass(frozen=True)
class CameraNodeInfo:
    """1個のGenICam feature nodeから取得した情報。"""

    name: str
    display_name: str
    node_type: str
    access_mode: str
    implemented: bool
    available: bool
    readable: bool
    writable: bool
    visibility: str
    value: str | None
    minimum: int | float | None
    maximum: int | float | None
    increment: int | float | None
    unit: str | None
    enum_values: tuple[str, ...] | None
    maximum_length: int | None
    description: str
    errors: tuple[str, ...]


@dataclass(frozen=True)
class CameraNodeReport:
    """カメラ情報とfeature node一覧をまとめた保存形式。"""

    generated_at: str
    camera: CameraInfo
    nodes: tuple[CameraNodeInfo, ...]


@dataclass(frozen=True)
class _NodeConstraints:
    """node型固有の制約情報。"""

    minimum: int | float | None = None
    maximum: int | float | None = None
    increment: int | float | None = None
    unit: str | None = None
    enum_values: tuple[str, ...] | None = None
    maximum_length: int | None = None


def _named_constant(value: int, names: dict[int, str]) -> str:
    """既知の定数名を返し、未知の値は数値を含む名前にする。"""
    return names.get(value, f"unknown({value})")


def _read_node_value(
    value_node: _ValueNode,
    *,
    readable: bool,
    interface_type: int,
    errors: list[str],
) -> str | None:
    """読み取り可能な値nodeから現在値を取得する。"""
    if not readable or interface_type in _VALUELESS_INTERFACE_TYPES:
        return None

    try:
        return str(value_node.ToString())
    except genicam.GenericException as exc:
        errors.append(f"value: {exc}")
        return None


def _read_node_constraints(
    value_node: _ValueNode,
    *,
    available: bool,
    interface_type: int,
    errors: list[str],
) -> _NodeConstraints:
    """node型に応じて範囲、刻み、単位、選択肢などを取得する。"""
    if not available:
        return _NodeConstraints()

    try:
        if interface_type == genicam.intfIInteger:
            integer_node = cast("genicam.IInteger", value_node)
            return _NodeConstraints(
                minimum=int(integer_node.GetMin()),
                maximum=int(integer_node.GetMax()),
                increment=int(integer_node.GetInc()),
                unit=str(integer_node.GetUnit()) or None,
            )
        if interface_type == genicam.intfIFloat:
            float_node = cast("genicam.IFloat", value_node)
            return _NodeConstraints(
                minimum=float(float_node.GetMin()),
                maximum=float(float_node.GetMax()),
                increment=float(float_node.GetInc()) if float_node.HasInc() else None,
                unit=str(float_node.GetUnit()) or None,
            )
        if interface_type == genicam.intfIEnumeration:
            enum_node = cast("genicam.IEnumeration", value_node)
            return _NodeConstraints(
                enum_values=tuple(str(item) for item in enum_node.GetSymbolics())
            )
        if interface_type == genicam.intfIString:
            string_node = cast("genicam.IString", value_node)
            return _NodeConstraints(maximum_length=int(string_node.GetMaxLength()))
    except genicam.GenericException as exc:
        errors.append(f"constraints: {exc}")

    return _NodeConstraints()


def _inspect_node(value_node: _ValueNode) -> CameraNodeInfo | None:
    """1個の公開feature nodeを読み取り可能な範囲で調査する。"""
    metadata = value_node.GetNode()
    if not metadata.IsFeature():
        return None

    interface_type = metadata.GetPrincipalInterfaceType()
    implemented = bool(genicam.IsImplemented(value_node))
    available = bool(genicam.IsAvailable(value_node))
    readable = bool(genicam.IsReadable(value_node))
    writable = bool(genicam.IsWritable(value_node))
    errors: list[str] = []
    value = _read_node_value(
        value_node,
        readable=readable,
        interface_type=interface_type,
        errors=errors,
    )
    constraints = _read_node_constraints(
        value_node,
        available=available,
        interface_type=interface_type,
        errors=errors,
    )

    return CameraNodeInfo(
        name=str(metadata.GetName()),
        display_name=str(metadata.GetDisplayName()),
        node_type=_named_constant(interface_type, _INTERFACE_TYPE_NAMES),
        access_mode=_named_constant(value_node.GetAccessMode(), _ACCESS_MODE_NAMES),
        implemented=implemented,
        available=available,
        readable=readable,
        writable=writable,
        visibility=_named_constant(metadata.GetVisibility(), _VISIBILITY_NAMES),
        value=value,
        minimum=constraints.minimum,
        maximum=constraints.maximum,
        increment=constraints.increment,
        unit=constraints.unit,
        enum_values=constraints.enum_values,
        maximum_length=constraints.maximum_length,
        description=str(metadata.GetDescription()),
        errors=tuple(errors),
    )


def _collect_node_infos(nodemap: _NodeMap) -> tuple[CameraNodeInfo, ...]:
    """node mapから公開feature nodeを収集して名前順に並べる。"""
    node_infos = (
        node_info
        for value_node in nodemap.GetNodes()
        if (node_info := _inspect_node(value_node)) is not None
    )
    return tuple(sorted(node_infos, key=lambda item: item.name.casefold()))


def _select_device(
    devices: Sequence[_DeviceInfo],
    serial_number: str | None,
) -> _DeviceInfo:
    """シリアル番号に一致するカメラ、または先頭のカメラを選ぶ。"""
    if not devices:
        msg = "カメラが見つかりません。接続と電源を確認してください。"
        raise RuntimeError(msg)

    if serial_number is None:
        return devices[0]

    for device_info in devices:
        if device_info.GetSerialNumber() == serial_number:
            return device_info

    detected_serials = ", ".join(device.GetSerialNumber() for device in devices)
    msg = (
        f"シリアル番号 {serial_number!r} のカメラが見つかりません。"
        f"検出済み: {detected_serials}"
    )
    raise RuntimeError(msg)


def _camera_info(device_info: _DeviceInfo) -> CameraInfo:
    """pylonのdevice infoを保存用データへ変換する。"""
    return CameraInfo(
        vendor=str(device_info.GetVendorName()),
        model=str(device_info.GetModelName()),
        serial_number=str(device_info.GetSerialNumber()),
        device_class=str(device_info.GetDeviceClass()),
        device_version=str(device_info.GetDeviceVersion()),
        friendly_name=str(device_info.GetFriendlyName()),
    )


def collect_report(serial_number: str | None = None) -> CameraNodeReport:
    """対象カメラを開き、設定を書き換えずにfeature node一覧を取得する。"""
    factory = cast("_TlFactory", pylon.TlFactory.GetInstance())
    device_info = _select_device(list(factory.EnumerateDevices()), serial_number)
    camera = pylon.InstantCamera(factory.CreateDevice(device_info))
    camera.Open()

    try:
        connected_info = cast("_DeviceInfo", camera.GetDeviceInfo())
        nodemap = cast("_NodeMap", camera.GetNodeMap())
        return CameraNodeReport(
            generated_at=datetime.now(UTC).isoformat(),
            camera=_camera_info(connected_info),
            nodes=_collect_node_infos(nodemap),
        )
    finally:
        camera.Close()


def save_report(report: CameraNodeReport, output_path: Path) -> None:
    """nodeレポートをUTF-8のJSONファイルへ保存する。"""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(asdict(report), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _table_cell(value: object, maximum_width: int) -> str:
    """表のセルを1行へ正規化し、長すぎる値を省略する。"""
    text = "" if value is None else " ".join(str(value).split())
    if len(text) <= maximum_width:
        return text
    return f"{text[: maximum_width - 1]}…"


def print_report(report: CameraNodeReport) -> None:
    """カメラ識別情報とnode一覧の主要列を端末へ表示する。"""
    camera = report.camera
    print(
        f"Camera: {camera.model}  serial={camera.serial_number}  "
        f"class={camera.device_class}"
    )

    headers = ("Name", "Type", "Access", "Min", "Max", "Unit", "Value")
    maximum_widths = (44, 12, 13, 16, 16, 12, 36)
    rows = [
        (
            node.name,
            node.node_type,
            node.access_mode,
            node.minimum,
            node.maximum,
            node.unit,
            node.value,
        )
        for node in report.nodes
    ]
    display_rows = [
        tuple(_table_cell(value, limit) for value, limit in zip(row, maximum_widths, strict=True))
        for row in (headers, *rows)
    ]
    column_widths = tuple(
        max(len(row[index]) for row in display_rows) for index in range(len(headers))
    )

    for row_index, row in enumerate(display_rows):
        print("  ".join(value.ljust(column_widths[index]) for index, value in enumerate(row)))
        if row_index == 0:
            print("  ".join("-" * width for width in column_widths))

    print(f"\n{len(report.nodes)} nodes")


def _build_parser() -> argparse.ArgumentParser:
    """コマンドライン引数のparserを生成する。"""
    parser = argparse.ArgumentParser(
        description=(
            "BaslerカメラのGenICam feature nodeを一覧表示し、詳細をJSONへ保存します。"
        )
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help=f"保存先JSONファイル (default: {DEFAULT_OUTPUT_PATH})",
    )
    parser.add_argument(
        "--serial",
        dest="serial_number",
        help="複数台接続時に対象とするカメラのシリアル番号",
    )
    parser.add_argument(
        "--simulate",
        action="store_true",
        help="pylon Camera Emulationを1台有効にしてnodeを取得する",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """node一覧の取得、表示、JSON保存を実行する。"""
    args = _build_parser().parse_args(argv)

    if args.simulate:
        # pylonはTlFactoryの初回アクセス時にエミュレータ台数を読み取る。
        os.environ[CAMERA_EMULATION_ENV_VAR] = "1"

    try:
        report = collect_report(args.serial_number)
        print_report(report)
        save_report(report, args.output)
    except (genicam.GenericException, OSError, RuntimeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(f"Saved: {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
