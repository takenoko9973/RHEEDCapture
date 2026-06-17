"""
AZD-CDで使うModbus RTUフレームとレジスタ定数。

このモジュールは通信フレームの形だけを扱う。
シリアルポートの開閉や、モーターをどう動かすかの判断は行わない。
"""

from __future__ import annotations

INPUT_COMMAND_REGISTER = 0x007D
OUTPUT_STATUS_REGISTER = 0x007E
FUNCTION_READ_HOLDING_REGISTERS = 0x03

POSITION_REGISTER = 0x0400
SPEED_REGISTER = 0x0480
OPERATION_TYPE_REGISTER = 0x0500

OP_RELATIVE_POSITIONING = 0x00000002
INPUT_START = 0x0008

STATUS_READY = 1 << 5
STATUS_INFO = 1 << 6
STATUS_ALM_A = 1 << 7
STATUS_SYS_BUSY = 1 << 8
STATUS_MOVE = 1 << 13
STATUS_IN_POS = 1 << 14


def modbus_crc(payload: bytes) -> int:
    """Modbus RTUのCRC-16を計算する。"""
    crc = 0xFFFF

    for byte in payload:
        crc ^= byte

        for _ in range(8):
            if crc & 0x0001:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1

    return crc & 0xFFFF


def with_crc(payload: bytes) -> bytes:
    """CRCを付けたModbus RTUフレームを返す。"""
    crc = modbus_crc(payload)

    return payload + crc.to_bytes(2, "little")


def write_u16_frame(slave: int, register: int, value: int) -> bytes:
    """単一保持レジスタへ16bit値を書き込むフレームを作る。"""
    payload = bytes(
        [
            slave,
            0x06,
            (register >> 8) & 0xFF,
            register & 0xFF,
            (value >> 8) & 0xFF,
            value & 0xFF,
        ]
    )

    return with_crc(payload)


def write_i32_frame(slave: int, register: int, value: int) -> bytes:
    """連続する2レジスタへ符号付き32bit値を書き込むフレームを作る。"""
    raw_value = value.to_bytes(4, "big", signed=True)

    payload = bytes(
        [
            slave,
            0x10,
            (register >> 8) & 0xFF,
            register & 0xFF,
            0x00,
            0x02,
            0x04,
        ]
    ) + raw_value

    return with_crc(payload)


def read_holding_registers_frame(slave: int, register: int, count: int) -> bytes:
    """保持レジスタを読み出すフレームを作る。"""
    payload = bytes(
        [
            slave,
            0x03,
            (register >> 8) & 0xFF,
            register & 0xFF,
            (count >> 8) & 0xFF,
            count & 0xFF,
        ]
    )

    return with_crc(payload)
