"""
AZD-CDへ接続した状態で低レベル制御を行うDriver。

Driverはシリアルポートを保持し、Modbus RTUの読み書きと
AZD-CD固有レジスタの基本操作だけを担当する。
角度指定、完了待ち、操作ごとの自動接続/切断はAdapter側の責務。
"""

from __future__ import annotations

import importlib
import logging
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, Self, cast

from .protocol import (
    FUNCTION_READ_HOLDING_REGISTERS,
    INPUT_COMMAND_REGISTER,
    INPUT_START,
    OPERATION_TYPE_REGISTER,
    OUTPUT_STATUS_REGISTER,
    POSITION_REGISTER,
    SPEED_REGISTER,
    STATUS_ALM_A,
    STATUS_IN_POS,
    STATUS_INFO,
    STATUS_MOVE,
    STATUS_READY,
    STATUS_SYS_BUSY,
    read_holding_registers_frame,
    with_crc,
    write_i32_frame,
    write_u16_frame,
)

if TYPE_CHECKING:
    from types import ModuleType


logger = logging.getLogger(__name__)


class SerialPort(Protocol):
    dtr: bool
    rts: bool

    def close(self) -> None: ...

    def flush(self) -> None: ...

    def read(self, size: int = 1) -> bytes: ...

    def reset_input_buffer(self) -> None: ...

    def reset_output_buffer(self) -> None: ...

    def write(self, data: bytes) -> int | None: ...


@dataclass(frozen=True)
class AzdCdConfig:
    """AZD-CDへ接続するための通信設定。"""

    port: str
    slave: int

    baudrate: int = 115200
    parity: str = "E"
    stopbits: int = 1
    timeout: float = 1.0

    start_ack_timeout: float = 1.0
    inter_frame_delay: float = 0.05

    rts_control: bool = False
    rts_active_level: bool = True
    rts_before_delay: float = 0.005
    rts_after_delay: float = 0.005


@dataclass(frozen=True)
class AzdCdStatus:
    """0x007E-0x007Fから読み取ったドライバ出力状態。"""

    upper_word: int
    lower_word: int

    @classmethod
    def from_words(cls, upper_word: int, lower_word: int) -> AzdCdStatus:
        """読み出した2ワードから状態オブジェクトを作る。"""
        return cls(upper_word=upper_word, lower_word=lower_word)

    def has(self, mask: int) -> bool:
        """下位ワードの指定bitがONかどうかを返す。"""
        return bool(self.lower_word & mask)

    @property
    def ready(self) -> bool:
        """運転準備完了ならTrue。"""
        return self.has(STATUS_READY)

    @property
    def info(self) -> bool:
        """INFO出力がONならTrue。"""
        return self.has(STATUS_INFO)

    @property
    def alarm_a(self) -> bool:
        """ALM-A出力がONならTrue。"""
        return self.has(STATUS_ALM_A)

    @property
    def sys_busy(self) -> bool:
        """SYS-BSY出力がONならTrue。"""
        return self.has(STATUS_SYS_BUSY)

    @property
    def moving(self) -> bool:
        """MOVE出力がON、つまりモーター動作中ならTrue。"""
        return self.has(STATUS_MOVE)

    @property
    def in_pos(self) -> bool:
        """IN-POS出力がONならTrue。"""
        return self.has(STATUS_IN_POS)

    def format_bits(self) -> str:
        """人が読むための主要bit一覧を文字列にする。"""
        flags = [
            ("READY", self.ready),
            ("MOVE", self.moving),
            ("IN-POS", self.in_pos),
            ("SYS-BSY", self.sys_busy),
            ("INFO", self.info),
            ("ALM-A", self.alarm_a),
        ]
        return ", ".join(
            f"{name}={'ON' if enabled else 'OFF'}" for name, enabled in flags
        )


