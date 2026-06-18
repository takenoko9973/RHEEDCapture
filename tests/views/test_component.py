import numpy as np
from PySide6.QtGui import QColor
from pytestqt.qtbot import QtBot

from rheed_capture.application.ports.motor import DEFAULT_MOTOR_SPEED_RPM
from rheed_capture.presentation.qt.panels.angle_scan import AngleScanPanel
from rheed_capture.presentation.qt.panels.motor_settings import MotorSettingsPanel
from rheed_capture.presentation.qt.panels.preview import PreviewPanel
from rheed_capture.presentation.qt.panels.sequence import SequencePanel
from rheed_capture.presentation.qt.widgets.histogram_viewer import HistogramPanel
from rheed_capture.presentation.qt.widgets.image_viewer import ImageViewer
from rheed_capture.presentation.qt.widgets.preview_background import (
    PreviewBackground,
    PreviewBackgroundStyle,
)


def test_preview_panel_sync(qtbot: QtBot) -> None:
    """PreviewPanel内部のスライダー・スピンボックス同期と対数変換テスト"""
    # 露光時間は 1.0(10^0) ~ 100.0(10^2) の範囲でテスト
    panel = PreviewPanel(expo_bounds=(1.0, 100.0), gain_bounds=(0, 40))
    qtbot.addWidget(panel)

    # =========================================================
    # 1. スピンボックス変更 -> 対数スライダーへの変換
    # 露光時間10.0ms (10^1) は、範囲(10^0 ~ 10^2)のちょうど真ん中(500/1000)になるはず
    # =========================================================
    with qtbot.waitSignal(panel.exposure_changed, timeout=1000) as blocker:
        panel.spin_expo.setValue(10.0)

    assert panel.slider_expo.value() == 500
    assert blocker.args[0] == 10.0

    # =========================================================
    # 2. スライダー変更 (ドラッグ中) はシグナルを出さずUIだけ更新するか
    # =========================================================
    # Gainを15に設定 (valueChangedシグナル発火)
    panel.slider_gain.setValue(15)
    assert panel.spin_gain.value() == 15

    # qtbotを使って「シグナルが出ないこと」をアサートするのは難しいため、
    # 値が内部で反映されていることだけを確認し、リリースエミュレートへ進む

    # =========================================================
    # 3. マウスリリース時に初めてカメラ用シグナルが発火するか
    # =========================================================
    with qtbot.waitSignal(panel.gain_changed, timeout=1000) as blocker:
        panel.slider_gain.sliderReleased.emit()

    assert blocker.args[0] == 15


def test_sequence_panel_validation(qtbot: QtBot) -> None:
    """SequencePanelの入力バリデーションテスト"""
    panel = SequencePanel()
    qtbot.addWidget(panel)

    # 正常な入力
    panel.edit_seq_expo.setText("10, 20, 30")
    with qtbot.waitSignal(panel.expo_text_edited, timeout=1000) as blocker:
        # ユーザーがEnterを押すかフォーカスを外した操作をエミュレート
        panel.edit_seq_expo.editingFinished.emit()
    assert blocker.args[0] == "10, 20, 30"

    panel.edit_seq_gain.setText("1, 30")
    with qtbot.waitSignal(panel.gain_text_edited, timeout=1000) as blocker:
        # ユーザーがEnterを押すかフォーカスを外した操作をエミュレート
        panel.edit_seq_gain.editingFinished.emit()
    assert blocker.args[0] == "1, 30"

    with qtbot.waitSignal(panel.start_requested, timeout=1000) as blocker:
        panel.btn_start.click()

    assert len(blocker.args) == 0


def test_angle_scan_panel_uses_positive_interval(qtbot: QtBot) -> None:
    panel = AngleScanPanel()
    qtbot.addWidget(panel)

    assert panel.spin_interval_deg.minimum() == 0.5
    assert panel.spin_interval_deg.singleStep() == 0.5
    assert panel.spin_range_deg.minimum() == 0.5
    assert panel.spin_range_deg.maximum() == 90.0
    assert panel.spin_motor_speed_rpm.value() == DEFAULT_MOTOR_SPEED_RPM
    assert panel.chk_return_to_start.text() == "Return to Start"
    assert panel.btn_direction_positive.text() == "+"
    assert panel.btn_direction_negative.text() == "-"
    assert panel.btn_direction_both.text() == "±"
    assert panel.btn_direction_both.isChecked() is True


def test_angle_scan_panel_progress_shows_current_angle(qtbot: QtBot) -> None:
    panel = AngleScanPanel()
    qtbot.addWidget(panel)

    panel.update_progress(2, 5, -0.5)

    assert panel.progress_bar.value() == 2
    assert panel.progress_bar.maximum() == 5
    assert panel.progress_bar.format() == "2/5"
    assert panel.lbl_progress_status.text() == "Angle: -0.5 deg"


def test_sequence_panel_progress_shows_current_condition(qtbot: QtBot) -> None:
    panel = SequencePanel()
    qtbot.addWidget(panel)

    panel.update_progress(2, 5, 50.0, 0)

    assert panel.progress_bar.value() == 2
    assert panel.progress_bar.maximum() == 5
    assert panel.progress_bar.format() == "2/5"
    assert panel.lbl_progress_status.text() == "Condition: 50 ms, gain 0"


