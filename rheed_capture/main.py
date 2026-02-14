import logging
import os
import sys

from PySide6.QtWidgets import QApplication

from rheed_capture.core.camera_device import CameraDevice
from rheed_capture.core.storage import ExperimentStorage
from rheed_capture.ui.main_window import MainWindow

# ログの設定
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# ※エミュレータでテストしたい場合はコメントアウトを外してください
os.environ["PYLON_CAMEMU"] = "1"


def main():
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
        logging.exception(f"起動エラー: {e}")
        # GUI起動前のエラーはコンソールに出力
        print(f"アプリケーションを起動できませんでした:\n{e}")


if __name__ == "__main__":
    main()
