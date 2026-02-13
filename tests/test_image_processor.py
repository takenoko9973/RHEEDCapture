import numpy as np
from rheed_capture.core.image_processor import ImageProcessor

def test_apply_double_clahe():
    # 1. 準備 (Arrange)
    # カメラからの12bit生データ(16bitコンテナ)を模擬したダミー画像 (1024x1024)
    dummy_image = np.random.randint(0, 4096, (1024, 1024), dtype=np.uint16)

    # 2. 実行 (Act)
    result = ImageProcessor.apply_double_clahe(dummy_image)

    # 3. 検証 (Assert)
    assert result is not None
    assert result.shape == (1024, 1024), "入力と同じ解像度であること"
    assert result.dtype == np.uint8, "プレビュー用に8bitに変換されていること"

    # 真っ黒や真っ白になっていないかの簡易チェック
    assert np.mean(result) > 0
    assert np.mean(result) < 255
