# original_10 学習ワークスペース

このディレクトリは、`original_10`用のvalue評価器とpolicy評価器を学習し、
Javaが検証可能なmodel bundleを生成するためのコードだけを収録しています。
長時間処理はBox同期フォルダではなく、`C:\Code\OthelloAI_10_training`で
実行してください。

既存データは読み取り専用で再利用します。

- value学習: `C:\Code\OthelloAI_05_training\data\processed\egaroucid_v2`
- policy変換元: `C:\Code\OthelloAI_05_training\resources\Egaroucid_Train_Data_v0002_0`
  と `Egaroucid_Train_Data_v0002_1`
- 初期パラメータ: Box側`original_10\resources\param.txt`

`prepare_local_workspace.ps1`はコードと設定だけをコピーします。既存の
05データ、学習結果、変換結果はコピーも変更もしません。

## 0. 前提

- 64-bit PythonとPyTorch
- CUDAを使う場合はCUDA対応版PyTorch
- C++17対応のg++（既定値は`C:\msys64\ucrt64\bin\g++.exe`）
- Box側に`original_10\resources\param.txt`があること

CUDAがPyTorchから見えているかは次で確認できます。

```powershell
python -c "import torch; print('torch=', torch.__version__); print('cuda=', torch.cuda.is_available()); print('device=', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CPU')"
```

## 1. ASCIIパスのローカル作業領域を作る

Box側の`original_10_training`で、次を一度だけ実行します。

```powershell
powershell -ExecutionPolicy Bypass -File .\prepare_local_workspace.ps1
Set-Location C:\Code\OthelloAI_10_training
```

`C:\Code\OthelloAI_10_training`が既に存在する場合、誤上書きを避けるため
スクリプトは停止します。

## 2. 短い自己テスト

これは学習や全データ変換を行いません。

```powershell
python .\training\train_evaluator.py --config .\config\train_value.json --self-test
powershell -ExecutionPolicy Bypass -File .\converter\build_converter.ps1
.\build\egaroucid_policy_converter.exe --self-test
python .\training\train_policy.py --config .\config\train_policy.json --self-test
python .\tests\compare_java_eval.py --self-test
python .\tools\validate_candidate.py --self-test
python .\tools\tune_mpc_ga.py --self-test
```

## 3. value評価器を学習する

次の1コマンドは、既存v2 shardの全件検証、phase層化した2,048件の
overfit gate、本学習の順に実行します。進捗はCUIへ表示されます。

```powershell
python .\training\run_training_pipeline.py --config .\config\train_value.json --stage all --device cuda
```

段階ごとに実行したい場合は次の3コマンドです。

```powershell
python .\training\run_training_pipeline.py --config .\config\train_value.json --stage verify
python .\training\run_training_pipeline.py --config .\config\train_value.json --stage overfit --device cuda
python .\training\run_training_pipeline.py --config .\config\train_value.json --stage train --device cuda
```

CPUだけを使う場合は`--device cuda`を`--device cpu`へ変更します。
本学習の候補は`artifacts\value_candidate_001.txt`へ出力され、既に同名
ファイルがある場合は番号を増やして保存されます。

overfit用2,048件は、shuffle済みshardから各phase 512件が揃った時点で
収集を止めるため、全4,600万超のtrain例をoverfit確認だけのために走査
しません。`--stage all`では最初に全shardのhashを1回検証し、その成功後に
起動するoverfit/trainではmanifest、パス、shard数の契約確認とstrict parseを
維持しながら重い再hashだけを省略します。各stageを個別に実行した場合は、
独立性を保つためその都度全hash検証を行います。

full-pass本学習では、各epochのtrain、validation、testがmanifestの件数と
完全一致したことも検査します。既定の色反転設定を含め、期待件数は
train 46,788,999件、validation 5,195,814件、test 5,206,794件です。
欠落・重複・途中終了があれば候補を出力せず停止します。

### 3.1 value候補を機械的に選別する

候補を作成したら、policy学習へ進む前に次を実行します。

```powershell
python .\tools\validate_candidate.py `
  --candidate .\artifacts\value_candidate_001.txt `
  --dry-run

python .\tools\validate_candidate.py `
  --candidate .\artifacts\value_candidate_001.txt
```

本検査は25,436値・finite・SHA-256、Java/Python 4,096局面一致、verified
test shard全件のrows/size/hash、phase別RMSE、D4方向差を確認し、結果を
`artifacts\candidate_validation_*.json`へ非上書きで保存します。
サンプルはphaseごとに4,096個の異なるD4正規局面を決定的に選び、重複局面
の教師値は平均します。RMSEは黒・白の両配置で測ります。基準paramは実際の
`legacy-v1`、候補は`exact-mobility-v1`として評価します。

全体RMSEが1%以上または0.1石以上改善し、phase 3が悪化しない候補だけが
`eligible_for_ab=true`になります。D4値も報告されますが、既定では
観測項目であり単独の採否条件にはしていません。

## 4. policy teacherデータをC++で変換する

コンパイル済みなら、ビルドコマンドは再実行不要です。

```powershell
powershell -ExecutionPolicy Bypass -File .\converter\build_converter.ps1
.\build\egaroucid_policy_converter.exe --workers 12
```

変換器は各棋譜のrandom prefix直後にあるlevel-11着手を教師とし、D4正規化
した局面hashで決定的に約1/16を採用します。合法手が1個だけの局面は
listwise CEと勾配が常に0になるため除外し、複数合法手があるrootだけを
保存します。出力は既存value shardとは別の
`data\processed\egaroucid_policy_v1`です。出力先が既に存在する場合は停止し、
既存データを上書きしません。

変換前に、05側value converterの`conversion_manifest.json`がschema 2、
`verified-full`、5,200 files、52,000,000 gamesであることを確認します。
この既存検証が全棋譜の合法性と終局を保証しているため、policy converterは
random prefixと直後のteacher合法性までを再生した時点で次の棋譜へ進みます。
同じ終局検査を5,200万回繰り返さず、policy生成に必要な契約は維持します。

進捗には処理ファイル数、棋譜数、採用件数、処理速度、経過時間、ETAが
表示されます。CPU論理コア数に応じて`--workers`を調整できます。

## 5. policy評価器を学習する

全教師データの検証後、各局面の全合法手を候補にしたlistwise cross entropy
で学習します。D4変換は盤面と教師着手へ同時に適用され、logitは各子局面の
raw評価値の符号を反転した値です。

```powershell
python .\training\train_policy.py `
  --config .\config\train_policy.json `
  --stage all `
  --device cuda `
  --init .\artifacts\value_candidate_001.txt
