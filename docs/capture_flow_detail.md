# Sequence・Angle Scan・Recordingの詳細フロー

この文書は、現在の実装に基づいて通常シーケンス撮影、回転撮影、Recordingの処理順を整理したものである。回転撮影はUI上では `Angle Scan` として実装されている。

## 0. 共通Acquisition設定とTrigger Session

Preview、Sequence、Angle Scan、Recordingは、共通Acquisition設定から作った同じTrigger Session経路を使用する。
取得モードは `Software` と `Hardware` であり、Free Runは使用しない。

既定値は次のとおりである。

| 項目 | 既定値と意味 |
| --- | --- |
| Trigger Mode | `Software` |
| Hardware Source | `Line1` |
| Hardware Activation | `RisingEdge` |
| Trigger Delay | `0 us`。Hardware専用 |
| FPS Limit | `Unlimited` |
| Accumulation | `Off`、`N=1` |
| Trigger Wait Timeout | `0 s`。無期限 |

Softwareでは、Sessionをarmした後に `TriggerReady` を待ち、Software Triggerを発行してから1枚を取得する。
HardwareではSoftware Triggerを発行せず、外部FrameStartに対応するRaw frameを取得する。
Trigger Source、Activation、DelayなどのHardware設定が利用不能または設定拒否になった場合、別の値へ変更せずエラーにする。

Recording、Sequence、Angle Scanの実行中は共通Acquisition設定をロックする。
Preview中に設定を変更した場合は現在のSessionを閉じ、現在値で再armしてPreviewを自動再開する。
Hardware RecordingではRecordingパネルのFPSとInterval入力も無効化する。

Timestamp Chunkは任意である。
利用可能な場合はcamera timestampを保存し、欠落または読戻し不能の場合だけhost timestampへfallbackする。
ExposureとGainの必須Chunk読戻しは緩和しない。

## 1. 通常シーケンス撮影

### 1.1 開始前のUI制御

1. ユーザーが `Sequence` タブで `Start` を押す。
2. `MainWindow` は通常シーケンス撮影中の状態へ切り替える。
   - `Sequence` パネルを撮影中表示にする。
   - `Angle Scan` パネル、モーター設定、プレビュー設定の操作を無効化する。
   - 共通Acquisition設定を無効化する。
   - 次回保存先表示を更新するタイマーを停止する。
3. `PreviewWorker` へプレビュー停止を要求する。
4. プレビュー停止完了通知を受けてから、`CaptureViewModel.start_sequence()` が呼ばれる。

### 1.2 撮影条件の確定

1. `CaptureService` を新しく作成する。
2. 入力済みの露光時間リストとゲインリストをそれぞれ昇順にソートする。
3. ソート済みリストの直積を撮影条件にする。
   - 例: 露光時間 `[10, 50]`、ゲイン `[0, 5]` の場合、`(10, 0)`, `(10, 5)`, `(50, 0)`, `(50, 5)` の順に撮影する。
4. 総撮影枚数は `露光時間数 * ゲイン数` になる。
5. 1回の撮影条件につき最大3回まで再試行する。

### 1.3 保存先の確定

1. `ExperimentStorage.start_new_sequence()` が呼ばれる。
2. 現在の実験ブランチ直下を再スキャンし、既存の `image_nnn` の最大番号を確認する。
3. ルートフォルダと実験フォルダを必要に応じて作成する。
   - その日最初の実験フォルダは `yymmdd`。
   - 手動でブランチを進めた場合は `yymmdd-n`。
4. 次の連番として `image_nnn` フォルダを作成する。
5. 撮影完了時にUIへ表示する保存先名として、この `image_nnn` が保持される。

### 1.4 各条件での撮影処理

各露光時間・ゲイン条件について、以下を繰り返す。