class AzdCdDriver:
    """接続済みシリアルポートを所有する低レベルDriver。"""

    def __init__(self, config: AzdCdConfig) -> None:
        """シリアルポートを開いて、送受信バッファを初期化する。"""
        self.config = config
        self.serial: SerialPort = self._open_serial(config)

        self.serial.dtr = True
        self.serial.rts = not config.rts_active_level if config.rts_control else False
        self.serial.reset_input_buffer()
        self.serial.reset_output_buffer()

    def _open_serial(self, config: AzdCdConfig) -> SerialPort:
        """pyserialのSerialインスタンスを作る。"""
        serial_module = importlib.import_module("serial")

        try:
            serial_port = serial_module.Serial(
                port=config.port,
                baudrate=config.baudrate,
                bytesize=serial_module.EIGHTBITS,
                parity=self._serial_parity(serial_module, config.parity),
                stopbits=self._serial_stopbits(serial_module, config.stopbits),
                timeout=config.timeout,
                write_timeout=config.timeout,
                xonxoff=False,
                rtscts=False,
                dsrdtr=False,
            )
        except (OSError, RuntimeError) as e:
            msg = (
                f"モーターのCOMポート '{config.port}' を開けませんでした。"
                "接続先のポート番号を確認してください。"
                "実機なしで動作確認する場合は Motor Port に MOCK を入力してください。"
            )
            raise RuntimeError(msg) from e

        return cast("SerialPort", serial_port)

    def _serial_parity(self, serial_module: ModuleType, parity: str) -> str:
        """設定文字からpyserialのparity定数へ変換する。"""
        parities = {
            "N": serial_module.PARITY_NONE,
            "E": serial_module.PARITY_EVEN,
            "O": serial_module.PARITY_ODD,
        }

        return str(parities[parity])

    def _serial_stopbits(self, serial_module: ModuleType, stopbits: int) -> int:
        """設定値からpyserialのstopbits定数へ変換する。"""
        values = {
            1: serial_module.STOPBITS_ONE,
            2: serial_module.STOPBITS_TWO,
        }

        return int(values[stopbits])

    def close(self) -> None:
        """保持しているシリアルポートを閉じる。"""
        self.serial.close()

    def __enter__(self) -> Self:
        """`with AzdCdDriver(...) as driver:` で使うための入口。"""
        return self

    def __exit__(self, *_exc: object) -> None:
        """withブロックを抜けるときに必ずポートを閉じる。"""
        self.close()

    def transact(self, frame: bytes, expected_length: int) -> bytes:
        """1つのModbus RTU要求を送信し、応答を検証して返す。"""
        self.serial.reset_input_buffer()
        logger.debug("TX: %s", frame.hex(" ").upper())

        self._begin_transmit()

        try:
            self._write_frame(frame)
        finally:
            self._end_transmit(frame)

        response = self._read_response(expected_length)
        self._validate_response_crc(response)

        return response

    def _begin_transmit(self) -> None:
        """手動RTS制御が有効な場合、送信可能状態へ切り替える。"""
        if self.config.rts_control:
            self.serial.rts = self.config.rts_active_level
            time.sleep(self.config.rts_before_delay)

    def _write_frame(self, frame: bytes) -> None:
        """送信フレームを書き込み、OS側の送信キューをflushする。"""
        self.serial.write(frame)
        self.serial.flush()

    def _end_transmit(self, frame: bytes) -> None:
        """手動RTS制御が有効な場合、送信完了を待って受信状態へ戻す。"""
        if not self.config.rts_control:
            return

        time.sleep(self._wire_time_seconds(len(frame)) + self.config.rts_after_delay)
        self.serial.rts = not self.config.rts_active_level

    def _read_response(self, expected_length: int) -> bytes:
        """指定長の応答を読み取る。長さ不足ならタイムアウトとして扱う。"""
        response = self.serial.read(expected_length)
        logger.debug("RX: %s", response.hex(" ").upper() if response else "(none)")

        if len(response) != expected_length:
            msg = (
                f"response timeout: expected {expected_length} bytes, got {len(response)} "
                f"({response.hex(' ').upper()})"
            )
            raise TimeoutError(msg)

        return response

    def _validate_response_crc(self, response: bytes) -> None:
        """応答フレーム末尾のCRCが正しいか確認する。"""
        if response[-2:] != with_crc(response[:-2])[-2:]:
            msg = f"CRC mismatch in response: {response.hex(' ').upper()}"
            raise ValueError(msg)

    def _wire_time_seconds(self, byte_count: int) -> float:
        """指定byte数の送信にかかる理論時間を秒で返す。"""
        parity_bits = 0 if self.config.parity == "N" else 1
        bits_per_byte = 1 + 8 + parity_bits + self.config.stopbits

        return byte_count * bits_per_byte / self.config.baudrate

    def write_u16(self, register: int, value: int) -> bytes:
        """16bitレジスタを1つ書き込む。"""
        frame = write_u16_frame(self.config.slave, register, value)
        response = self.transact(frame, expected_length=8)

        if response != frame:
            msg = (
                f"unexpected write_u16 response: sent {frame.hex(' ').upper()}, "
                f"got {response.hex(' ').upper()}"
            )
            raise ValueError(msg)

        time.sleep(self.config.inter_frame_delay)

        return response

    def write_i32(self, register: int, value: int) -> bytes:
        """連続する2レジスタへ符号付き32bit値を書き込む。"""
        frame = write_i32_frame(self.config.slave, register, value)
        response = self.transact(frame, expected_length=8)
        expected = with_crc(frame[:6])

        if response != expected:
            msg = (
                f"unexpected write_i32 response: expected {expected.hex(' ').upper()}, "
                f"got {response.hex(' ').upper()}"
            )
            raise ValueError(msg)

        time.sleep(self.config.inter_frame_delay)

        return response

    def read_holding_registers(self, register: int, count: int) -> list[int]:
        """保持レジスタを指定数だけ読み取る。"""
        frame = read_holding_registers_frame(self.config.slave, register, count)
        response = self.transact(frame, expected_length=5 + count * 2)

        if (
            response[0] != self.config.slave
            or response[1] != FUNCTION_READ_HOLDING_REGISTERS
            or response[2] != count * 2
        ):
            msg = f"unexpected read response: {response.hex(' ').upper()}"
            raise ValueError(msg)

        values = self._decode_register_values(response, count)

        time.sleep(self.config.inter_frame_delay)

        return values

    def _decode_register_values(self, response: bytes, count: int) -> list[int]:
        """Modbus応答ペイロードから16bitレジスタ値のリストを取り出す。"""
        values = []

        for index in range(count):
            offset = 3 + index * 2
            values.append(int.from_bytes(response[offset : offset + 2], "big"))

        return values

    def read_status(self) -> AzdCdStatus:
        """ドライバ出力状態を読み取って、扱いやすい状態オブジェクトへ変換する。"""
        upper_word, lower_word = self.read_holding_registers(OUTPUT_STATUS_REGISTER, 2)

        return AzdCdStatus.from_words(upper_word, lower_word)

    def set_operation_type(self, operation_type: int) -> None:
        """運転方式レジスタを設定する。"""
        self.write_i32(OPERATION_TYPE_REGISTER, operation_type)

    def set_speed_units(self, speed_units: int) -> None:
        """速度レジスタをドライバ内部単位で設定する。"""
        self.write_i32(SPEED_REGISTER, speed_units)

    def set_position_units(self, position_units: int) -> None:
        """位置レジスタをドライバ内部単位で設定する。"""
        self.write_i32(POSITION_REGISTER, position_units)

    def start_on(self) -> None:
        """START入力をONにする。"""
        self.write_u16(INPUT_COMMAND_REGISTER, INPUT_START)

    def start_off(self) -> None:
        """START入力をOFFに戻す。"""
        self.write_u16(INPUT_COMMAND_REGISTER, 0x0000)
