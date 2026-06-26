from unittest.mock import MagicMock, patch

import pytest

from rheed_capture.bootstrap import create_camera
from rheed_capture.infrastructure.camera.basler_configurators import (
    CAMERA_EMULATION_ENV_VAR,
    BaslerCameraEmulationSettings,
    BaslerMandatorySettings,
)


def test_create_camera_uses_mandatory_settings_for_real_camera(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """実機向けのカメラ生成では共通設定だけを渡す。"""
    monkeypatch.delenv(CAMERA_EMULATION_ENV_VAR, raising=False)
    camera_instance = MagicMock()
    camera_class = MagicMock(return_value=camera_instance)

    with patch("rheed_capture.bootstrap.BaslerCamera", camera_class):
        camera = create_camera()

    configurators = camera_class.call_args.kwargs["configurators"]
    assert camera is camera_instance
    assert [type(configurator) for configurator in configurators] == [BaslerMandatorySettings]
    camera_instance.connect.assert_called_once_with()


def test_create_camera_adds_emulation_settings_for_camera_emulation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """エミュレータ向けのカメラ生成ではROI設定を追加する。"""
    monkeypatch.setenv(CAMERA_EMULATION_ENV_VAR, "1")
    camera_instance = MagicMock()
    camera_class = MagicMock(return_value=camera_instance)

    with patch("rheed_capture.bootstrap.BaslerCamera", camera_class):
        camera = create_camera()

    configurators = camera_class.call_args.kwargs["configurators"]
    assert camera is camera_instance
    assert [type(configurator) for configurator in configurators] == [
        BaslerMandatorySettings,
        BaslerCameraEmulationSettings,
    ]
    camera_instance.connect.assert_called_once_with()
