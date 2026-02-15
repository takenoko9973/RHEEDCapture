from pytestqt.qtbot import QtBot

from rheed_capture.views.components.preview_panel import PreviewPanel
from rheed_capture.views.components.sequence_panel import SequencePanel


def test_preview_panel_sync(qtbot: QtBot) -> None:
    """PreviewPanel内部のスライダー・スピンボックス同期テスト"""
    panel = PreviewPanel(exp_bounds=(1.0, 100.0), gain_bounds=(0.0, 10.0))
    qtbot.addWidget(panel)

    # スピンボックス変更でシグナルが出るか＆スライダーが動くか
    with qtbot.waitSignal(panel.exposure_changed, timeout=1000) as blocker:
        panel.spin_expo.setValue(50.25)

    assert panel.slider_expo.value() == 5025
    assert blocker.args[0] == 50.25

    # スライダー変更でシグナルが出るか＆スピンボックスが動くか
    with qtbot.waitSignal(panel.gain_changed, timeout=1000) as blocker:
        panel.slider_gain.setValue(150)  # 1.5

    assert panel.spin_gain.value() == 1.5
    assert blocker.args[0] == 1.5


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
