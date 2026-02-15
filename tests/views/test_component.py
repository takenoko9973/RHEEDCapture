import numpy as np
from pytestqt.qtbot import QtBot

from rheed_capture.views.components.histogram_viewer import HistogramPanel, HistogramWidget
from rheed_capture.views.components.preview_panel import PreviewPanel
from rheed_capture.views.components.sequence_panel import SequencePanel


def test_preview_panel_sync(qtbot: QtBot) -> None:
    """PreviewPanel内部のスライダー・スピンボックス同期と対数変換テスト"""
    # 露光時間は 1.0(10^0) ~ 100.0(10^2) の範囲でテスト
    panel = PreviewPanel(expo_bounds=(1.0, 100.0), gain_bounds=(0.0, 40.0))
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
    panel.edit_seq_expo.setText("10, 20")
    panel.edit_seq_gain.setText("1")

    with qtbot.waitSignal(panel.start_requested, timeout=1000) as blocker:
        panel.btn_start.click()

    assert blocker.args[0] == [10.0, 20.0]
    assert blocker.args[1] == [1.0]

    # 不正な入力
    panel.edit_seq_expo.setText("invalid")
    with qtbot.waitSignal(panel.validation_error, timeout=1000):
        panel.btn_start.click()

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
    assert np.array_equal(panel.hist_widget.hist_data, dummy_hist)

    # 統計量ラベルのテキストが指定の書式（少数第2位まで）で表示されているか
    lbl_text = panel.lbl_stats.text()
    assert "2048.50" in lbl_text
    assert "123.46" in lbl_text  # 四捨五入の確認
