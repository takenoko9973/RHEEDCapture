"""取得統計メーターの振る舞いを検証する。"""

import math
from typing import cast

import pytest

from rheed_capture.domain.acquisition_statistics import (
    DEFAULT_SLIDING_WINDOW_SECONDS,
    AcquisitionStatistics,
    AcquisitionStatisticsMeter,
)


def test_initial_snapshot_has_no_rates() -> None:
    """初期状態では累計件数のみゼロになる。"""
    meter = AcquisitionStatisticsMeter()

    assert meter.snapshot(0.0, include_average=True) == AcquisitionStatistics(
        current_fps=None,
        average_fps=None,
        frame_count=0,
        payload_bytes_per_second=None,
    )


def test_one_frame_has_no_current_fps() -> None:
    """1フレームだけでは時間差からFPSを定義できない。"""
    meter = AcquisitionStatisticsMeter()
    meter.record_frame(0.0, 100)

    statistics = meter.snapshot(0.0, include_average=False)

    assert statistics.current_fps is None
    assert statistics.frame_count == 1
    assert statistics.payload_bytes_per_second is None


def test_evenly_spaced_frames_calculate_current_and_payload_rates() -> None:
    """等間隔サンプルではフレーム間隔の逆数とpayload転送量を返す。"""
    meter = AcquisitionStatisticsMeter()
    for timestamp in (0.0, 0.25, 0.5, 0.75):
        meter.record_frame(timestamp, 1000)

    statistics = meter.snapshot(0.75, include_average=False)

    assert statistics.current_fps == pytest.approx(4.0)
    assert statistics.payload_bytes_per_second == pytest.approx(4000.0)


def test_uneven_samples_use_first_and_last_timestamps() -> None:
    """不均一サンプルでも窓内の先頭末尾からFPSを計算する。"""
    meter = AcquisitionStatisticsMeter()
    for timestamp in (0.0, 0.1, 0.6):
        meter.record_frame(timestamp, 500)

    assert meter.snapshot(0.6, include_average=False).current_fps == pytest.approx(10 / 3)


def test_old_samples_are_excluded_from_current_window() -> None:
    """1秒を超えて古いサンプルは現在値から除外する。"""
    meter = AcquisitionStatisticsMeter()
    meter.record_frame(0.0, 100)
    meter.record_frame(0.5, 200)
    meter.record_frame(1.2, 300)

    statistics = meter.snapshot(1.2, include_average=False)

    assert statistics.current_fps == pytest.approx(1 / 0.7)
    assert statistics.payload_bytes_per_second == pytest.approx(250 / 0.7)
    assert statistics.frame_count == 3


def test_average_fps_uses_reset_start_and_can_be_disabled() -> None:
    """平均FPSはreset時刻から累計し、プレビュー指定では返さない。"""
    meter = AcquisitionStatisticsMeter()
    meter.reset(started_at=10.0)
    meter.record_frame(10.0, 100)
    meter.record_frame(11.0, 100)

    assert meter.snapshot(12.0, include_average=True).average_fps == pytest.approx(1.0)
    assert meter.snapshot(12.0, include_average=False).average_fps is None


def test_reset_clears_samples_and_count() -> None:
    """reset後は以前のサンプルと累計件数を持ち越さない。"""
    meter = AcquisitionStatisticsMeter()
    meter.record_frame(1.0, 100)
    meter.reset(started_at=5.0)

    statistics = meter.snapshot(5.0, include_average=True)

    assert statistics.frame_count == 0
    assert statistics.current_fps is None
    assert statistics.average_fps is None


def test_payload_requires_all_window_samples_to_be_known() -> None:
    """窓内に未知payloadがあれば転送量を算出しない。"""
    meter = AcquisitionStatisticsMeter()
    meter.record_frame(0.0, 100)
    meter.record_frame(0.5, None)
    meter.record_frame(1.0, 300)

    assert meter.snapshot(1.0, include_average=False).payload_bytes_per_second is None


def test_payload_is_none_when_all_window_samples_are_unknown() -> None:
    """窓内payloadがすべて未知の場合も転送量を算出しない。"""
    meter = AcquisitionStatisticsMeter()
    meter.record_frame(0.0, None)
    meter.record_frame(0.5, None)

    assert meter.snapshot(0.5, include_average=False).payload_bytes_per_second is None


def test_payload_is_none_when_current_fps_is_undefined() -> None:
    """現在FPSを定義できない場合はpayload転送量も返さない。"""
    meter = AcquisitionStatisticsMeter()
    meter.record_frame(0.0, 100)
    meter.record_frame(0.0, 200)

    statistics = meter.snapshot(0.0, include_average=False)

    assert statistics.current_fps is None
    assert statistics.payload_bytes_per_second is None


@pytest.mark.parametrize("value", [math.nan, math.inf])
def test_non_finite_record_timestamps_are_rejected(value: float) -> None:
    """時刻のNaN/infや負値payloadを受け入れない。"""
    meter = AcquisitionStatisticsMeter()

    with pytest.raises(ValueError, match="finite"):
        meter.record_frame(value, 100)


@pytest.mark.parametrize("value", [math.nan, math.inf])
def test_non_finite_snapshot_timestamps_are_rejected(value: float) -> None:
    """snapshotのNaN/inf時刻を受け入れない。"""
    meter = AcquisitionStatisticsMeter()

    with pytest.raises(ValueError, match="finite"):
        meter.snapshot(value, include_average=False)


def test_negative_payload_is_rejected() -> None:
    """負のpayloadサイズは不正値として拒否する。"""
    meter = AcquisitionStatisticsMeter()

    with pytest.raises(ValueError, match="non-negative"):
        meter.record_frame(0.0, -1)


@pytest.mark.parametrize("payload_bytes", [True, 1.5])
def test_non_integer_payload_is_rejected(payload_bytes: object) -> None:
    """payloadサイズは整数または未知値だけを受け付ける。"""
    meter = AcquisitionStatisticsMeter()

    with pytest.raises(TypeError):
        meter.record_frame(0.0, cast("int | None", payload_bytes))


def test_timestamp_order_and_start_boundary_are_rejected() -> None:
    """開始時刻より前、または直前のフレームより逆行する時刻を拒否する。"""
    meter = AcquisitionStatisticsMeter()
    meter.reset(started_at=2.0)

    with pytest.raises(ValueError, match="started_at"):
        meter.record_frame(1.9, 100)

    meter.record_frame(2.0, 100)
    meter.record_frame(2.5, 100)
    with pytest.raises(ValueError, match="non-decreasing"):
        meter.record_frame(2.1, 100)

    meter.reset(started_at=0.0)
    meter.record_frame(2.0, 100)
    with pytest.raises(ValueError, match="non-decreasing"):
        meter.snapshot(1.9, include_average=True)


def test_delayed_frame_can_be_recorded_after_newer_snapshot() -> None:
    """取得済みフレームの記録がsnapshotより遅れても受け入れる。"""
    meter = AcquisitionStatisticsMeter()
    meter.record_frame(1.0, 100)
    meter.snapshot(2.0, include_average=False)

    meter.record_frame(1.5, 100)

    with pytest.raises(ValueError, match="non-decreasing"):
        meter.snapshot(1.5, include_average=False)


def test_default_window_constant_is_one_second() -> None:
    """既定窓は仕様どおり1秒である。"""
    assert DEFAULT_SLIDING_WINDOW_SECONDS == 1.0
