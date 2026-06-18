import contextlib
import logging
import signal
import sys

from dotenv import load_dotenv
from PySide6.QtWidgets import QApplication

from rheed_capture.bootstrap import create_main_window

load_dotenv()

# ログの設定
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def main() -> None:
    app = QApplication(sys.argv)
    window = None

    # Ctrl+C で終了できるように (Pyside6 では Ctrl+C で終了できない)
    signal.signal(signal.SIGINT, signal.SIG_DFL)

    try:
        window = create_main_window()
        window.show()

        sys.exit(app.exec())

    except Exception as e:
        logger.exception("起動エラー")
        # GUI起動前のエラーはコンソールに出力
        print(f"アプリケーションを起動できませんでした:\n{e}")

    finally:
        if window is not None:
            with contextlib.suppress(Exception):
                window.camera.disconnect()


if __name__ == "__main__":
    main()
