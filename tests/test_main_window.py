from unittest.mock import MagicMock

import pytest
from pytestqt.qtbot import QtBot

from rheed_capture.core.camera_device import CameraDevice
from rheed_capture.core.storage import ExperimentStorage
from rheed_capture.ui.main_window import MainWindow


@pytest.fixture
def mock_camera() -> MagicMock:
    """カメラデバイスのモックフィクスチャ"""
    camera = MagicMock(spec=CameraDevice)
    # プレビュー取得時にNoneを返し、処理エラーによる QMessageBox(エラーダイアログ) の表示を防ぐ
    camera.retrieve_preview_frame.return_value = None
    return camera


@pytest.fixture
def mock_storage() -> MagicMock:
    """ストレージ管理のモックフィクスチャ"""
    return MagicMock(spec=ExperimentStorage)


def test_main_window_initialization(
    qtbot: QtBot, mock_camera: MagicMock, mock_storage: MagicMock
) -> None:
    """メインウィンドウが正常に初期化され、UI要素が存在するかテスト"""
    window = MainWindow(camera=mock_camera, storage=mock_storage)
    qtbot.addWidget(window)

    # プレビュー表示用ラベルが存在するか
    assert window.image_label is not None

    # 初期化時にプレビュー開始が呼ばれているか
    mock_camera.start_preview_grab.assert_called_once()
    assert window.preview_worker.isRunning()

    # テスト終了時にウィンドウを閉じ、スレッドを停止させる
    window.close()


def test_preview_parameter_changes(
    qtbot: QtBot, mock_camera: MagicMock, mock_storage: MagicMock
) -> None:
    """UIからのパラメータ変更がカメラに伝わるかテスト"""
    window = MainWindow(camera=mock_camera, storage=mock_storage)
    qtbot.addWidget(window)

    # 露光時間を変更 (スピンボックスの値をセット)
    window.spin_preview_exp.setValue(50.0)
    # 値変更シグナルによってカメラのset_exposureが呼ばれるはず
    mock_camera.set_exposure.assert_called_with(50.0)

    # 処理のON/OFF
    window.chk_processing.setChecked(True)
    assert window.preview_worker.enable_processing is True

    window.close()


def test_parse_sequence_inputs(
    qtbot: QtBot, mock_camera: MagicMock, mock_storage: MagicMock
) -> None:
    """カンマ区切りの文字列入力が正しくリストに変換されるかテスト"""
    window = MainWindow(camera=mock_camera, storage=mock_storage)
    qtbot.addWidget(window)

    window.edit_seq_exp.setText("10, 20.5, 30")
    window.edit_seq_gain.setText("0, 1")

    exp_list, gain_list = window._parse_sequence_inputs()  # noqa: SLF001
    assert exp_list == [10.0, 20.5, 30.0]
    assert gain_list == [0.0, 1.0]

    window.close()