1. キャンセル要求が出ていないか確認する。
2. 進捗を `現在枚数 / 総枚数` としてUIへ通知する。
3. カメラの露光時間を設定する。
4. カメラのゲインを設定する。
5. AccumulationがOFFなら `expected_frames=1` のTrigger Sessionを開始する。ONなら同じ条件で `N` 枚を取得するgroupとして扱う。
6. 共通Acquisition設定に従ってRawを取得する。Softwareでは `TriggerReady` を待ち、PCのJST時刻とmonotonic時刻を記録してからSoftware Triggerを1回発行する。Hardwareではアプリからtriggerを発行せず、外部FrameStartに対応するフレームを待つ。
7. `GrabStrategy_OneByOne` でRaw frameを取得し、必須のExposure/Gain ChunkとMono16 / `MsbAligned` 画像を得る。Timestamp Chunkが利用可能ならcamera timestampを使い、欠落・不可読時はhostの `time.time_ns()` を1GHzのtickとして使う。
   - Softwareの1試行は `露光時間 + 500ms` の共通deadlineを持つ。
   - HardwareでONの場合は、group内の各Raw frameに共通Trigger Wait Timeoutを適用する。
8. Accumulation ONでは各Rawを取得直後にgroupへ保存する。積算は `uint64` で画素ごとに行い、group完成時に `65535` へclipした画像だけをPreviewへ通知する。積算画像は保存しない。
9. Sessionを閉じ、Trigger設定を解除してカメラを通常状態へ戻す。
10. 要求した露光時間・ゲイン、カメラから読戻した露光時間・Gain、Softwareではtrigger直前・HardwareではRaw取得時点のPC時刻、camera timestamp tickと周波数、ビット深度、`MsbAligned` 情報をTIFFメタデータとして作る。
11. 現在の `image_nnn` フォルダへTIFFを保存する。
   - Accumulation OFFは `{実験フォルダ名}-{シーケンス番号}_expo{露光時間:g}_gain{ゲイン:g}.tiff`。
   - Accumulation ONは `group_{group_index:04d}_expo{露光時間:g}_gain{ゲイン:g}/raw_{raw_index:04d}.tiff`。group indexは条件順で、Raw indexはgroup内の取得順である。

### 1.5 リトライと中断

1. Session開始（Trigger設定、必須node設定、必須Chunk準備、`StartGrabbing`）、Softwareのready待機・trigger発行、フレーム取得、画像変換、カメラ通信の失敗は撮影エラーとして扱う。Timestamp Chunkだけは任意であり、欠落・不可読時はhost timestampへfallbackする。Exposure/Gain Chunkの欠落・不可読は引き続き撮影エラーとする。
2. 1つの条件につき最大3回まで撮影を再試行する。
3. 異常Sessionを停止・解除し、0.5秒待機後に新しいSessionで再triggerする。
4. HardwareでRaw待機が共通Trigger Wait Timeoutを超えた場合は、その条件をskipせず通常シーケンス全体を中断する。`0` は無期限である。
5. 3回とも失敗した場合は通常シーケンス全体を中断する。
6. キャンセル要求がある場合は、次の条件へ進む前の確認タイミングで中断する。group途中で停止またはエラーになった場合、既に保存済みのRawは削除しない。

### 1.6 終了処理

1. `CaptureService` は成功または失敗と保存先名をUIへ通知する。
2. `MainWindow` は通常シーケンス撮影中の状態を解除する。
3. 無効化していた `Angle Scan` パネル、モーター設定、プレビュー設定を再び有効化する。
4. 共通Acquisition設定を再び有効化する。
5. プレビューを再開する。
6. 保存先表示を更新し、次回保存先表示タイマーを再開する。
7. 成功時はステータスバーに保存先フォルダ名を表示する。

## 2. 回転撮影

### 2.1 開始前のUI制御

1. ユーザーが `Angle Scan` タブで `Start` を押す。
2. `MainWindow` は回転撮影中の状態へ切り替える。
   - `Angle Scan` パネルを撮影中表示にする。
   - `Sequence` パネル、モーター設定、プレビュー設定の操作を無効化する。
   - 共通Acquisition設定を無効化する。
   - 次回保存先表示を更新するタイマーを停止する。
3. `PreviewWorker` へプレビュー停止を要求する。
4. プレビュー停止完了通知を受けてから、`AngleScanViewModel.start_angle_scan()` が呼ばれる。

