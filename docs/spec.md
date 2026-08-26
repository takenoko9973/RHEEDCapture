# RHEED撮影・解析支援システム 要件定義書

## 1. システム概要

Basler社製産業用カメラを用い、RHEED（反射高速電子線回折）パターンのリアルタイムプレビューおよびマルチ条件での自動シーケンス撮影を行うシステム。
プレビュー時は視認性を高める画像処理（CLAHE）を適用可能とし、保存時は解析の定量性を完全に保証するため、pypylonの公式コンバータを介した**センサ生データ（Raw）**を出力する。

## 2. 動作環境・技術スタック

* **言語**: Python 3.x
* **GUIフレームワーク**: PySide6 (Qt)
* **カメラ制御**: pypylon (Basler Pylon SDK Wrapper)
* **画像保存・メタデータ処理**: tifffile
* **画像処理・数値計算**: OpenCV, NumPy
* **アーキテクチャ設計**: TDD（テスト駆動開発）に基づくレイヤードアーキテクチャ (Model-View-ViewModelベース)

## 3. ソフトウェアアーキテクチャ

責務を分離し、拡張性とテスト容易性を高める設計とする。

| モジュール名 | レイヤー | 役割・責務 |
| --- | --- | --- |
| **`CameraDevice`** | Model | ハードウェア制御 (pypylonラッパー)。パラメータ設定、MsbAligned適用、Min/Max取得。 |
| **`ImageProcessor`** | Model | 純粋な画像変換。CLAHE処理アルゴリズム。状態を持たない静的メソッド。 |
| **`ExperimentStorage`** | Model | 実験セッションのディレクトリ状態管理、連番管理、遅延作成ロジック。 |
| **`TiffWriter`** | Model | I/O専任。Numpy配列とJSONメタデータを指定圧縮でTIFFへ書き込む。 |
| **`AppSettings`** | Model | `settings.json` を用いたUI状態の保存・復元。 |
| **`PreviewWorker`** | ViewModel | 非同期スレッドでの継続的プレビュー取得・画像処理・UIへのシグナル送信。 |
| **`CaptureService`** | ViewModel | 非同期スレッドでの自動撮影制御。直積ループ生成、リトライロジックの管理。 |
| **`MainWindow`** | View | GUI表示、ユーザー入力のバリデーション、各Model/Workerへのイベント伝達。 |

## 4. カメラ・ハードウェア制御仕様

### 4.1 センサおよびピクセルフォーマット

カメラからPCへの転送形式と、pypylon変換後にアプリケーションが扱う形式を区別する。

**カメラ転送形式**：

* 実機Basler acA720-290gm：`PixelFormat = Mono12Packed`
* pylon Camera Emulation：`PixelFormat = Mono12`

接続先はDevice Classで判定し、`BaslerCamEmu`だけをエミュレータとして扱う。
`PixelFormat` は撮影データの意味を決める必須設定であり、nodeの利用可否と書込可否を確認し、設定後の読戻し値が期待値と一致しない場合は接続を失敗させる。
実機で `Mono12Packed` を設定できない場合に、`Mono12` や `Mono8` へフォールバックしない。

**pypylon変換後の形式**：

* `OutputPixelFormat = Mono16`
* `OutputBitAlignment = MsbAligned`
* NumPy dtype：`uint16`
* センサ有効ビット深度：12bit

実機とエミュレータのどちらも、pypylon公式の `ImageFormatConverter` で変換する。
PythonやNumPyによる `Mono12Packed` の手動アンパックは行わない。
12bitデータ（0〜4095）を16bitコンテナの上位ビットへ配置し、0〜65520のスケールとしてプレビュー処理、解析処理、保存処理へ渡す。

### 4.2 強制初期化設定 (生データ保証)

接続時に以下の設定を強制し、カメラ側での余計な補正を無効化する。

* `ExposureAuto` = Off, `GainAuto` = Off, `BalanceWhiteAuto` = Off
* `Gamma` = 1.0, `BlackLevel` = 0.0, `LUTEnable` = False

## 5. 機能要件

### 5.1 プレビュー機能

