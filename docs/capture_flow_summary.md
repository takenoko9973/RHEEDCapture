# Sequence・Angle Scan・Recordingの概要

Preview、Sequence、Angle Scan、Recordingは、共通Acquisition設定から作ったTrigger Sessionを使用する。
取得モードは `Software` と `Hardware` であり、Free Runは使用しない。

既定値は `Software`、Hardware Source `Line1`、Activation `RisingEdge`、Trigger Delay `0 us`、FPS Limit `Unlimited`、Accumulation `Off`（`N=1`）、Trigger Wait Timeout `0 s`（無期限）である。
Recording、Sequence、Angle Scanの実行中は共通Acquisition設定を変更できない。
Preview中の設定変更は、現在のSessionを閉じて現在値で再armすることで反映する。

Softwareでは、`TriggerReady` を待ってSoftware Triggerを発行し、1枚のRaw frameを取得する。
HardwareではSoftware Triggerを発行せず、外部FrameStartに対応するRaw frameを待つ。
Hardware待機中の無信号はPreviewのエラーにせず、最後に完成した画像を表示したままにする。
HardwareのTrigger Source、Activation、Delayが利用不能または設定拒否になった場合は、別の値へ変更せずエラーにする。

Sequenceは、露光時間とゲインの全組み合わせを順番に処理する。
Angle Scanは、モーターを角度計画に従って移動し、移動後の待機を終えてから、各角度で同じ条件処理を行う。
Recordingは固定した露光時間とゲインで連続取得する。
Software RecordingはFPSまたはIntervalの予定時刻に従い、要求rateが共通FPS Limitを超える場合は開始前にエラーにする。
Hardware RecordingはFPSとIntervalを使わず、最初のRaw frameを共通Trigger Wait Timeoutで待つ。
最初の正常Raw到着時をDurationの `t=0` とし、その後はtrigger停止時のtimeoutよりDuration終了を優先する。

AccumulationがOFFの場合、既存の単一TIFF保存形式を維持する。
ONの場合は、同一条件のRaw `N` 枚を1 groupとして扱い、各Rawを取得直後に保存する。
積算は十分広い整数型で画素ごとに行い、完成時に `65535` へclipした画像だけをPreviewへ通知する。
積算画像は保存せず、group途中で停止またはエラーになっても既に保存したRawを削除しない。

SequenceのON保存先は `group_{group_index:04d}_expo{exposure_ms:g}_gain{gain:g}/raw_{raw_index:04d}.tiff` である。
Angle ScanのON保存先は角度ディレクトリ配下の `group_{condition_index:04d}_exp{exposure_ms:g}_gain{gain:g}/raw_{raw_index:04d}.tiff` である。
RecordingのON保存先は `record-N/group_{group_index:06d}/raw_{raw_index:04d}.tiff` である。
RecordingではON時の `frames.csv` にgroupからの相対POSIXパスを記録し、`recording.json` の `storage` にgroupとRawの形式を記録する。

すべての保存Rawはプレビュー用CLAHEやグリッドを反映しない、コンバータ由来の16bit Raw相当TIFFである。
Timestamp Chunkが利用可能な場合はcamera timestampを使い、欠落または不可読の場合だけhost timestampへfallbackする。
Softwareの `timestamp` はSoftware Trigger発行直前、Hardwareの `timestamp` はRaw到着時点のPC時刻を表す。

PreviewとRecordingのstatus bar表示はRaw frame単位で、Raw count、Raw FPS、Accumulation progress `x/N` を示す。
HardwareのRaw待機中は `Waiting for trigger` を表示する。
SequenceとAngle Scanでは取得統計を表示しない。
