"""Sequence ViewModelのUI状態とService境界を検証する。"""

from unittest.mock import MagicMock, patch

from PySide6.QtCore import Qt
from pytestqt.qtbot import QtBot

from rheed_capture.infrastructure.config.schema import (
    AcquisitionSettings,
    AppSettingsData,
    SequenceCaptureSettings,
)
from rheed_capture.presentation.qt.viewmodels.sequence import CaptureViewModel


def test_candidate_update_emits_filtered_selection_without_automatic_fill(
    qtbot: QtBot,
) -> None:
    """候補更新signalは候補外を除き、空選択を自動補充せず通知する。"""
    view_model = CaptureViewModel(MagicMock(), MagicMock())
    view_model.load_settings(
        AppSettingsData(
            exposure_ms_values=[10.0, 20.0],
            gain_values=[0, 1],
            sequence_capture=SequenceCaptureSettings(
                selected_exposure_ms_values=[20.0],
                selected_gain_values=[1],
            ),
        )
    )

    with (
        qtbot.waitSignal(view_model.exposure_values_updated) as exposure_signal,
        qtbot.waitSignal(view_model.gain_values_updated) as gain_signal,
    ):
        view_model.update_candidate_values([10.0], [0])

    assert exposure_signal.args == [[10.0], []]
    assert gain_signal.args == [[0], []]
    assert view_model.get_settings_to_save() == SequenceCaptureSettings(
        selected_exposure_ms_values=[],
        selected_gain_values=[],
    )


def test_start_sequence_passes_ordered_product_and_uses_direct_frame_connection(
    qtbot: QtBot,
) -> None:
    """開始時は入力順の直積と取得設定を渡し、frameをDirect接続する。"""
    _ = qtbot
    camera = MagicMock()
    storage = MagicMock()
    acquisition = AcquisitionSettings(accumulation_frames=3)
    view_model = CaptureViewModel(camera, storage)
    view_model.load_settings(
        AppSettingsData(
            exposure_ms_values=[20.0, 10.0],
            gain_values=[2, 1],
            sequence_capture=SequenceCaptureSettings(
                selected_exposure_ms_values=[20.0, 10.0],
                selected_gain_values=[2, 1],
            ),
            acquisition=acquisition,
        )
    )
    service = MagicMock()

    with patch(
        "rheed_capture.presentation.qt.viewmodels.sequence.CaptureService",
        return_value=service,
    ) as service_class:
        view_model.start_sequence()

    conditions = service_class.call_args.args[2]
    assert [(condition.exposure_ms, condition.gain) for condition in conditions] == [
        (20.0, 2),
        (20.0, 1),
        (10.0, 2),
        (10.0, 1),
    ]
    assert service_class.call_args.args[:2] == (camera, storage)
    assert service_class.call_args.args[3] == acquisition
    service.frame_captured.connect.assert_called_once_with(
        view_model.frame_captured,
        Qt.ConnectionType.DirectConnection,
    )
    service.start.assert_called_once_with()
