# OthelloAI_05

`original_04` を基に、終盤ルート再探索の深さ不整合を修正し、評価関数の
本学習・候補検証・段階的A/B対局を再現可能にした版です。Java本体は標準
ライブラリだけで動作し、引数なしの本番思考時間は約9.5秒/手のままです。

`resources/param.txt` と `resources/book.txt` は基準版から変更していません。
学習候補は `artifacts/` に別名で出力し、`-Dothello.param=PATH` で選択します。

## 必要環境

- JDK 11以上
- Python 3.10以上
- 学習時のみPyTorch
- v0002棋譜の変換時のみC++17対応g++（既定: `C:\msys64\ucrt64\bin\g++.exe`）
- 起動時の作業ディレクトリはこのREADMEのある `original_05`

生のEgaroucidデータ、展開データ、PyTorch checkpoint、対局のJSONLは配布対象に
含めません。

## コンパイルと起動

PowerShellで次を実行します。

```powershell
New-Item -ItemType Directory -Force build/current | Out-Null
javac -encoding UTF-8 -Xlint:all -d build/current OthelloAI_05.java
java -Xmx1g -cp build/current OthelloAI_05
```

起動後、初期化が終わるとstdoutへ `READY` を出します。続いてAIの色を一度だけ
`0` または `1` で入力し、AIへ着手させるたびに8文字の盤面を8行入力します。
出力はゼロ始まりの `y x evaluation` です。診断はstderrだけに出します。

テスト専用設定は次のとおりです。

| System property | Environment variable | 内容 | 本番既定値 |
|---|---|---|---:|
| `othello.moveTimeMs` | `OTHELLO_MOVE_TIME_MS` | 1手の時間 | 9500 ms |
| `othello.threads` | `OTHELLO_THREADS` | root探索スレッド数 | available processors |
| `othello.seed` | `OTHELLO_SEED` | 定石抽選seed | current time |
| `othello.param` | - | parameter file | `resources/param.txt` |
| `othello.book` | - | opening book | `resources/book.txt` |

## 回帰テスト

```powershell
New-Item -ItemType Directory -Force build/current,build/tests | Out-Null
javac -encoding UTF-8 -Xlint:all -d build/current OthelloAI_05.java
javac -encoding UTF-8 -Xlint:all -cp build/current -d build/tests tests/OthelloAIRegressionTest.java
java -Xmx1g '-Dothello.moveTimeMs=100' '-Dothello.threads=1' '-Dothello.seed=1' `
  -cp 'build/tests;build/current' OthelloAIRegressionTest
python -m unittest discover -s tests -p 'test*.py' -v
```

Javaテストは、固定10空き局面で評価順先頭以外の手が再探索されること、全childの
厳密alpha-betaとpolicy/valueが一致すること、再探索深さが残り9 plyであることを
検査します。ほかに合法手、反転、パス、終局、色交換、D4、parameter数、book、
評価再現性、TT手番分離、時間超過を検査します。

## 今回配置したv0002棋譜で学習する

棋譜から盤面shardへの変換はC++、GPU学習はPython/PyTorch、実戦探索はJavaで
分担します。Python学習コードは生棋譜を再生せず、C++が生成したmanifestと
train/validation/test shardだけを読みます。

resources配下の入力は次の展開済み2フォルダです。

    resources/Egaroucid_Train_Data_v0002_0
    resources/Egaroucid_Train_Data_v0002_1

### 1. C++変換器をコンパイルする

コンパイル対象は `converter/egaroucid_v2_converter.cpp` です。PowerShellでは
ビルドスクリプトを使います。

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File .\converter\build_converter.ps1
```

生成される実行ファイルは `build/egaroucid_v2_converter.exe` です。本番データを
読まない内蔵テストは次で実行できます。

```powershell
.\build\egaroucid_v2_converter.exe --self-test
```

### 2. C++変換器を実行する

以前のPython変換処理が動いている場合は、先にその端末で `Ctrl+C` を押して完全に
停止してください。同じoutputへPython版とC++版を同時実行してはいけません。