* **取得ロジック**: PreviewはSequence、Angle Scan、Recordingと同じTrigger Sessionを使う。取得モードは `Software` と `Hardware` の2種類で、Free Runは使用しない。
* **Software Trigger**: `TriggerReady` を待ってからSoftware Triggerを1回発行し、1枚のRaw frameを取得する。FPS Limitが `Unlimited` の場合、アプリケーション側で意図的なsleepによる速度制限を行わない。
* **Hardware Trigger**: アプリケーションからSoftware Triggerを発行せず、外部FrameStartに対応するRaw frameを待つ。無信号の待機は撮影エラーにせず、最後に完成したPreview画像を表示したままにする。
* **共通Acquisition設定**: Trigger Mode、Hardware Source、Hardware Activation、Trigger Delay `[us]`、FPS Limit、Accumulation、Accumulation Frames、Trigger Wait Timeout `[s]` を使用する。既定値は `Software`、`Line1`、`RisingEdge`、遅延 `0`、FPS Limit `Unlimited`、Accumulation `Off`（`N=1`）、Trigger Wait Timeout `0`（無期限）である。Trigger DelayはHardware専用とする。
* **Preview設定変更**: Preview中にTrigger Mode、FPS Limit、Accumulation設定を変更した場合は、現在のSessionを停止して現在値で再armする。再arm後もPreviewを自動的に再開する。
* **画像処理 (トグル式)**:
* **ON時**: CLAHE（Contrast Limited Adaptive Histogram Equalization）を分割数の異なる2段構成で適用。
* **OFF時**: MsbAligned化された16bitデータを8bitにダウンスケール（`>> 8`）して表示。

AccumulationをONにした場合、Raw frameを `uint64` で画素ごとに加算し、`uint16` の範囲へclipしてから完成した積算画像だけをPreviewへ通知する。
Accumulation中は次のRaw frameが到着するまで前回の完成画像を表示し、積算画像そのものは保存しない。

* **グリッド表示 (トグル式)**:
プレビュー画像上に位置合わせ用のグリッドをオーバーレイ表示できる。グリッドは表示補助のみを目的とし、プレビュー用画像処理および保存画像データには適用しない。
* **分割数**: `rows x cols` 形式で選択する。初期候補は `1x2`, `2x2`, `4x4`, `8x8` とし、最小値は各軸1以上とする。
* **初期状態**: グリッド表示はOFF、分割数は `4x4` とする。

* **プレビュー外領域の識別**:
表示領域とカメラ画像のアスペクト比が異なる場合、カメラ画像の外側に発生する余白は黒一色ではなく、透過領域を示すようなグレー系チェッカーボードで描画する。これにより、暗いRHEED画像と画像外領域の境界を視認しやすくする。
* **背景表示の拡張性**: 背景表示は `solid` / `checkerboard` などのスタイルと色・タイルサイズを設定値として分離し、将来的に単色背景、斜線背景、境界強調などを試せる構造とする。

* **描画負荷への対応**: UIの応答性（ボタン操作等）を最優先とし、必要に応じてプレビューのフレームレート低下を許容する。

### 5.2 自動シーケンス撮影機能

* **撮影フロー**:

1. プレビューの完全停止 (`StopGrabbing`)。
2. 入力された露光時間(ms)リストとゲインリストを**それぞれ昇順にソートする**（カメラの安定性確保のため、小さい値から順に適用する）。
3. ソートされたリストの**直積（全組み合わせ）**を展開し、順次設定を適用。
4. AccumulationがOFFの場合は条件ごとに `expected_frames=1` のTrigger Sessionを開始する。ONの場合は同一条件で `N` 枚のRaw frameを取得するgroupとして扱う。
5. 共通Acquisition設定のTrigger Modeに従い、Softwareでは `TriggerReady` 待機後にSoftware Triggerを発行し、HardwareではSoftware Triggerを発行せず外部FrameStartを待つ。
6. `GrabStrategy_OneByOne` でRaw frameを取得し、AccumulationがONの場合も各Rawを取得直後に保存処理へ渡す。積算結果はPreview通知専用であり、保存対象は元のRaw frameである。
7. Hardwareで共通Trigger Wait Timeoutが設定されている場合、必要なRaw frameの待機が期限を超えると条件をskipせず撮影全体をエラー終了する。`0` は無期限である。
8. 撮影完了後、プレビューを自動再開。

共通Acquisition設定が `Software` の場合は上記の `TriggerReady` 待機とSoftware Trigger発行を行う。`Hardware` の場合はアプリからSoftware Triggerを発行せず、外部FrameStartに対応するフレームを待つ。HardwareではTrigger Source / Activation / Delayを指定し、利用不能または設定拒否時に別値へ変更せず `CameraError` とする。

