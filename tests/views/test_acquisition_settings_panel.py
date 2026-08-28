from PySide6.QtTest import QSignalSpy
from pytestqt.qtbot import QtBot

from rheed_capture.presentation.qt.panels.acquisition_settings import AcquisitionSettingsPanel


def test_acquisition_settings_panel_controls_hardware_inputs(qtbot: QtBot) -> None:
    """Hardware専用入力はmodeと撮影ロックを合成して有効化する。"""
    panel = AcquisitionSettingsPanel()
    qtbot.addWidget(panel)
    settings_spy = QSignalSpy(panel.settings_changed)

    assert panel.get_settings_to_save().mode == "software"
    assert panel.cmb_source.isEnabled() is False
    assert panel.cmb_activation.isEnabled() is False
    assert panel.spin_delay_us.isEnabled() is False

    panel.cmb_mode.setCurrentText("Hardware")
    assert settings_spy.at(0)[0].mode == "hardware"
    assert panel.cmb_source.isEnabled() is True
    assert panel.cmb_activation.isEnabled() is True
    assert panel.spin_delay_us.isEnabled() is True

    panel.set_controls_enabled(False)
    assert panel.cmb_mode.isEnabled() is False
    assert panel.cmb_source.isEnabled() is False
    assert panel.chk_accumulation.isEnabled() is False

    panel.set_controls_enabled(True)
    assert panel.cmb_mode.isEnabled() is True
    assert panel.cmb_source.isEnabled() is True


def test_acquisition_settings_panel_builds_current_settings(qtbot: QtBot) -> None:
    """Acquisition入力値を保存用設定へ変換する。"""
    panel = AcquisitionSettingsPanel()
    qtbot.addWidget(panel)

    panel.cmb_mode.setCurrentText("Hardware")
    panel.cmb_source.setCurrentText("Line3")
    panel.cmb_activation.setCurrentText("FallingEdge")
    panel.spin_delay_us.setValue(12.5)
    panel.chk_fps_unlimited.setChecked(False)
    panel.spin_fps_limit.setValue(24.0)
    panel.chk_accumulation.setChecked(True)
    panel.spin_accumulation_frames.setValue(4)
    panel.spin_trigger_wait_timeout_sec.setValue(2.5)

    settings = panel.get_settings_to_save()
    assert settings.hardware_source == "Line3"
    assert settings.hardware_activation == "FallingEdge"
    assert settings.hardware_delay_us == 12.5
    assert settings.fps_limit == 24.0
    assert settings.accumulation_enabled is True
    assert settings.accumulation_frames == 4
    assert settings.trigger_wait_timeout_sec == 2.5
