from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, Signal, Slot

from rheed_capture.domain.capture_condition import CaptureCondition
from rheed_capture.infrastructure.config.schema import (
    AppSettingsData,
    SequenceCaptureSettings,
    filter_existing_float_values,
    filter_existing_int_values,
)
from rheed_capture.presentation.qt.workers.capture_service import CaptureService

if TYPE_CHECKING:
    from rheed_capture.infrastructure.camera.basler_camera import CameraDevice
    from rheed_capture.infrastructure.storage.experiment_storage import ExperimentStorage


class CaptureViewModel(QObject):
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
        self._exposure_ms_values = defaults.exposure_ms_values
        self._gain_values = defaults.gain_values
        self._selected_exposure_ms_values = (
            defaults.sequence_capture.selected_exposure_ms_values
        )
        self._selected_gain_values = defaults.sequence_capture.selected_gain_values

    def load_settings(self, settings: AppSettingsData) -> None:
        self.update_candidate_values(settings.exposure_ms_values, settings.gain_values)
        self.update_selected_exposure_ms_values(
            settings.sequence_capture.selected_exposure_ms_values
        )
        self.update_selected_gain_values(settings.sequence_capture.selected_gain_values)

    def get_settings_to_save(self) -> SequenceCaptureSettings:
        return SequenceCaptureSettings(
            selected_exposure_ms_values=self._selected_exposure_ms_values,
            selected_gain_values=self._selected_gain_values,
        )

    @Slot(object, object)
    def update_candidate_values(
        self,
        exposure_ms_values: list[float],
        gain_values: list[int],
    ) -> None:
        self._exposure_ms_values = list(exposure_ms_values)
        self._gain_values = list(gain_values)
        self._selected_exposure_ms_values = filter_existing_float_values(
            self._selected_exposure_ms_values,
            set(self._exposure_ms_values),
        )
        self._selected_gain_values = filter_existing_int_values(
            self._selected_gain_values,
            set(self._gain_values),
        )
        self._emit_value_state()

    @Slot(list)
    def update_selected_exposure_ms_values(self, selected_values: list[float]) -> None:
        self._selected_exposure_ms_values = filter_existing_float_values(
            [float(value) for value in selected_values],
            set(self._exposure_ms_values),
        )
        self.exposure_values_updated.emit(
            self._exposure_ms_values,
            self._selected_exposure_ms_values,
        )

    @Slot(list)
    def update_selected_gain_values(self, selected_values: list[int]) -> None:
        self._selected_gain_values = filter_existing_int_values(
            [int(value) for value in selected_values],
            set(self._gain_values),
        )
        self.gain_values_updated.emit(self._gain_values, self._selected_gain_values)

    @Slot()
    def start_sequence(self) -> None:
        try:
            conditions = self._build_capture_conditions()
        except ValueError as e:
            self.error_occurred.emit(str(e))
            self.sequence_finished.emit(False, "")
            return

        self._capture_service = CaptureService(self._camera, self._storage, conditions)
        self._capture_service.progress_update.connect(self.progress_updated)
        self._capture_service.frame_captured.connect(self.frame_captured)
        self._capture_service.sequence_finished.connect(self.sequence_finished)
        self._capture_service.error_occurred.connect(self.error_occurred)
        self._capture_service.start()

    @Slot()
    def cancel_sequence(self) -> None:
        if self.is_running() and self._capture_service:
            self._capture_service.cancel()

    def is_running(self) -> bool:
        return self._capture_service is not None and self._capture_service.isRunning()

    def _build_capture_conditions(self) -> list[CaptureCondition]:
        if not self._selected_exposure_ms_values:
            msg = "露光時間が選択されていません。\n1つ以上の露光時間を選択してください。"
            raise ValueError(msg)
        if not self._selected_gain_values:
            msg = "ゲインが選択されていません。\n1つ以上のゲインを選択してください。"
            raise ValueError(msg)

        return [
            CaptureCondition(exposure_ms=exposure_ms, gain=gain)
            for exposure_ms in self._selected_exposure_ms_values
            for gain in self._selected_gain_values
        ]

    def _emit_value_state(self) -> None:
        self.exposure_values_updated.emit(
            self._exposure_ms_values,
            self._selected_exposure_ms_values,
        )
        self.gain_values_updated.emit(self._gain_values, self._selected_gain_values)