* **キャンセルフラグ**: ユーザーによる即時中断（進行中の撮影ループ終了後に停止）をサポート。

### 5.3 Recording機能

* 露光時間とゲインを設定後、`expected_frames=None` の共通Trigger Sessionを用意し、正常な間はRecording全体で再利用する。
* Softwareでは従来のFPSまたはInterval入力から元の予定時刻を計算し、`TriggerReady` 待機後に1回Software Triggerを発行する。遅延時もframe indexを飛ばさない。Softwareの要求rateが有効な共通FPS Limitを超える場合は開始前にエラーとし、FPSを自動的に丸めない。
* HardwareではRecording側のFPSとInterval入力を使用せず、外部FrameStartに対応するRaw frameを待つ。最初のRaw frameだけは共通Trigger Wait Timeoutを適用し、最初の正常Raw到着時をDurationの `t=0` とする。最初のRaw到着後はtriggerが停止してもTrigger Wait Timeoutエラーにせず、Duration終了を優先する。
* Duration終了時にAccumulation groupが開始済みであれば、そのgroupが `N` 枚になるまでRawを取得して保存する。完成後に終了し、Duration終了後に新しいgroupは開始しない。
* AccumulationがOFFの場合は従来のRecording保存形式を維持する。ONの場合はgroupディレクトリにRawを保存し、Previewへはgroup完成時のclip済み積算画像だけを通知する。
* Session開始またはSoftwareの1フレーム取得が失敗した場合は異常Sessionを閉じ、新しいSessionで同じframe indexを最大3回まで再試行する。Hardware Recordingの最初のRaw待機timeoutはエラーとして終了し、開始後のtimeoutはDuration境界として扱う。
* RecordingのTIFF圧縮はboolean設定で切り替え、ONでは`zlib`、OFFでは非圧縮とする。`recording.json` の `storage.tiff_compression` は実際の状態（`"zlib"` または `null`）を記録する。
* Recordingの保存待機queueは最大1000 framesとし、容量内の要求は破棄しない。満杯時は空きができるまで撮影側を待機させ、終了・キャンセル・エラー時も投入済み要求をdrainしてから終了する。
* Recordingの `frames.csv` には各frameのenqueue時待機queue depthを `save_queue_depth` としてframe対応で記録する。
* `actual_elapsed_ms` はSoftwareではtrigger発行直前、HardwareではRaw到着時のmonotonic時刻を基準にする。Hardwareの `target_elapsed_ms` は記録しない。

### 5.4 データ・ディレクトリ管理機能

* **遅延作成 (Lazy Creation)**:
アプリ起動やルートフォルダ設定時点では空フォルダを作成せず、**実際に「Start Sequence」が実行された瞬間にのみ**必要なディレクトリツリーを構築する。
* **ブランチ(-n)の自動認識と手動更新**:
指定されたRoot内に本日の実験フォルダ(`yymmdd`)が存在する場合、既存の枝番(`yymmdd-n`)と内部の連番(`image_nnn`)を自動スキャンして続きから再開する。
GUI上の「New Branch」ボタンにより、意図的に新しいブランチ（例: `-2` から `-3` へ）を切り出し、連番を `001` にリセット可能。

### 5.5 GUI・操作要件

* **パラメータ入力の双方向同期**:
プレビューの露光時間・ゲイン設定において、「小数入力可能なSpinBox」と「直感的に操作可能なSlider」を相互にリアルタイム同期させる。スライダーの可動域はカメラのMin/Max仕様を動的に取得して反映する。
* **プレビュー表示補助**:
CLAHE処理のON/OFFとグリッド表示のON/OFFをPreview Settings内で操作可能とする。グリッドはチェックボックスと分割数ComboBoxを同一行に配置し、OFF時はComboBoxを無効化して効果がない状態を視覚的に示す。
* **保存先参照**: GUIからダイアログで保存先 Root Directory を変更可能。
* **進捗表示**: シーケンス撮影時は全体の撮影予定枚数と現在枚数をプログレスバーで可視化する。
* **共通Acquisition設定**: Settings画面でTrigger Mode、Hardware Source、Hardware Activation、Trigger Delay `[us]`、FPS Limit、Accumulation、Accumulation Frames、Trigger Wait Timeout `[s]` を設定できる。Software選択時はHardware専用入力を無効化する。
* **撮影中のロック**: Recording、Sequence、Angle Scanの実行中は共通Acquisition設定を変更できない。Hardware RecordingではRecordingパネルのFPSとInterval入力も無効化する。