def test_motor_settings_panel_exposes_position_units_per_deg(qtbot: QtBot) -> None:
    panel = MotorSettingsPanel()
    qtbot.addWidget(panel)

    assert panel.spin_position_units_per_deg.value() == 31.25
    assert panel.spin_position_units_per_deg.minimum() > 0
    assert panel.spin_position_units_per_deg.decimals() == 4
    assert "MOCK" in panel.edit_motor_port.toolTip()


def test_preview_panel_grid_control_state(qtbot: QtBot) -> None:
    panel = PreviewPanel(expo_bounds=(1.0, 100.0), gain_bounds=(0, 40))
    qtbot.addWidget(panel)

    assert panel.chk_show_grid.isChecked() is False
    assert panel.cmb_grid_shape.isEnabled() is False
    assert panel.cmb_grid_shape.currentText() == "4x4"

    with qtbot.waitSignal(panel.grid_enabled_changed, timeout=1000) as blocker:
        panel.chk_show_grid.setChecked(True)
    assert blocker.args[0] is True
    assert panel.cmb_grid_shape.isEnabled() is True

    with qtbot.waitSignal(panel.grid_shape_changed, timeout=1000) as blocker:
        panel.cmb_grid_shape.setCurrentText("8x8")
    assert blocker.args == [8, 8]

    with qtbot.waitSignal(panel.grid_enabled_changed, timeout=1000) as blocker:
        panel.chk_show_grid.setChecked(False)
    assert blocker.args[0] is False
    assert panel.cmb_grid_shape.isEnabled() is False


def test_preview_panel_accepts_non_square_grid_shape(qtbot: QtBot) -> None:
    panel = PreviewPanel(expo_bounds=(1.0, 100.0), gain_bounds=(0, 40))
    qtbot.addWidget(panel)

    panel.apply_grid_settings(True, 2, 4)

    assert panel.cmb_grid_shape.currentText() == "2x4"
    grid_settings = panel.get_grid_settings_to_save()
    assert grid_settings.rows == 2
    assert grid_settings.cols == 4


def test_preview_panel_exposure_arrow_step_tracks_current_digits(qtbot: QtBot) -> None:
    panel = PreviewPanel(expo_bounds=(0.01, 5000.0), gain_bounds=(0, 40))
    qtbot.addWidget(panel)

    panel.spin_expo.setValue(1200.0)
    panel.spin_expo.stepBy(1)
    assert panel.spin_expo.value() == 1210.0

    panel.spin_expo.setValue(23.0)
    panel.spin_expo.stepBy(1)
    assert panel.spin_expo.value() == 23.1

    panel.spin_expo.stepBy(-1)
    assert panel.spin_expo.value() == 23.0


def test_image_viewer_grid_overlay_updates_pixmap(qtbot: QtBot) -> None:
    viewer = ImageViewer()
    qtbot.addWidget(viewer)
    viewer.resize(800, 600)
    viewer.show()

    image_data = np.full((120, 160), 128, dtype=np.uint8)
    viewer.set_grid_enabled(True)
    viewer.set_grid_shape(1, 2)
    viewer.update_image(image_data)

    assert viewer.pixmap() is not None
    assert viewer.pixmap().isNull() is False


def test_image_viewer_draws_configurable_preview_background(qtbot: QtBot) -> None:
    viewer = ImageViewer()
    qtbot.addWidget(viewer)
    viewer.resize(800, 600)
    viewer.show()

    viewer.set_preview_background(
        PreviewBackground(
            style=PreviewBackgroundStyle.CHECKERBOARD,
            primary_color=QColor(10, 20, 30),
            secondary_color=QColor(40, 50, 60),
            tile_size=16,
        )
    )
    image_data = np.full((100, 160), 128, dtype=np.uint8)
    viewer.update_image(image_data)

    rendered = viewer.grab().toImage()

    assert rendered.pixelColor(8, 8) == QColor(10, 20, 30)
    assert rendered.pixelColor(24, 8) == QColor(40, 50, 60)


def test_histogram_panel_update(qtbot: QtBot) -> None:
    """HistogramPanelにデータが渡され、UIテキストが正しくフォーマットされるかテスト"""
    panel = HistogramPanel()
    qtbot.addWidget(panel)

    # UI用のダミー計算結果を用意
    dummy_hist = np.zeros(256, dtype=int)
    dummy_hist[128] = 500  # 真ん中にピーク
    dummy_mean = 2048.5
    dummy_var = 123.456

    # Workerからシグナルが飛んできたと仮定してスロットを直接叩く
    panel.update_histogram(dummy_hist, dummy_mean, dummy_var)

    # 描画用ウィジェットに配列が渡されているか
    assert panel.hist_widget.hist_data is not None
    assert np.array_equal(panel.hist_widget.hist_data, dummy_hist)

    # 統計量ラベルのテキストが指定の書式（少数第2位まで）で表示されているか
    lbl_text = panel.lbl_stats.text()
    assert "2048.50" in lbl_text
    assert "123.46" in lbl_text  # 四捨五入の確認
