import logging
import sys

from dotenv import load_dotenv
from PySide6.QtWidgets import QApplication

from rheed_capture.models.hardware.camera_device import CameraDevice
from rheed_capture.models.io.storage import ExperimentStorage
from rheed_capture.views.main_window import MainWindow

load_dotenv()

# ログの設定
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def main() -> None:
    app = QApplication(sys.argv)

    try:
        # 1. モデル(ハードウェアとストレージ)の初期化
        camera = CameraDevice()
        camera.connect()

        storage = ExperimentStorage(root_dir="./Data_Root")

        # 2. UIの初期化と表示 (依存性を注入)
        window = MainWindow(camera, storage)
        window.show()

        # 3. イベントループ開始
        sys.exit(app.exec())

    except Exception as e:
        logger.exception("起動エラー")
        # GUI起動前のエラーはコンソールに出力
        print(f"アプリケーションを起動できませんでした:\n{e}")


if __name__ == "__main__":
    main()
