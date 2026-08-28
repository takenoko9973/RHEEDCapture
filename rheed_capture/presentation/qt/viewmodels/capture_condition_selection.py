"""Sequence系UIで共有する撮影条件の候補値と選択値を管理する。"""

from rheed_capture.domain.capture_condition import CaptureCondition
from rheed_capture.infrastructure.config.schema import (
    filter_existing_float_values,
    filter_existing_int_values,
)


class CaptureConditionSelection:
    """露光時間とゲインの候補・選択状態から撮影条件を生成する。"""

    def __init__(
        self,
        *,
        exposure_ms_values: list[float],
        gain_values: list[int],
        selected_exposure_ms_values: list[float],
        selected_gain_values: list[int],
    ) -> None:
        """候補値と選択値を入力順のまま保持する。"""
        self.exposure_ms_values = list(exposure_ms_values)
        self.gain_values = list(gain_values)
        self.selected_exposure_ms_values = list(selected_exposure_ms_values)
        self.selected_gain_values = list(selected_gain_values)

    def update_candidate_values(
        self,
        exposure_ms_values: list[float],
        gain_values: list[int],
    ) -> None:
        """候補値を置換し、候補から消えた選択値だけを除外する。"""
        self.exposure_ms_values = list(exposure_ms_values)
        self.gain_values = list(gain_values)
        self.selected_exposure_ms_values = filter_existing_float_values(
            self.selected_exposure_ms_values,
            set(self.exposure_ms_values),
        )
        self.selected_gain_values = filter_existing_int_values(
            self.selected_gain_values,
            set(self.gain_values),
        )

    def update_selected_exposure_ms_values(self, selected_values: list[float]) -> None:
        """露光時間の選択値を数値化し、現在の候補内へ絞り込む。"""
        self.selected_exposure_ms_values = filter_existing_float_values(
            [float(value) for value in selected_values],
            set(self.exposure_ms_values),
        )

    def update_selected_gain_values(self, selected_values: list[int]) -> None:
        """ゲインの選択値を数値化し、現在の候補内へ絞り込む。"""
        self.selected_gain_values = filter_existing_int_values(
            [int(value) for value in selected_values],
            set(self.gain_values),
        )

    def build_capture_conditions(self) -> list[CaptureCondition]:
        """選択された露光時間とゲインの直積から撮影条件を生成する。"""
        if not self.selected_exposure_ms_values:
            msg = "露光時間が選択されていません。\n1つ以上の露光時間を選択してください。"
            raise ValueError(msg)
        if not self.selected_gain_values:
            msg = "ゲインが選択されていません。\n1つ以上のゲインを選択してください。"
            raise ValueError(msg)

        return [
            CaptureCondition(exposure_ms=exposure_ms, gain=gain)
            for exposure_ms in self.selected_exposure_ms_values
            for gain in self.selected_gain_values
        ]
