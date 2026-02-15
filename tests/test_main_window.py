import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from pytestqt.qtbot import QtBot

from rheed_capture.models.hardware.camera_device import CameraDevice
from rheed_capture.models.io.storage import ExperimentStorage
from rheed_capture.views.main_window import MainWindow


@pytest.fixture
def mock_camera() -> MagicMock:
    """カメラデバイスのモックフィクスチャ"""
    camera = MagicMock(spec=CameraDevice)

    # テストスレッドが無限ループでフリーズするのを防ぐため、即座にNoneを返さず少しだけ待機させる
    def mock_retrieve(*args, **kwargs) -> None:  # noqa: ARG001
        time.sleep(0.01)  # noqa: F821

    # プレビュー取得時にNoneを返し、処理エラーによる QMessageBox(エラーダイアログ) の表示を防ぐ
    camera.retrieve_preview_frame.return_value = mock_retrieve
    camera.get_exposure_bounds.return_value = (1, 10000)
    camera.get_gain_bounds.return_value = (0, 48)
    return camera


@pytest.fixture
def mock_storage() -> MagicMock:
    """ストレージ管理のモックフィクスチャ"""
    storage = MagicMock(spec=ExperimentStorage)
    storage.root_dir = Path("dummy/root")

    mock_dir = MagicMock(spec=Path)
    mock_dir.name = "260215"
    storage.get_current_experiment_dir.return_value = mock_dir

    # 新機能: ブランチ更新のモック
    storage.increment_branch.return_value = "260215-2"
    return storage


@pytest.fixture
def mock_settings() -> types.GeneratorType:
    """設定保存/復元 (AppSettings) のモック"""
    with patch("rheed_capture.views.main_window.AppSettings") as mock_app_settings:
        # ロード時に返すダミー設定
        mock_app_settings.load.return_value = {
            "root_dir": "dummy/root",
            "preview_exp": 15.5,
            "preview_gain": 2.0,
            "seq_exp_list": "10, 20",
            "seq_gain_list": "0, 1",
            "enable_clahe": True,
        }
        yield mock_app_settings


@pytest.fixture(autouse=True)
def mock_preview_worker() -> types.GeneratorType:
    """
    すべてのテストで自動適用されるPreviewWorkerのモック。
    MainWindow初期化時にQThreadが実際にスタートし、テストがハングするのを防ぐ。
    """
    with patch("rheed_capture.views.main_window.PreviewWorker") as mock_worker_class:
        mock_worker_instance = MagicMock()
        mock_worker_class.return_value = mock_worker_instance
        yield


def test_main_window_initialization_and_settings_load(
    qtbot: QtBot,
    mock_camera: MagicMock,
    mock_storage: MagicMock,
    mock_settings: MagicMock,
) -> None:
    """初期化時に設定ファイルが読み込まれ、UIに反映されているかテスト"""
    window = MainWindow(camera=mock_camera, storage=mock_storage)
    qtbot.addWidget(window)

    # AppSettings.load が呼ばれたか
    mock_settings.load.assert_called_once()

    # 読み込んだ設定がUIコンポーネントに反映されているか
    assert window.spin_preview_exp.value() == 15.5
    assert window.spin_preview_gain.value() == 2.0
    assert window.edit_seq_exp.text() == "10, 20"
    assert window.chk_processing.isChecked() is True

    window.close()


def test_slider_and_spinbox_sync(
    qtbot: QtBot,
    mock_camera: MagicMock,
    mock_storage: MagicMock,
) -> None:
    """スライダー(整数)とスピンボックス(小数)の双方向同期テスト"""
    window = MainWindow(camera=mock_camera, storage=mock_storage)
    qtbot.addWidget(window)

    # 1. SpinBox -> Slider の同期テスト (小数 -> 100倍の整数)
    window.spin_preview_exp.setValue(50.25)
    assert window.slider_exp.value() == 5025
    mock_camera.set_exposure.assert_called_with(50.25)

    # 2. Slider -> SpinBox の同期テスト (整数 -> 100で割った小数)
    window.slider_gain.setValue(150)  # 1.5 を意味する
    assert window.spin_preview_gain.value() == 1.5
    mock_camera.set_gain.assert_called_with(1.5)

    window.close()


def test_branch_update_logic(
    qtbot: QtBot,
    mock_camera: MagicMock,
    mock_storage: MagicMock,
) -> None:
    """ブランチ(-n)の更新ボタンのロジックテスト"""
    window = MainWindow(camera=mock_camera, storage=mock_storage)
    qtbot.addWidget(window)

    # UIテストで邪魔になるQMessageBoxをモック化して非表示にする
    with patch("rheed_capture.views.main_window.QMessageBox.information") as mock_msg:
        # 新規ブランチボタンのクリックをシミュレート
        window._on_new_branch()  # noqa: SLF001

        # storageのブランチ更新メソッドが呼ばれたか
        mock_storage.increment_branch.assert_called_once()

        # ユーザーへの完了通知メッセージが出たか
        mock_msg.assert_called_once()

    window.close()


def test_settings_save_on_close(
    qtbot: QtBot,
    mock_camera: MagicMock,
    mock_storage: MagicMock,
    mock_settings: MagicMock,
) -> None:
    """ウィンドウを閉じる際に現在のUI状態が保存されるかテスト"""
    window = MainWindow(camera=mock_camera, storage=mock_storage)
    qtbot.addWidget(window)

    # UIの値を一部変更する
    window.spin_preview_exp.setValue(99.9)
    window.chk_processing.setChecked(False)

    # ウィンドウを閉じる (closeEventをトリガー)
    window.close()

    # AppSettings.save が呼ばれたか
    mock_settings.save.assert_called_once()

    # 保存された辞書の中身を検証
    saved_data = mock_settings.save.call_args[0][0]
    assert saved_data["preview_exp"] == 99.9
    assert saved_data["enable_clahe"] is False
    assert "root_dir" in saved_data
    assert "seq_exp_list" in saved_data

    window.close()