```powershell
.\build\egaroucid_v2_converter.exe --workers 12
```

引数を省略した場合は上記2入力、`data/processed/egaroucid_v2`、split seed
`20260715`、比率0.9/0.05/0.05を使用します。既存のPython版schema-v2 receiptと
shardをsource/output SHA-256まで検証し、完了済みファイルは再変換しません。

変換器は5,200ファイル・5,200万棋譜を検証・再生し、次を生成します。

- `data/processed/egaroucid_v2/{train,val,test}/...` のshard
- `data/processed/egaroucid_v2/_receipts/...` のsource別receipt
- `data/processed/egaroucid_v2/conversion_manifest.json`

CUIには新規変換速度、割合、経過時間、ETAを表示します。完了manifestが
`verified-full`になるまでPython学習は開始できません。

### 3. 変換済みshardをPythonで検証・学習する

設定は `config/train_v0002.json`、入口は
`training/run_training_pipeline.py` です。学習を起動せず計画だけ確認できます。

```powershell
python .\training\run_training_pipeline.py `
  --config .\config\train_v0002.json `
  --stage all `
  --device cuda:0 `
  --dry-run
```

実際の学習は次です。ここでは棋譜変換を行いません。

```powershell
python .\training\run_training_pipeline.py `
  --config .\config\train_v0002.json `
  --stage all `
  --device cuda:0
```

成功時の最初の候補は artifacts/param_candidate_v0002_001.txt です。同名が既に
存在する場合は連番を進め、既存候補やresources/param.txtを上書きしません。

`all`は次の順に実行し、前段が失敗すれば停止します。

1. verify: C++ manifestと全15,600 shardのpath・行数・サイズ・SHA-256を検証する
2. overfit: 4 phase各512件、合計2,048件の過学習gateを行う
3. train: full-pass学習、validation/test、候補parameter出力を行う

段階別に実行する場合は次の順です。

```powershell
python .\training\run_training_pipeline.py --config .\config\train_v0002.json --stage verify
python .\training\run_training_pipeline.py --config .\config\train_v0002.json --stage overfit --device cuda:0
python .\training\run_training_pipeline.py --config .\config\train_v0002.json --stage train --device cuda:0
```

通常はgateの飛ばし忘れを防ぐ`all`を推奨します。

v0002は盤面評価値ではなく完全棋譜です。ランダム着手N手を除き、強い相関を
避けるため各棋譜から最初のAI対戦局面だけを最大1件生成します。暗黙のパスも
再生し、教師値はJava本体と同じく勝者へ残り空きマスを加えた終局石差です。
59手ランダム着手の時点で既に終局した正常棋譜は学習局面なしとして集計・
スキップします。

変換結果は data/processed/egaroucid_v2 のsplit別shardへ保存します。入力と
出力のSHA-256をreceiptへ記録するため、中断後の再実行では完了済みファイルを
検証して棋譜再生を省略できます。変換完了manifestがverified-fullでなければ、
overfitとtrainは開始しません。

train/validation/testの分割はD4正規化した相対盤面をキーに固定します。同一局面や
その回転・反転形が複数棋譜に現れても、異なるsplitへ漏れません。

進捗は既定でstderrへ表示します。

- 対話CUI: 1行のバー、件数、割合、処理速度、経過時間、ETA
- リダイレクト時: ログを壊さない周期的な改行表示
- 学習開始前: 全shardのpath・行数・SHA-256整合性を表示付きで再検証
- 学習時: overfit走査、各epochのtrain/validation、testを個別表示
- 非表示: pipelineへ --quiet を付ける

## 旧盤面・評価値データで学習する

取得元、利用条件、provenanceは [data/README.md](data/README.md) を参照してください。
ZIPは展開せず、次へ置きます。

```text
data/raw/Egaroucid_Train_Data.zip
```

取得と全件検証は次の順です。

```powershell
python tools/fetch_egaroucid_data.py download
python training/parse_egaroucid.py --verify-all `
  --output artifacts/data_validation/egaroucid_full_stats.json
```

