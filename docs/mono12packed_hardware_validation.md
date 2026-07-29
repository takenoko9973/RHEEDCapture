# Mono12Packed実機確認チェックリスト

## 検証状態

- 状態: 未実施
- 記録日: 2026-07-29
- 対象カメラ: Basler acA720-290gm
- 未実施理由: この変更の実装・自動テスト時に実機を使用していないため

この文書は、pylon Camera Emulationやmockでは確定できない実機依存項目を記録する。
確認結果を推測で補わず、実機で観測した値と結果を追記する。

## 確認環境

- 確認日:
- 確認者:
- カメラ型番:
- カメラSerial Number:
- pylonバージョン:
- pypylonバージョン:
- 接続先NIC:
- 保存先:

## 必須確認項目

- [ ] 接続後の `PixelFormat` 読戻し値が `Mono12Packed` である。
- [ ] Preview画像を正常に取得できる。
- [ ] Recordingを正常に実行できる。
- [ ] PreviewとRecordingの取得配列が `numpy.uint16` である。
- [ ] `MsbAligned` 出力で、通常の12-bitセンサ値が16刻みになっている。
- [ ] 保存前配列とTIFF読戻し配列が一致する。
- [ ] 同じ露光時間・Gainで、従来の `Mono12` と明るさスケールが変化していない。
- [ ] 横縞、画素の交互入れ替わり、画像幅の崩れがない。
- [ ] PreviewのCurrent FPSが実際の取得状況に応じて更新される。
- [ ] RecordingのCurrent FPSとAverage FPSが更新される。
- [ ] Payload表示が変換後の `uint16` 配列サイズではなく、GrabResultまたは `PayloadSize` nodeの値に基づいている。
- [ ] Preview停止後に統計表示が消える。
- [ ] Recordingの正常終了、キャンセル、例外終了後に統計表示が消える。

## Mono12との比較記録(任意)

同一の露光時間、Gain、ROI、接続条件で記録する。数値をコードや仕様へ固定値として転記しない。

| PixelFormat | Resulting Frame Rate | Current FPS | Payload MB/s | CPU使用率 | フレーム欠落・Timeout | 備考 |
| --- | ---: | ---: | ---: | ---: | --- | --- |
| Mono12 |  |  |  |  |  |  |
| Mono12Packed |  |  |  |  |  |  |

## 検証結果

- 総合結果:
- 未確認のまま残した項目:
- 観測した問題:
- 関連ログ・保存データ:
- 対応IssueまたはPull Request:
