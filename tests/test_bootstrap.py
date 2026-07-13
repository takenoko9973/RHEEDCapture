from unittest.mock import MagicMock, patch

import pytest

from rheed_capture.bootstrap import create_camera
from rheed_capture.infrastructure.camera.basler_configurators import (
    CAMERA_EMULATION_ENV_VAR,
    BaslerMandatorySettings,
)


def test_create_camera_leaves_emulation_detection_to_camera_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """環境変数があってもbootstrapは共通設定だけをカメラへ渡す。"""
    monkeypatch.setenv(CAMERA_EMULATION_ENV_VAR, "1")
    camera_instance = MagicMock()
    camera_class = MagicMock(return_value=camera_instance)

    with patch("rheed_capture.bootstrap.BaslerCamera", camera_class):
        camera = create_camera()

    configurators = camera_class.call_args.kwargs["configurators"]
    assert camera is camera_instance
    assert [type(configurator) for configurator in configurators] == [BaslerMandatorySettings]
    camera_instance.connect.assert_called_once_with()
