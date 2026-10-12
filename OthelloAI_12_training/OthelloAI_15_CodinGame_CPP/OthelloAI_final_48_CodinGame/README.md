# OthelloAI final_48 — CodinGame版

大会で使用した `original_final_48` のwidth48 MSE評価器を、CodinGameの
Othello向け単一Javaソースへ移植した版です。デスクトップ版、Client、arenaは
変更しません。

## 提出するファイル

CodinGameへ貼り付けるのは `Player.java` の内容だけです。外部ファイル、
コマンドライン引数、環境変数は不要です。

提出クラスは意図的に `class Player`（`public`なし）です。`public`を付けると、
CodinGame側の一時ファイル名によってコンパイルエラーになる場合があります。

## 構成

- value：大会版と同じwidth48 MSE、`exact-mobility-v1`
- 元パラメータ：142,812値
- 元パラメータSHA-256：
  `9FA0820F15356561F8A576F3C306B48F0043BBAA3782A838D2CC6105BBA1D15B`
- policy：off
- opening book：off
- 探索：単一スレッド反復深化、PVS/NegaScout、TT、legacy MPC、bitboard終盤探索
- 通常手番：150 ms制限に対し内部探索115 ms
- 初回：初期化込み約800 msを目標、絶対上限900 ms
- 初期黒：対称な4候補から合法手を即決

初回timeout対策として、同期初期化するのは序盤で必要なphase 0だけです。残りの
3 phaseは初手出力後に低優先度スレッドで準備し、中盤へ入るまでに完了させます。

CodinGameのソース上限に収めるため、288テンソルごとに符号付き11bitへ量子化し、
DEFLATE圧縮後にJava文字列へ埋め込んでいます。これは大会版のdoubleモデルと
bit単位では同一ではありません。4,096局面検査では平均評価誤差0.069石、
最大0.364石、D4方向差0を確認しています。

## 再生成と検査

PowerShellでこのディレクトリへ移動して実行します。

```powershell
python .\tools\build_submission.py --template .\template\PlayerTemplate.java --param .\model\param.txt --output .\Player.java
javac -encoding UTF-8 .\Player.java
python .\tools\protocol_smoke.py --player .\Player.java
python .\tools\verify_evaluator.py --player .\Player.java --param .\model\param.txt
```

生成時には次を検査します。

- 142,812値、全finite
- 量子化・DEFLATE・15bit文字列のround-trip
- CRC32と元パラメータSHA-256
- CodinGameの100,000 UTF-16 code unit制限
- Javaコンパイル、初手、複数手番、stdout純度、EOF、応答時間
- 4 phase・passを含む4,096局面の元モデルとの評価誤差
- D4回転・反転の評価一致

## 注意

これはCodinGameの150 ms環境向けです。大学大会の9.5秒版と探索条件や並列性が
異なるため、CodinGame順位は大会版の棋力を直接示しません。また、量子化版なので
`original_final_48`との厳密なA/B比較にも使用しないでください。

## ライセンス

本移植にはEgaroucid 7.8.2由来のbitboard mobility、終盤着手順、探索設計が含まれ、
GPL-3.0-or-laterです。`Player.java`先頭の著作権・ライセンス表示を削除しないで
ください。