### 2.2 モーターと走査設定の確定

1. `AngleScanViewModel` がモーター接続設定を作る。
   - COMポート
   - ModbusスレーブID
   - 1degあたりのモーター位置単位
2. `AzdCdRotationMotor` を作成する。
3. 回転撮影設定を作る。
   - 走査範囲
   - 角度間隔
   - 走査方向
   - 移動後待機時間
   - モーター速度
   - 撮影後に開始位置へ戻るかどうか
4. 設定値を検証する。
   - 走査範囲は正の値かつ90deg以下。
   - 角度間隔は0.5deg以上。
   - 角度間隔は走査範囲以下。
   - 走査方向は `positive`, `negative`, `both` のいずれか。
   - モーター速度と1degあたりのモーター位置単位は正の値。

### 2.3 角度走査計画の作成

1. 撮影開始時のモーター現在位置を相対0degとして扱う。
2. 走査方向に応じて角度列を作る。
   - `positive`: `0deg` から正方向へ進む。
   - `negative`: `0deg` から負方向へ進む。
   - `both`: 正方向の走査後、0degへ戻ってから負方向を走査する。
3. 角度間隔で走査範囲を割り切れない場合でも、終端角度は必ず撮影点に含める。
4. `both` の2本目に入る前の `0deg` は、反対方向へ移るための内部移動点として扱い、撮影点には数えない。
5. 各撮影角度を、1degあたりのモーター位置単位で絶対目標unitへ変換する。
6. 各移動は、絶対目標unit同士の差分から相対移動量を作る。
   - これにより、角度間隔ごとの丸め誤差が積み重ならない。
7. 露光時間リストとゲインリストは通常シーケンスと同じく昇順ソートし、直積を撮影条件にする。
8. 総撮影枚数は `撮影角度数 * 露光時間数 * ゲイン数` になる。

### 2.4 保存先とscan.jsonの作成

1. `ExperimentStorage.start_new_angle_scan()` が呼ばれる。
2. 現在の実験ブランチ直下を再スキャンし、既存の `angle_scan_nnn` の最大番号を確認する。
3. ルートフォルダと実験フォルダを必要に応じて作成する。
4. 次の連番として `angle_scan_nnn` フォルダを作成する。
5. `scan_id` は `asNNN` として作られる。
6. `angle_scan_nnn/scan.json` を保存する。
   - 走査範囲、角度間隔、走査方向
   - 1degあたりのモーター位置単位
   - 実際に保存対象になる撮影角度リスト
   - 移動後待機時間
   - モーター速度
   - 開始位置へ戻る設定
   - 露光時間・ゲインの撮影条件
   - Accumulation ON時のRaw枚数、`capture.accumulation_frames`、group directoryとRaw filenameの保存形式
   - リトライ上限
   - 保存名規則

### 2.5 各角度での移動と撮影

走査計画内の各移動について、以下を繰り返す。

1. キャンセル要求が出ていないか確認する。
2. 移動量が0でなければ、モーター移動前にプレビュー再開を要求する。
   - 回転中の様子を画面で確認できるようにするため。
3. モーターを相対移動量、指定速度、タイムアウト付きで移動する。
4. 現在の目標unitを内部状態として記録する。
5. その移動が撮影対象でなければ、次の移動へ進む。
   - `both` の2本目先頭の `0deg` が該当する。
