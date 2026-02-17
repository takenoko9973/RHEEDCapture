from PySide6.QtCore import QObject, Signal, Slot

from rheed_capture.models.hardware.camera_device import CameraDevice
from rheed_capture.models.io.storage import ExperimentStorage
from rheed_capture.services.capture_service import CaptureService
from rheed_capture.utils import parse_numbers


class CaptureViewModel(QObject):
    # View (UI) に公開するパススルー用シグナル
    progress_updated = Signal(int, int)  # (現在の枚数, 全体の枚数)
    sequence_finished = Signal(bool, str)  # (成功フラグ, 保存先ディレクトリ名)
    error_occurred = Signal(str)

    # UI表示更新用シグナル（パース・整形済みの綺麗な文字列をUIに返す）
    expo_text_updated = Signal(str)
    gain_text_updated = Signal(str)

    def __init__(self, camera: CameraDevice, storage: ExperimentStorage) -> None:
        super().__init__()
        self._camera = camera
        self._storage = storage
        self._capture_service: CaptureService | None = None

        # 撮影条件の状態保持
        self._expo_list: list[float] = [10.0, 50.0, 100.0]
        self._gain_list: list[int] = [0]

    # ====== 設定のロード・セーブ ======

    def load_settings(self, settings: dict) -> None:
        # JSONファイルから直接リストとして読み込む
        self._update_expo_state(settings.get("seq_expo_list", [10.0, 50.0, 100.0]))
        self._update_gain_state(settings.get("seq_gain_list", [0]))

    def get_settings_to_save(self) -> dict:
        # リストのまま保存する
        return {
            "seq_expo_list": self._expo_list,
            "seq_gain_list": self._gain_list,
        }

    # ====== 入力バリデーションと状態の更新 ======

    def _empty_list_error(self) -> None:
        msg = "リストが空です"
        raise ValueError(msg)

    @Slot(str)
    def update_expo_from_text(self, text: str) -> None:
        """UIで露光時間が入力された際にパースしてリストを更新する"""
        try:
            vals = parse_numbers(text, float)
            if not vals:
                self._empty_list_error()

            self._update_expo_state(vals)
        except ValueError:
            self.error_occurred.emit(
                "露光時間の形式が正しくありません。\nカンマ区切りの数値を入力してください。"
            )
            # エラー時は、UIの文字を現在保持している正しい状態の文字列に強制的にし戻しする
            self._update_expo_state(self._expo_list)

    @Slot(str)
    def update_gain_from_text(self, text: str) -> None:
        """UIでゲインが入力された際にパースしてリストを更新する"""
        try:
            vals = parse_numbers(text, int)
            if not vals:
                self._empty_list_error()

            self._update_gain_state(vals)
        except ValueError:
            self.error_occurred.emit(
                "ゲインの形式が正しくありません。\nカンマ区切りの整数を入力してください。"
            )
            self._update_gain_state(self._gain_list)

    def _update_expo_state(self, vals: list[float]) -> None:
        """状態を更新し、UI向けに整形された文字列を通知する"""
        self._expo_list = vals
        # 例: [10.0, 50.0] -> "10.0, 50.0" と整形してUIを更新
        self.expo_text_updated.emit(", ".join(map(str, vals)))

    def _update_gain_state(self, vals: list[int]) -> None:
        self._gain_list = vals
        self.gain_text_updated.emit(", ".join(map(str, vals)))

    # ====== 撮影制御 ======

    @Slot()
    def start_sequence(self) -> None:
        """撮影スレッドを生成して開始"""
        # スレッドのインスタンス化 (実行のたびに作り直す設計を維持)
        self._capture_service = CaptureService(
            self._camera, self._storage, self._expo_list, self._gain_list
        )

        # 内部スレッドのシグナルをViewModelのシグナルに中継する
        self._capture_service.progress_update.connect(self.progress_updated)
        self._capture_service.sequence_finished.connect(self.sequence_finished)
        self._capture_service.error_occurred.connect(self.error_occurred)

        self._capture_service.start()

    @Slot()
    def cancel_sequence(self) -> None:
        """撮影のキャンセルを要求する"""
        if self.is_running() and self._capture_service:
            self._capture_service.cancel()

    def is_running(self) -> bool:
        """撮影スレッドが実行中かどうかを判定する"""
        return self._capture_service is not None and self._capture_service.isRunning()