### 5.6 アプリケーション設定の永続化

* アプリケーション終了時に以下の項目を `settings.json` に保存し、次回起動時に自動復元する。
* Root Directoryパス
* プレビュー用露光時間 / ゲイン
* シーケンス用露光時間リスト / ゲインリスト
* CLAHE処理のON/OFF状態
* プレビューグリッド表示のON/OFF状態 (`show_preview_grid`)
* プレビューグリッド分割数 (`preview_grid_rows`, `preview_grid_cols`)
* Recording TIFF圧縮の有効/無効 (`tiff_compression_enabled`)

### 5.7 取得統計表示

* PreviewとRecordingでは、正常取得したRaw frameを単位として、session内Raw frame count、Raw FPS、Accumulation progress `x/N` を表示する。HardwareのRaw frame待機中は `Waiting for trigger` を表示する。
* Raw frame countはgroup数、積算画像数、UI描画回数、TIFF保存完了数ではなく、正常に取得したRaw frame数を表す。
* Raw FPSは単調増加時計を使用し、直近1秒のRaw frame時刻について、フレーム間隔数を先頭から末尾までの経過時間で割って求める。
* 取得可能な場合は、直近1秒のGrabResultのPayload byte数合計を対象時間で割り、10進単位のMB/sで表示する。変換後の `uint16` 配列の `nbytes` は使用しない。
* Payloadは画像取得に伴うデータ量であり、NIC全体の通信量ではない。Ethernet、IP、UDP、GigE Visionのヘッダと再送分を含まない。
* Recording中は保存処理中の要求を除く待機中save queueのcurrent depthと、Recording中に観測したpeak depthを診断表示する。
* 表示はMainWindowのstatus bar右側に置き、500ms間隔で更新する。Preview停止中とRecording終了後は表示を消去する。
* 通常のSequence撮影とAngle Scanでは取得統計を表示しない。

実機依存項目の確認状況と記録欄は、[Mono12Packed実機確認チェックリスト](mono12packed_hardware_validation.md)にまとめる。

## 6. データ保存仕様

### 6.1 記録形式

* **フォーマット**: TIFF (`.tiff`)。Sequence/Angle Scanは`zlib`固定、Recordingは圧縮booleanにより`zlib`または非圧縮。
* **データ型**: `uint16` (MsbAligned処理済み)
* **保存値スケール**: 12bitセンサ値を16bitコンテナの上位ビットへ配置した0〜65520
* **画像加工**: 画像処理（CLAHE等）は一切適用せず、コンバータから得た配列をそのまま書き込む。

### 6.2 メタデータ仕様

TIFFの標準タグ `ImageDescription` に、以下の情報をJSON文字列として埋め込む。

```json
{
  "exposure_ms": 10.5,
  "gain": 0.0,
  "camera_exposure_ms": 10.496,
  "camera_gain": 0,
  "timestamp": "2026-02-15T15:00:00.000+09:00",
  "camera_timestamp_ticks": 123456789,
  "camera_timestamp_frequency_hz": 125000000,
  "camera_timestamp_source": "camera",
  "bit_depth_sensor": 12,
  "bit_depth_saved": 16,
  "alignment": "MsbAligned"
}

```

`exposure_ms` と `gain` はアプリが要求した撮影条件、`camera_exposure_ms` と `camera_gain` は取得フレームに対応するカメラ読戻し値を表す。実機ではExposure Time、Gain Allを必須Chunkから読戻し、Timestamp Chunkが利用可能な場合だけcamera timestampを使う。Timestamp Chunkが欠落・不可読なカメラでも撮影を拒否せず、`camera_timestamp_source` を `host` として `time.time_ns()` を1GHzのtickへ保存する。`timestamp` はSoftwareではPCがSoftware Trigger命令を発行する直前のJST時刻、HardwareではRaw frameをhostが取得した時点のJST時刻を表す。`camera_timestamp_source` が `camera` の場合、`camera_timestamp_ticks` は画像取得開始時のカメラ内部時計の生tick、`camera_timestamp_frequency_hz` は1秒あたりのtick数である。PTPを自動有効化しないため、camera tickを絶対日時として扱わない。pylonエミュレータではsourceを `simulation` とし、Software Trigger発行直後の `perf_counter_ns()` と周波数 `1000000000` を保存する。この値は実測値ではない。Recordingではcamera読戻し項目をTIFFと `frames.csv` の両方へ保存する。

