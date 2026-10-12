# OthelloAI_13

`original_11`の探索を固定し、評価関数だけを幅48のBCE学習済み候補へ
置き換えた実験版です。`original_11`とClientは変更していません。

## 主な差分

- パターンMLP: `2×patternLength → 48 → 48 → 1`
- パラメータ: 142,812個
- 学習目的: 勝敗BCE（勝ち1、引き分け0.5、負け0）
- Java探索値: `tanh(logit / 2) × 6400`
- value feature: `exact-mobility-v1`
- 定石: 既定値は`bookStones=4`（実質無効）
- 探索、MPC、終盤完全読み、Client標準入出力は`original_11`を維持

採用候補:

- `resources/value_param.txt`
- SHA-256:
  `B1DE15DEB14CAD293F916B2AF4EE177D631F0D5EAE0664E3E8986ED81ACFAD7B`

## ビルド

PowerShellでこのディレクトリへ移動し、次を実行します。

```powershell
powershell -ExecutionPolicy Bypass -File .\build_for_client.ps1
```

## Client

親ディレクトリに`Client.class`がある配置なら、次の形式です。

```powershell
java Client --ai original_13\OthelloAI_13 --time 9.5
```

定石ありを比較する場合だけ、JVMオプションをClientより前へ追加します。

```powershell
java -Dothello.bookStones=20 Client --ai original_13\OthelloAI_13 --time 9.5
```

既定は定石なしです。`book.txt`はA/B比較を可能にするため同梱しています。

## Arenaでの最初の比較

まず同じ探索条件で評価関数だけを比較するため、両者とも定石なし、
200 ms、1 thread、色交換ペアで`original_13`対`original_11`を実行します。
screeningは128ペア（256局）、有望なら9.5秒で32～64ペアです。

## 再検証

モデル件数・SHA-256・bundle契約:

```powershell
javac --release 11 -encoding UTF-8 -d test-build OthelloAI_13.java tests\OthelloAI13ModelTest.java
java -cp test-build OthelloAI13ModelTest
```

独立したPython評価器との4,096局面一致:

```powershell
python .\tools\compare_java_eval.py --positions 4096 --seed 20260724
```

作成時の結果は整数値・feature不一致0、変換後raw値の最大絶対誤差
`1.110e-16`でした。

## モデルの意味

BCEモデルが返す値は最終石差ではなく、黒視点の勝利logitです。
Javaでは次の恒等式で従来探索の符号付き尺度へ写像します。

```text
2 * sigmoid(logit) - 1 = tanh(logit / 2)
```

表示上の`eval`は「予測石差」ではありません。概算勝率は
`sigmoid(logit)`ですが、探索後の評価値は確率校正された値とは限りません。