旧形式用の入口は、25,514,097件検証、4 phase各512件の2,048件overfit gate、
全splitのfull-pass学習、候補出力をこの順で実行します。前段が失敗すると停止します。

```powershell
python training/run_training_pipeline.py --config config/train_full.json --stage all
```

実行計画だけの確認には `--dry-run` を付けます。`config/train_small.json` は短い
動作確認専用であり、本候補の生成には使いません。full-pass設定は
`steps_per_epoch`、validation/test step、全source record上限がすべて0で、
phase 0～3が揃うことをコードでも強制します。

候補は `artifacts/param_candidate_###.txt` として出力され、既存ファイルを
上書きしません。

## 候補parameterの機械選別

```powershell
python tools/validate_candidate.py `
  --candidate artifacts/param_candidate_001.txt `
  --baseline resources/param.txt `
  --config config/candidate_gate.json `
  --report artifacts/param_candidate_001-validation.json
```

選別は次をすべて検査します。

- 25,436値で全値finite
- 同じ学習split契約を使う、全4 phaseのheld-out RMSE
- 全体RMSEが1%以上または0.1石以上改善
- 終盤phase 3のRMSEが悪化しない
- baselineとcandidateのD4方向差
- candidateについてJava/Pythonが4,096到達可能局面で完全一致

JSON reportの `decision.eligible_for_ab` が真の候補だけ対局へ進めます。

## 段階的A/B対局

AI本体、定石、seed、スレッド数、開始局面を共通にし、parameter pathだけを
変えます。Clientではなく `tools/arena.py` を使い、各開始局面を色交換した2局で
1ペアとします。

```powershell
$engine = 'java -Xmx1g -cp build/current -Dothello.param={param} OthelloAI_05'
$candidate = 'artifacts/param_candidate_001.txt'
$gate = 'artifacts/param_candidate_001-validation.json'

python tools/run_ab_stage.py --stage smoke `
  --candidate-param $candidate --gate-report $gate --engine-command $engine
python tools/run_ab_stage.py --stage screening `
  --candidate-param $candidate --gate-report $gate --engine-command $engine
python tools/run_ab_stage.py --stage acceptance `
  --candidate-param $candidate --gate-report $gate --engine-command $engine
python tools/run_ab_stage.py --stage practical `
  --candidate-param $candidate --gate-report $gate --engine-command $engine
```

`config/ab_stages.json` に事前登録した条件は次のとおりです。

| stage | ペア | 局数 | 1手 | 次段階の主条件 |
|---|---:|---:|---:|---|
| smoke | 10 | 20 | 50 ms | 全局完了、fault 0 |
| screening | 128 | 256 | 150 ms | fault 0、ペアscore 50%以上、平均石差0以上 |
| acceptance | 512 | 1,024 | 200 ms | ペア単位95% CI下限が50%超、平均石差が正、fault 0 |
| practical | 32 | 64 | 9.5 s | acceptance通過、全局完了、fault 0 |

各stageは候補・基準parameterのSHA-256と前stageの合格を検証します。色交換2局の
平均scoreを1つの独立ペア標本としてCIを計算します。timeout、不正着手、異常終了、
不完全な色交換ペアは合格になりません。

評価関数を採用するまではMPC、定石、割当削減、Future回収順を同時に変更しません。
採用後にそれぞれ単独で再調整・A/Bします。

## 設計資料

- [docs/current-architecture.md](docs/current-architecture.md): 盤面、評価器、探索、今回の終盤修正
- [docs/candidate-selection.md](docs/candidate-selection.md): 候補gate、ペア統計、段階的A/Bの詳細
- [docs/experiments.md](docs/experiments.md): original_04までの測定条件と結果
- [data/README.md](data/README.md): Egaroucidデータの取得、規約、全件検証

## 継承した資源ハッシュ

```text
param.txt  D2351C23DCD4CD09AEAD2A0D9DAC46F4BFF2FFFC18633C397156330F5FB26B0E
book.txt   39EB45BBE3E776462E5E4D1D21A686EEFDB280F35DD4A2C0F8B68509B3135F78
```