```

候補は`artifacts\policy_candidate_001.txt`へ非上書きで出力されます。
checkpoint、validation/test指標、CUI進捗は
`artifacts\policy_training_runs`に保存されます。
`--init`には手順3で生成した実際のvalue候補番号を指定してください。
省略時の現行`original_10\resources\param.txt`は自己テスト・fallback用です。
既定では4個のDataLoader workerが変換済みshardを重複なく分担します。
Windowsのメモリ制約やworker起動問題がある場合だけ、
`config\train_policy.json`の`num_workers`を`0`へ変更してください。
学習前のvalidationも測定してepoch `-1`のbest checkpointとして保存するため、
3 epochのいずれも改善しなければ悪化したpolicyはexportされません。

完了済みepochの`checkpoint_last.pt`から再開する例です。初回と同じconfig、
同じ`--init`を指定してください。schema、config、初期valueのSHA-256、
隣接する`checkpoint_best.pt`の整合性を確認してから次epochへ進みます。

```powershell
python .\training\train_policy.py `
  --config .\config\train_policy.json `
  --stage train `
  --device cuda `
  --init .\artifacts\value_candidate_001.txt `
  --resume .\artifacts\policy_training_runs\run_XXXXXXXXTXXXXXXZ\checkpoint_last.pt
```

## 6. Java用model bundleを作る

実際に生成された候補番号を指定します。

```powershell
python .\tools\assemble_bundle.py `
  --value .\artifacts\value_candidate_001.txt `
  --policy .\artifacts\policy_candidate_001.txt
```

`artifacts\bundles\model_candidate_001`（既存なら次番号）に、次の4ファイル
が生成されます。

```text
param.txt
policy.txt
model.properties
bundle_manifest.json
```

生成時にvalueとpolicyがそれぞれ「25,436個・全finite」であることと、
SHA-256が検査されます。Java実行に必要なのは先頭3ファイルです。

## 7. Boxへ戻す場所

候補を保存してA/Bする段階では、生成されたbundleディレクトリをそのまま
次へコピーしてください。

```text
C:\Users\mosas\Box\01_授業関連\3-1\計算機科学応用演習\2026_1\0_課題\
2026_07_15_ネットワークプログラミング\original_10\resources\candidates\
model_candidate_XXX\
```

その候補を直接試す場合は、`OTHELLO_MODEL_BUNDLE`へ候補内の
`model.properties`を指定できます。正式採用するときだけ、bundleの
`param.txt`、`policy.txt`、`model.properties`を次へ配置します。

```text
...\original_10\resources\param.txt
...\original_10\resources\policy.txt
...\original_10\resources\model.properties
```

正式配置は現行`param.txt`を置き換えるため、A/B検証前には行わないで
ください。`bundle_manifest.json`は学習履歴として候補フォルダへ残します。

## 8. MPC倍率を遺伝的アルゴリズムで探索する（任意）

これはモデル候補をA/Bで採用した後にだけ行う実験です。各個体について
同じAI・seed・思考時間を使い、MPC倍率だけを変えた色交換ペア対局を
`othello_arena.py`へ依頼します。次は実行例です。

```powershell
$Project = 'C:\Users\mosas\Box\01_授業関連\3-1\計算機科学応用演習\2026_1\0_課題\2026_07_15_ネットワークプログラミング'
python .\tools\tune_mpc_ga.py `
  --arena "$Project\othello_arena.py" `
  --candidate-ai "$Project\original_10\OthelloAI_10" `
  --mpc-mode legacy `
  --games 64 `
  --time-ms 200 `
  --threads 1 `
  --population 8 `
  --generations 5
```

進捗、経過時間、ETAはCUIへ表示されます。checkpointと対局記録、最終JSONは
`artifacts\mpc_ga`以下へ保存され、既存の最終JSONは上書きしません。
中断後は同じ引数へ`--resume`を加えます。timeout、反則、fault、不完全pair、
arena異常終了を含む個体は必ず負のfitnessとなり、正常完走個体には
ペアスコア率、同率時には平均石差を使います。最終JSONの`best`には、その
まま利用できるJVM property名と環境変数名も記録されます。

## 実装上の契約

- value/policyはいずれもJava互換の25,436パラメータ形式
- 特徴schemaは`exact-mobility-v1`
- mobilityは重複のない合法手数を`0..30`にclampし、黒を正、白を負として
  `30`で正規化
- policy損失ではraw child値をそのまま使い、tanhやclampを適用しない
- 既存の05 shard、raw棋譜、`original_10\resources\param.txt`は読み取り専用
- candidate、変換先、bundleはすべて非上書き

Egaroucid由来のアルゴリズムを含むため、本コードは`LICENSE`記載の
GPL-3.0-or-laterとして扱います。