6. 撮影対象であれば、設定された移動後待機時間だけ待つ。
7. 撮影直前にプレビュー停止を要求する。
8. プレビュー停止完了を最大5秒待つ。
9. 停止完了しない場合はタイムアウトとして回転撮影全体を中断する。
10. その角度で露光時間・ゲインの全組み合わせを順番に撮影する。
11. 各撮影前にキャンセル要求を確認する。
12. 進捗を `現在枚数 / 総枚数 / 現在角度` としてUIへ通知する。
13. カメラの露光時間とゲインを設定する。
14. AccumulationがOFFならSequenceと同じ1フレーム用Trigger Sessionで撮影する。ONなら同じ角度・条件で `N` 枚のRaw frameを取得するgroupとして扱う。
15. 共通Acquisition設定に従ってRawを取得する。Softwareではready待機後にSoftware Triggerを発行し、Hardwareでは外部triggerに対応するフレームを待つ。
16. HardwareでRaw待機が共通Trigger Wait Timeoutを超えた場合は、その条件をskipせずAngle Scan全体をエラー終了する。`0` は無期限である。
17. Accumulation ONでは各Rawを取得直後に保存し、groupが完成するまで次の条件または角度へ進まない。積算は `uint64` で行い、完成時に `65535` へclipした画像だけをPreviewへ通知する。
18. `scan_id`、目標角度、要求した露光時間・ゲイン、カメラから読戻した露光時間・Gain、Softwareではtrigger直前・HardwareではRaw取得時点のPC時刻、camera timestamp tickと周波数、ビット深度、`MsbAligned` 情報をTIFFメタデータとして作る。
19. 角度別サブフォルダへTIFF保存する。
    - 角度フォルダ名は `angle{角度:+06.1f}`。
    - Accumulation OFFのファイル名は `{scan_id}_angle{角度:+06.1f}_exp{露光時間:g}_gain{ゲイン:g}.tiff`。
    - Accumulation ONは `group_{condition_index:04d}_exp{露光時間:g}_gain{ゲイン:g}/raw_{raw_index:04d}.tiff`。

### 2.6 開始位置への復帰

1. `return_to_start` が有効で、現在位置が相対0degでない場合だけ実行する。
2. プレビュー再開を要求する。
3. 現在の目標unitの符号を反転した相対移動量で、開始位置へ戻す。
4. この復帰移動では撮影しない。

### 2.7 リトライと中断

1. Trigger Session開始、Softwareのready待機・trigger発行、Hardwareの外部trigger待機、取得、必須Chunk読戻し、画像変換、カメラ通信の失敗を撮影エラーとして扱う。Timestamp Chunkだけは任意であり、欠落・不可読時はhost timestampへfallbackする。
2. 1つの角度・露光時間・ゲイン条件につき最大3回まで撮影を再試行する。
3. 再試行前には0.5秒待機する。
4. HardwareでRaw待機が共通Trigger Wait Timeoutを超えた場合は、条件をskipせず回転撮影全体を中断する。`0` は無期限である。
5. 3回とも失敗した場合は回転撮影全体を中断する。
6. キャンセル要求がある場合は、各移動前または各撮影条件の前の確認タイミングで中断する。group途中で停止またはエラーになった場合、既に保存済みのRawは削除しない。

### 2.8 終了処理

1. `AngleScanService` は成功または失敗と保存先名をUIへ通知する。
2. `MainWindow` は回転撮影中の状態を解除する。
3. 無効化していた `Sequence` パネル、モーター設定、プレビュー設定を再び有効化する。
4. 共通Acquisition設定を再び有効化する。
5. プレビューを再開する。
6. 保存先表示を更新し、次回保存先表示タイマーを再開する。
7. 成功時はステータスバーに保存先フォルダ名を表示する。

## 3. Recording

1. プレビュー停止完了後、固定した露光時間とゲインを設定する。
2. `expected_frames=None` の共通Trigger Sessionを用意する。Sessionは正常な間、Recording全体で再利用し、取得失敗時だけ閉じて再armする。
3. AccumulationがOFFなら1 Raw frameを1フレームとして扱う。ONなら `N` 枚を1 groupとして扱い、Raw indexを `1` から `N` まで割り当てる。
4. **Software Recording**では、FPSまたはInterval入力から `frame_index` ごとの元の予定時刻を求め、キャンセルを監視しながらその時刻まで待つ。遅延してもindexを飛ばさず、`TriggerReady` 待機後にSoftware Triggerを1回発行する。
   - 要求rateが共通FPS Limitを超える場合はSessionを作成する前にエラーにする。FPSを共通FPS Limitへ自動的に丸めない。
