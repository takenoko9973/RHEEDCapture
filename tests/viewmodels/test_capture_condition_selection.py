"""Sequence系ViewModelで共有する撮影条件選択状態を検証する。"""

import pytest

from rheed_capture.presentation.qt.viewmodels.capture_condition_selection import (
    CaptureConditionSelection,
)


def test_candidate_update_filters_selection_without_reordering_or_filling() -> None:
    """候補更新は候補外だけを除き、選択順と重複を保持して自動補充しない。"""
    selection = CaptureConditionSelection(
        exposure_ms_values=[10.0, 20.0, 30.0],
        gain_values=[0, 1, 2],
        selected_exposure_ms_values=[20.0, 20.0, 30.0],
        selected_gain_values=[2, 0, 2],
    )

    selection.update_candidate_values([20.0, 10.0, 20.0], [2, 1, 2])

    assert selection.exposure_ms_values == [20.0, 10.0, 20.0]
    assert selection.gain_values == [2, 1, 2]
    assert selection.selected_exposure_ms_values == [20.0, 20.0]
    assert selection.selected_gain_values == [2, 2]


def test_selected_values_are_filtered_and_keep_order_and_duplicates() -> None:
    """UI選択値は候補内へ絞り、入力順と重複を保持する。"""
    selection = CaptureConditionSelection(
        exposure_ms_values=[10.0, 20.0],
        gain_values=[0, 1],
        selected_exposure_ms_values=[],
        selected_gain_values=[],
    )

    selection.update_selected_exposure_ms_values([20.0, 10.0, 20.0, 99.0])
    selection.update_selected_gain_values([1, 0, 1, 9])

    assert selection.selected_exposure_ms_values == [20.0, 10.0, 20.0]
    assert selection.selected_gain_values == [1, 0, 1]


def test_capture_conditions_use_exposure_outer_gain_inner_product() -> None:
    """撮影条件は露光時間を外側、ゲインを内側にした直積で生成する。"""
    selection = CaptureConditionSelection(
        exposure_ms_values=[20.0, 10.0],
        gain_values=[2, 1],
        selected_exposure_ms_values=[20.0, 10.0, 20.0],
        selected_gain_values=[2, 1],
    )

    conditions = selection.build_capture_conditions()

    assert [(condition.exposure_ms, condition.gain) for condition in conditions] == [
        (20.0, 2),
        (20.0, 1),
        (10.0, 2),
        (10.0, 1),
        (20.0, 2),
        (20.0, 1),
    ]


@pytest.mark.parametrize(
    ("selected_exposure_ms_values", "selected_gain_values", "message"),
    [
        ([], [0], "露光時間が選択されていません。\n1つ以上の露光時間を選択してください。"),
        ([10.0], [], "ゲインが選択されていません。\n1つ以上のゲインを選択してください。"),
    ],
)
def test_capture_conditions_reject_empty_selection(
    selected_exposure_ms_values: list[float],
    selected_gain_values: list[int],
    message: str,
) -> None:
    """露光時間またはゲインが未選択なら既存の利用者向けエラーを返す。"""
    selection = CaptureConditionSelection(
        exposure_ms_values=[10.0],
        gain_values=[0],
        selected_exposure_ms_values=selected_exposure_ms_values,
        selected_gain_values=selected_gain_values,
    )

    with pytest.raises(ValueError, match=message.replace("\n", r"\n")):
        selection.build_capture_conditions()
