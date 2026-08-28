from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, Qt, Signal, Slot

from rheed_capture.infrastructure.config.schema import (
    AppSettingsData,
    SequenceCaptureSettings,
)
from rheed_capture.presentation.qt.viewmodels.capture_condition_selection import (
    CaptureConditionSelection,
)
from rheed_capture.presentation.qt.workers.capture_service import CaptureService

if TYPE_CHECKING:
    from rheed_capture.infrastructure.camera.basler_camera import CameraDevice
    from rheed_capture.infrastructure.storage.experiment_storage import ExperimentStorage


class CaptureViewModel(QObject):
    """Sequence撮影の候補値、選択値、撮影開始を仲介するViewModel。"""

    progress_updated = Signal(int, int, float, int)
    frame_captured = Signal(object)
    sequence_finished = Signal(bool, str)
    error_occurred = Signal(str)

    exposure_values_updated = Signal(object, object)
    gain_values_updated = Signal(object, object)

    def __init__(self, camera: CameraDevice, storage: ExperimentStorage) -> None:
        super().__init__()
        self._camera = camera
        self._storage = storage
        self._capture_service: CaptureService | None = None

        defaults = AppSettingsData()
        # 候補値はSettingsタブと共有、選択値はSequence専用として保持する。
        self._condition_selection = CaptureConditionSelection(
            exposure_ms_values=defaults.exposure_ms_values,
            gain_values=defaults.gain_values,
            selected_exposure_ms_values=(
                defaults.sequence_capture.selected_exposure_ms_values
            ),
            selected_gain_values=defaults.sequence_capture.selected_gain_values,
        )
        self._acquisition_settings = defaults.acquisition

    def load_settings(self, settings: AppSettingsData) -> None:
        self._acquisition_settings = settings.acquisition
        self.update_candidate_values(settings.exposure_ms_values, settings.gain_values)
        self.update_selected_exposure_ms_values(
            settings.sequence_capture.selected_exposure_ms_values
        )
        self.update_selected_gain_values(settings.sequence_capture.selected_gain_values)

    def get_settings_to_save(self) -> SequenceCaptureSettings:
        return SequenceCaptureSettings(
            selected_exposure_ms_values=(
                self._condition_selection.selected_exposure_ms_values
            ),
            selected_gain_values=self._condition_selection.selected_gain_values,
        )

    @Slot(object, object)
    def update_candidate_values(
        self,
        exposure_ms_values: list[float],
        gain_values: list[int],
    ) -> None:
        """候補値の変更をSequence側の選択状態へ反映する。"""
        self._condition_selection.update_candidate_values(
            exposure_ms_values,
            gain_values,
        )
        self._emit_value_state()

    @Slot(list)
    def update_selected_exposure_ms_values(self, selected_values: list[float]) -> None:
        """露光時間チップのクリック結果を保存可能な選択値へ正規化する。"""
        self._condition_selection.update_selected_exposure_ms_values(selected_values)
        self.exposure_values_updated.emit(
            self._condition_selection.exposure_ms_values,
            self._condition_selection.selected_exposure_ms_values,
        )

    @Slot(list)
    def update_selected_gain_values(self, selected_values: list[int]) -> None:
        """ゲインチップのクリック結果を保存可能な選択値へ正規化する。"""
        self._condition_selection.update_selected_gain_values(selected_values)
        self.gain_values_updated.emit(
            self._condition_selection.gain_values,
            self._condition_selection.selected_gain_values,
        )

    @Slot()
    def start_sequence(self) -> None:
        try:
            # 撮影開始直前に、選択値の直積を最終的な撮影条件へ解決する。
            conditions = self._condition_selection.build_capture_conditions()
        except ValueError as e:
            self.error_occurred.emit(str(e))
            self.sequence_finished.emit(False, "")
            return

        self._capture_service = CaptureService(
            self._camera,
            self._storage,
            conditions,
            self._acquisition_settings,
        )
        self._capture_service.progress_update.connect(self.progress_updated)
        # Preview受信側はmailbox投入だけなので、Raw frameをGUI eventへ蓄積しない。
        self._capture_service.frame_captured.connect(
            self.frame_captured,
            Qt.ConnectionType.DirectConnection,
        )
        self._capture_service.sequence_finished.connect(self.sequence_finished)
        self._capture_service.error_occurred.connect(self.error_occurred)
        self._capture_service.start()

    @Slot()
    def cancel_sequence(self) -> None:
        if self.is_running() and self._capture_service:
            self._capture_service.cancel()

    def is_running(self) -> bool:
        return self._capture_service is not None and self._capture_service.isRunning()

    def _emit_value_state(self) -> None:
        """候補値と選択値をセットでViewへ通知する。"""
        self.exposure_values_updated.emit(
            self._condition_selection.exposure_ms_values,
            self._condition_selection.selected_exposure_ms_values,
        )
        self.gain_values_updated.emit(
            self._condition_selection.gain_values,
            self._condition_selection.selected_gain_values,
        )