取得統計は実行時の診断表示であり、TIFFメタデータへ追加しない。

### 6.3 ディレクトリ構造とファイル命名規則

```text
[Root_Directory] (設定で指定可)
 ├── 260215                  # その日最初の実験 (yymmdd)
 │    ├── image_001          # Accumulation OFFのSequence
 │    │    ├── 260215-1_expo10_gain0.tiff
 │    │    └── 260215-1_expo50_gain0.tiff
 │    ├── image_002          # Accumulation ONのSequenceの例
 │    │    └── group_0001_expo10_gain0
 │    │         ├── raw_0001.tiff
 │    │         └── raw_0002.tiff
 │    ├── angle_scan_001     # Angle Scan。配下にangle+00.0等を作る
 │    └── record-1           # Recording
 │         ├── recording.json
 │         ├── frames.csv
 │         └── group_000001  # Accumulation ONの場合
 │              └── raw_0001.tiff
 ├── 260215-2                # 新規ブランチ(同日別実験)
 │    └── image_001

```

* **SequenceのAccumulation OFF**: `image_nnn` 直下へ `{experiment_dir_name}-{sequence_number}_expo{exposure_ms:g}_gain{gain:g}.tiff` を保存する。
* **SequenceのAccumulation ON**: 条件ごとに `group_{group_index:04d}_expo{exposure_ms:g}_gain{gain:g}` を作り、その配下へ取得順に `raw_{raw_index:04d}.tiff` を保存する。`group_index` は条件の順番である。
* **Angle ScanのAccumulation OFF**: `angle{angle_deg:+06.1f}` 配下へ `{scan_id}_angle{angle_deg:+06.1f}_exp{exposure_ms:g}_gain{gain:g}.tiff` を保存する。
* **Angle ScanのAccumulation ON**: 角度ディレクトリ配下に `group_{condition_index:04d}_exp{exposure_ms:g}_gain{gain:g}` を作り、その配下へ `raw_{raw_index:04d}.tiff` を保存する。`scan.json` の `capture.accumulation_frames` と `storage.group_directory_format`、`storage.raw_filename_format` に実行形式を記録する。
* **RecordingのAccumulation OFF**: `record-N` 直下へ `{sample_name}_{date}_rec-{record_number}_{frame_index:05d}.tiff` を保存する。
* **RecordingのAccumulation ON**: `record-N/group_{group_index:06d}/raw_{raw_index:04d}.tiff` へRawを保存する。`recording.json` の `storage` にgroup directoryとRaw filenameの形式を記録し、`frames.csv` の `filename` はsessionディレクトリからの相対POSIXパスになる。
* Accumulation ONの保存対象は積算前のRaw frameであり、積算画像は保存しない。group途中で停止またはエラーになった場合も、既に保存したRawを削除しない。

## 7. エラー・例外処理

* **リトライ制御 (CaptureService)**:
Trigger Session開始（Trigger設定、必須node設定、必須Chunk準備、`StartGrabbing`）、Softwareの`TriggerReady` 待機・trigger発行、`RetrieveResult`、Grab成否、必須Chunk読戻し、画像変換、カメラ通信のいずれかが失敗した場合、異常Sessionを閉じて新しいSessionを作り、最大 **3回** まで再撮影する。Timestamp Chunkだけは任意であり、欠落・不可読時はhost timestampへfallbackする。Exposure/Gain readbackの失敗は再試行対象の撮影エラーとする。各Software試行は `露光時間 + 500ms` の共通deadlineを持ち、待機と取得にはその残り時間だけを渡す。
* **Hardware待機timeout**: SequenceとAngle Scanでは、各Raw frameのHardware待機に共通Trigger Wait Timeoutを適用し、timeout時は撮影全体をエラー終了する。Recordingでは最初のRaw待機だけに同じtimeoutを適用し、最初のRaw到着後はDuration終了を優先する。
* **接続初期化失敗時の保護**:
カメラをOpenした後のデバイス情報取得または初期設定で失敗した場合は、カメラをCloseして未接続状態へ戻し、起動エラーとして通知する。
* **致命的エラー時の保護**:
リトライ上限に達した場合は、シーケンス全体を中断し、ユーザーにダイアログで通知する。中断が発生した場合でも、`finally` ブロックにより必ずプレビュー機能を復帰させる（ハードウェアリソースをロックしたままにしない）。