5. **Hardware Recording**ではRecording側のFPSとInterval入力を使わず、外部triggerに対応するRaw frameを待つ。
   - 最初のRaw frameだけに共通Trigger Wait Timeoutを適用する。timeoutならRecordingをエラー終了する。
   - 最初の正常Raw到着時をDurationの `t=0` とし、開始前の待機時間はDurationに含めない。
   - 最初のRaw到着後はtriggerが止まってもTrigger Wait Timeoutエラーにせず、Duration終了を優先する。
6. Softwareではtrigger発行直前、HardwareではRaw frameのhost取得時点のmonotonic時刻から `actual_elapsed_ms` を計算する。Hardwareでは `target_elapsed_ms` を持たない。
7. Duration終了時にgroup途中であれば、既存groupの `N` 枚目まで取得して保存する。group完成後に終了し、Duration終了後に新しいgroupは開始しない。
8. TIFF保存キューへ元のRaw画像とメタデータを投入し、保存完了時に `frames.csv` へ追記する。
   - Accumulation OFFは `record-N` 直下へTIFFを保存する。
   - Accumulation ONは `record-N/group_{group_index:06d}/raw_{raw_index:04d}.tiff` へRawを保存する。group途中で停止またはエラーになっても、既に保存したRawは削除しない。
9. Accumulation OFFでは取得したRawをPreviewへ通知する。ONではgroup完成時にだけ、Rawの総和を `uint16` 範囲へclipした積算画像をPreviewへ通知する。積算画像は保存しない。
10. 正常終了、キャンセル、例外のいずれでもSessionを閉じ、Trigger設定を解除してカメラを通常状態へ戻す。

TIFFと `frames.csv` には、要求条件の `exposure_ms`・`gain` と、フレーム単位の読戻し値 `camera_exposure_ms`・`camera_gain` を区別して保存する。
さらにSoftwareではtrigger直前、HardwareではRaw frameのhost取得時点を表す `timestamp`、画像取得開始に対応する `camera_timestamp_ticks`、`camera_timestamp_frequency_hz`、取得元を表す `camera_timestamp_source` を保存する。
sourceが `camera` のtickはPTPを自動有効化しないため絶対日時として解釈しない。
Timestamp Chunkが使えない場合はsourceを `host` とし、`time.time_ns()` を1GHzのtickとして保存する。
pylonエミュレータではsourceを `simulation` とし、Software Trigger発行直後の `perf_counter_ns()` を周波数 `1000000000` の仮想timestampとして記録する。
Accumulation ONでは `frames.csv` の `filename` に `group_000001/raw_0001.tiff` のようなsession相対POSIXパスを記録する。

## 4. 撮影モードの主な違い

| 項目 | 通常シーケンス撮影 | 回転撮影 | Recording |
| --- | --- | --- | --- |
| UIタブ | `Sequence` | `Angle Scan` | `Recording` |
| 保存先 | `image_nnn` | `angle_scan_nnn` | `record-N` |
| 角度移動 | なし | あり | なし |
| 撮影条件 | 露光時間 x ゲイン | 角度 x 露光時間 x ゲイン | 固定露光時間 x ゲイン |
| Trigger | 条件ごとに1 RawまたはN Raw | 角度・条件ごとに1 RawまたはN Raw | Softwareは予定時刻、Hardwareは外部trigger |
| Hardware timeout | Rawごとに適用し、timeoutは全体エラー | Rawごとに適用し、timeoutは全体エラー | 最初のRawだけ適用。到着後はDurationを優先 |
| Accumulation ON | 条件groupへRaw保存 | 角度・条件groupへRaw保存 | Recording groupへRaw保存 |
| プレビュー | 撮影前に停止し、終了後に再開 | 移動中は再開し、撮影直前に停止 | 撮影中は停止し、終了後に再開 |
| 補助ファイル | なし | `scan.json` | `recording.json`, `frames.csv` |
| TIFFメタデータ | 露光時間、ゲイン、時刻、ビット深度など | 通常情報に加えて `scan_id` と目標角度など | Raw条件、時刻、読戻し値など |
