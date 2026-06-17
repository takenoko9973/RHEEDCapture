from __future__ import annotations

from typing import Literal

# UI、設定ファイル、実行計画で共有する角度走査の基本制約。
MIN_ANGLE_INTERVAL_DEG = 0.5
MAX_SCAN_ANGLE_DEG = 90.0
ANGLE_EPSILON = 1e-9

AngleScanDirection = Literal["positive", "negative", "both"]
VALID_ANGLE_SCAN_DIRECTIONS: set[str] = {"positive", "negative", "both"}


def validate_interval(interval_deg: float) -> None:
    """角度間隔がアプリ全体の条件を満たすか検証する。"""
    if interval_deg <= 0:
        msg = "角度間隔は正の値にしてください。"
        raise ValueError(msg)

    if interval_deg < MIN_ANGLE_INTERVAL_DEG:
        msg = "角度間隔は0.5deg以上の正の値にしてください。"
        raise ValueError(msg)


def validate_range(range_deg: float) -> None:
    """走査範囲がアプリ全体の条件を満たすか検証する。"""
    if range_deg <= 0:
        msg = "走査範囲は正の値にしてください。"
        raise ValueError(msg)

    if range_deg > MAX_SCAN_ANGLE_DEG:
        msg = "走査範囲は90deg以下で指定してください。"
        raise ValueError(msg)


def validate_interval_within_range(range_deg: float, interval_deg: float) -> None:
    """角度間隔が走査範囲を超えていないか検証する。"""
    if interval_deg - range_deg > ANGLE_EPSILON:
        msg = "角度間隔は走査範囲以下にしてください。"
        raise ValueError(msg)


def validate_direction(direction: str) -> None:
    """走査方向が保存形式とUIで扱える値か検証する。"""
    if direction not in VALID_ANGLE_SCAN_DIRECTIONS:
        msg = "走査方向はpositive, negative, bothのいずれかにしてください。"
        raise ValueError(msg)
