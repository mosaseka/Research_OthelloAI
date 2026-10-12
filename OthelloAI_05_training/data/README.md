# Egaroucid公開学習データ

## 採用方針

盤面＋評価値の旧形式と、5,200万局の棋譜版v0002の両方を別設定で
サポートする。旧形式はconfig/train_full.json、今回resourcesへ配置した
展開済みv0002はconfig/train_v0002.jsonを使う。形式と教師値の由来が
異なるため、同じ設定やmanifestを流用しない。

公開元は[Egaroucid 学習データ](https://www.egaroucid.nyanyan.dev/ja/technology/train-data/)である。公開元の規約では自身のオセロAI開発などへの利用は許可される一方、データ自体の再配布は禁止されている。また、強制ではないが、データが役立った場合は作者への連絡またはEgaroucid公開データを使った旨の明記を希望している。生ZIP、展開後テキスト、抽出サンプル、大規模な処理済みデータはGitへ追加しないこと。本プロジェクトでは公開元が例示する次の出典を記載する。

> 山名琢翔: Egaroucid 学習データ, https://www.egaroucid.nyanyan.dev/ja/technology/train-data/

## 第一段階：盤面・評価値データ

公式情報と2026-07-15にGitHub Releases APIで確認した配布情報は次の通り。

| 項目 | 値 |
|---|---|
| ファイル | `Egaroucid_Train_Data.zip` |
| 直接URL | `https://github.com/Nyanyan/Egaroucid/releases/download/training_data/Egaroucid_Train_Data.zip` |
| GitHub Release tag | `training_data` |
| ZIPサイズ | 401,502,981 bytes |
| 局面数 | 25,514,097 |
| 公式SHA-256 | 未提供（GitHub APIの`digest`は`null`） |
| 公開日 | 2025-02-02 |

公式SHA-256がないため、取得時の真正性をハッシュだけで独立に証明することはできない。取得スクリプトはHTTPSの公式URL、GitHub APIのasset ID・サイズ・更新時刻を確認し、ダウンロード中に計算したSHA-256を`data/raw/Egaroucid_Train_Data.zip.provenance.json`へ記録する。同じファイルを再利用するときは、このローカルprovenanceと再計算値を照合する。provenance JSONだけはGit管理可能だが、ZIPは管理しない。

1行は次の厳密な形式である。

```text
<X/O/-だけからなる64文字><空白><符号付き整数スコア>
```

- マス順は`a1, b1, ..., h1, a2, ..., h8`。
- `X`はその局面の手番側、`O`は相手側、`-`は空きマス。
- スコアは手番側から見た予想最終石差。
- 石数15以下はEgaroucid 7.4.0 level 17で全進行を評価してnegamaxした値。
- 石数16以上はEgaroucid 7.5.1 level 17の自己対戦の終局石差。序盤7～59手のランダム着手中の局面は除外され、ランダム着手直後の局面が優先収録されている。

公式の石数別件数は次の通り。

| 石数 | 件数 |
|---:|---:|
| 4 | 1 |
| 5 | 1 |
| 6 | 3 |
| 7 | 14 |
| 8 | 60 |
| 9 | 322 |
| 10 | 1,773 |
| 11 | 10,649 |
| 12 | 67,245 |
| 13 | 434,029 |
| 14～63 | 各500,000 |
| 合計 | 25,514,097 |

## 取得と検証

Python 3の標準ライブラリだけを使う。プロジェクトルートで実行する。

```powershell
python .\tools\fetch_egaroucid_data.py metadata
python .\tools\fetch_egaroucid_data.py download
```

`download`は次の順に処理する。

1. GitHub Releases APIからtag・asset ID・URL・サイズ・公式digestを取得する。
2. `data/raw/Egaroucid_Train_Data.zip.part`へストリーム保存しながらSHA-256を計算する。
3. 401,502,981 bytesであることを確認する。
4. 検証成功後だけ`.part`を正式名へ置き換える。
5. URL、APIメタデータ、取得日時、ローカルSHA-256をprovenance JSONへ保存する。

途中で失敗した`.part`は診断用に残る。再実行時は上書きされる。既存ZIPを再取得せずオフラインで検証するには次を使う。

```powershell
python .\tools\fetch_egaroucid_data.py verify
```

別経路で得た信頼できるSHA-256がある場合は`--sha256`で追加照合できる。

```powershell
python .\tools\fetch_egaroucid_data.py verify --sha256 <64桁のSHA-256>
```

GitHubから自動取得できない場合は、公式URLをブラウザで開いて`data/raw/Egaroucid_Train_Data.zip`へ手動配置し、上の`verify`を実行する。公式digestがないため、手動配置後の初回`verify`はサイズ確認とSHA-256算出までであり、既知のハッシュとの真正性照合ではない点に注意する。

## ZIPを展開しない形式検証

まず先頭10,000レコードだけを検証する。テキストmember名をソートした決定的な順序で読み、盤面長、文字種、符号付き整数スコア、スコア範囲、石数を確認し、石数・スコア・`X/O/-`数の統計をJSONで標準出力へ出す。盤面そのものや抽出サンプルは保存しない。

```powershell
python .\training\parse_egaroucid.py --sample-size 10000
```

必要なら統計だけを無視対象の`processed/`へ保存できる。

```powershell
python .\training\parse_egaroucid.py --sample-size 10000 --output .\data\processed\sample_stats.json
```

小規模検証が通った後、全25,514,097レコードと公式の石数別件数を検証する。ZIP memberは`zipfile`で直接ストリーム展開され、ファイルシステムへは展開されない。

```powershell
python .\training\parse_egaroucid.py --verify-all --output .\data\processed\full_stats.json
```

`--verify-all`は全圧縮データを読み、レコードごとに検証するため時間がかかる。学習開始条件は、取得ファイルのサイズ／SHA-256検証、10,000件サンプル検証、全件数・石数分布検証がすべて成功していることとする。

ネットワークなしでスクリプト自体を確認するコマンドは次の通り。

```powershell
python .\tools\fetch_egaroucid_data.py self-test
python .\training\parse_egaroucid.py --self-test
```

## 動作確認用と本学習用の設定

`config/train_small.json`はreader・forward/backward・checkpoint・exportの動作確認専用である。`steps_per_epoch=1000`などの有限上限を持つため、25,514,097局面に対する本学習や候補採否には使用しない。

本学習には`config/train_full.json`を使う。この設定は次をコード側でも強制する。

- train/validation/testのstep上限はすべて`0`（全件）。
- train/validation/testの`max_source_records`もすべて`0`（全件）。
- phase 0～3が各epochとvalidation/testに実際に含まれなければ停止する。
- trainは各元局面を1色向きで使い、色向きとD4方向をseed付きでepochごとに変更する。validation/testは両色向きを固定して測る。
- splitはD4正規化盤面hashで固定し、回転・反転や色交換した同一局面を別splitへ漏らさない。
- `num_workers=0`とし、複数workerが同じ巨大ZIPをそれぞれ先頭から走査する重複I/Oを避ける。

`full_pass`設定で有限step数または有限元局面数を指定すると、学習開始前にエラーになる。これにより、単一ZIPの先頭に並ぶ序盤付近だけを各epochで反復する設定へ誤って戻ることを防ぐ。

## 全件検証から候補生成まで

推奨入口は`run_training_pipeline.py`の`all` stageである。

```powershell
python .\training\run_training_pipeline.py `
  --config .\config\train_full.json `
  --stage all `
  --device cuda:0
```

このコマンドは次を順番に実行し、前段が失敗した場合は後段へ進まない。

1. ZIPを展開せず全25,514,097局面を読み、形式・公式石数別件数を検証する。統計だけを`artifacts/data_validation/egaroucid_full_stats.json`へ保存する。
2. train splitの全streamを走査する決定的reservoir samplingでphaseごとに512件、合計2,048件を確保してoverfitする。学習前RMSEに対して設定値（既定10%）以上低下しなければ失敗とする。このsanity checkではparameterをexportしない。
3. 初期`resources/param.txt`から独立にfull-pass本学習を行い、最良validation checkpointをtestした後、`artifacts/param_candidate_###.txt`へ新規候補を出力する。既存候補と`resources/param.txt`は上書きしない。

実行予定だけを確認する場合は、生ZIPやPyTorchを読み込まない`--dry-run`を使う。

```powershell
python .\training\run_training_pipeline.py --stage all --device cpu --dry-run
```

長時間処理を段階別に実行する場合は次の通り。採用候補を作る正式手順では、`verify`と`overfit`が成功した後に`train`を実行する。

```powershell
python .\training\run_training_pipeline.py --stage verify
python .\training\run_training_pipeline.py --stage overfit --device cpu
python .\training\run_training_pipeline.py --stage train --device cuda:0
```

ネットワークと生データを使わない学習側の自己テストは次で実行する。

```powershell
python .\training\train_evaluator.py --config .\config\train_full.json --self-test
python -m unittest .\tests\test_training_data_supply.py
```

学習runのresolved config、metrics、checkpoint、export manifestは`artifacts/training_runs/`へ保存される。これらは再現・比較用の生成物であり、生データや抽出局面を含まない。raw ZIP、展開テキスト、抽出sampleは引き続きリポジトリへ追加しない。

## 第二段階：5200万局の棋譜データ（v0002）

これはEgaroucid for Console 7.8.0 level 11とEdax 4.5.5 level 11の対戦棋譜で、8～59手ランダム着手の各条件に100万局、合計5200万局を収録する。1テキストファイルは`f5d6`形式の10,000局で、0側はランダム着手8～33手、1側は34～59手。GitHubが付与した公式SHA-256は次の通り（2026-07-15 API確認）。

| ファイル | サイズ | 公式SHA-256 |
|---|---:|---|
| `Egaroucid_Train_Data_v0002_0.zip` | 1,303,950,421 bytes | `7123a56b647985b17f90b864e00ae5851cb015296315432965f4ad224ca7c87a` |
| `Egaroucid_Train_Data_v0002_1.zip` | 1,339,651,484 bytes | `9bbda568b8c3163c9d7e15c3d5a4b5d47693401d1b094928c1a8077b3538b73b` |

直接URL：

- `https://github.com/Nyanyan/Egaroucid/releases/download/training_data_v0002/Egaroucid_Train_Data_v0002_0.zip`
- `https://github.com/Nyanyan/Egaroucid/releases/download/training_data_v0002/Egaroucid_Train_Data_v0002_1.zip`

今回の配置はZIPそのものではなく、次の展開済みフォルダである。

    resources/Egaroucid_Train_Data_v0002_0
    resources/Egaroucid_Train_Data_v0002_1

converter/egaroucid_v2_converter.cppは各棋譜を初期局面から合法手として再生し、
省略されたパスを推定する。フォルダ名Nで指定された最初のN着手はランダム
区間なので、境界後の実際の手番へパスを正規化した最初の局面だけを最大1件
生成する。全中間局面を生成しないため、同じ終局値を持つ約13.8億件の強く
相関したsampleへ膨張しない。

教師値はsample時点の手番から見た終局石差で、Javaのend_gameと同じく
勝者へ残り空きマスを加える。ランダム境界で既に終局した正常棋譜は
skipped_no_positionとして保存し、不正データとは扱わない。

C++変換器はビットボードとsourceファイル単位の並列処理を使い、次を実施する。

- 8～59手の52フォルダ、各100ファイル、各10,000局を全件検証
- D4正規化した相対盤面をキーにtrain/val/testへ分割し、同一・回転・反転局面の漏洩を防止
- data/processed/egaroucid_v2のsplit別shardへ旧盤面形式で保存
- sourceとshardのSHA-256をreceiptへ保存し、中断後は検証して再開
- source、skip、split、ランダム手数、評価phaseの正確な件数をmanifest化

コンパイル対象と実行ファイルは次の通り。

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\converter\build_converter.ps1
.\build\egaroucid_v2_converter.exe --workers 12
```

以前のPython変換処理が動いている場合は先に停止し、同じoutputへ同時実行
しないこと。C++版は既存のPython版schema-v2 receiptをsource/shard SHA-256
まで検証して再利用する。

`verified-full` manifest生成後、Pythonは変換済みshardだけを検証・学習する。

```powershell
python .\training\run_training_pipeline.py `
  --config .\config\train_v0002.json `
  --stage all `
  --device cuda:0
```

このall stageは全shard verify、2,048件overfit、full-pass trainの順で動く。
Python側にはv0002棋譜の再生・変換処理を置かない。計画確認だけなら
`--dry-run`、進捗を消す場合は`--quiet`を付ける。C++変換器は5,200万局の
割合、新規変換速度、経過時間、ETAを、Pythonはshard検証と各学習epochの
進捗をstderrのCUIへ表示する。

生ZIP、展開済み棋譜、処理済みshard、receipt、checkpointは再配布・
Git管理しない。公開する場合はスクリプト、設定、集計値、許可された
parameter候補だけを対象にする。
