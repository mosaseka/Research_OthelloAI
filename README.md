# Research_OthelloAI

オセロAIの探索・評価関数の学習・対局検証と、CodinGame向けのJava／C++移植をまとめた研究用リポジトリです。複数の開発段階をフォルダごとに保存し、学習したモデルや探索の変更を比較できるようにしています。

## リポジトリ構成

| フォルダ | 内容 | 詳細 |
| --- | --- | --- |
| `OthelloAI_05_training` | Java版AI、Egaroucidデータの変換、評価関数の学習、候補検証、A/B対局 | [README](OthelloAI_05_training/README.md) |
| `OthelloAI_10_training` | value（局面評価）とpolicy（着手評価）の学習、モデルの出力・検証 | [README](OthelloAI_10_training/README.md) |
| `OthelloAI_10_CodinGame` | 学習済み評価関数を埋め込んだCodinGame向けJava版 | [README](OthelloAI_10_CodinGame/README.md) |
| `OthelloAI_11_training` | value評価関数の追加学習、対戦ログの診断、候補モデルの比較 | [README](OthelloAI_11_training/README.md) |
| `OthelloAI_11_CodinGame` | 11系の評価関数・探索を移植したCodinGame向けJava版 | [README](OthelloAI_11_CodinGame/README.md) |
| `OthelloAI_12_training` | valueの継続学習設定（`value_12a`）、診断・検証ツール、15系C++版 | [README](OthelloAI_12_training/README.md) |
| `OthelloAI_13_training` | 隠れ層の幅を16から48へ拡張し、MSE／BCEの学習を比較する実験 | [README](OthelloAI_13_training/README_WIDTH48.md) |
| `OthelloAI_14_CodinGame_CPP` | Java版を基準にしたC++17移植、探索・評価の最適化候補、回帰テスト | [README](OthelloAI_14_CodinGame_CPP/README.md) |

15系C++版は、[OthelloAI_12_training/OthelloAI_15_CodinGame_CPP](OthelloAI_12_training/OthelloAI_15_CodinGame_CPP/README.md) に収録しています。

フォルダ番号は開発・実験の系列を表します。各候補の棋力は、同じ条件での対局結果をもとに判断してください。個別READMEに登場する `original_XX` は、開発時の元プロジェクト名です。

## GUIで対戦する

WindowsとLinuxで同じ対戦用JARを使えます。ビルドにはJDK 25、起動にはJava 25と、OS・CPUに合った[JavaFX 25 SDK](https://gluonhq.com/products/javafx/)が必要です。Linuxではグラフィカルなデスクトップ環境と[GTK 3.20以降](https://openjfx.io/highlights/25/)も必要です。

- **Windows**では `run.vbs` をダブルクリックすると、コンソールを表示せずに起動します。端末からは `.\run.bat` でも起動できます。JavaFX SDKを既定の `C:\Program Files\Java\javafx-sdk-25` 以外に置いた場合は、環境変数 `JAVAFX_LIB` にSDKの `lib` フォルダの絶対パスを設定してください。
- **Linux**では、展開したSDKへのパスを指定して実行します。

  ```sh
  JAVAFX_LIB="$HOME/javafx-sdk-25/lib" sh run.sh
  ```

ビルドだけ行う場合は、`run.bat --build-only` または `sh run.sh --build-only` を使います。別のPCへ移すときは `build/othello_gui/dist/` を丸ごとコピーしてください。このフォルダに `othello.jar` とAIのモデルが入ります。移動先で、このフォルダから次のコマンドで起動できます。

```text
java --enable-native-access=javafx.graphics,ALL-UNNAMED --module-path "<JavaFX SDKのlibフォルダ>" --add-modules javafx.controls -jar othello.jar
```

タイトル画面と対局画面の右上にある「全画面表示」ボタン、または `F11` キーで全画面に切り替えられます。全画面を解除するには `Esc` キー、`F11` キー、または「全画面を解除」ボタンを使います。

## 主な技術

CodinGame版では、次の仕組みを使っています。採用範囲や設定は版ごとに異なります。

- 64ビットのbitboardによる合法手・反転石の計算
- 局面の段階に応じた4フェーズの学習済み評価関数
- 反復深化、negamax alpha-beta、PVS／NegaScoutによる探索
- 置換表（Transposition Table）とMPCによる探索の効率化
- 終盤の完全読み
- 学習済みパラメータの量子化と、提出ソースへの埋め込み

CodinGame向けの `Player.java`／`Player.cpp` は、実行時に外部モデルファイルを読み込まない単一ソースです。これらの提出版ではpolicyと定石を無効にし、value評価と探索を使用しています。

## 必要な環境

| 用途 | 必要なもの |
| --- | --- |
| リポジトリの取得 | Git |
| Java版のコンパイル・検証 | JDK（Java 11互換以上）、Python |
| C++版のコンパイル・検証 | C++17対応のg++、Python |
| 評価関数の学習 | Python 3.10以上、PyTorch、学習データ |
| GPUを使った学習 | CUDA対応版PyTorchと対応GPU |
| 同梱の `.ps1` スクリプト | Windows／PowerShell |

以下の例はPowerShell用です。`python`、`javac`、`g++` を使う場合は、それぞれ実行できるようにしておいてください。

## C++版を試す

リポジトリを取得し、14系の生成済みソースをコンパイルします。

```powershell
git clone https://github.com/mosaseka/Research_OthelloAI.git
Set-Location .\Research_OthelloAI\OthelloAI_14_CodinGame_CPP

New-Item -ItemType Directory -Force .\build | Out-Null
g++ -std=c++17 -O2 -Wall -Wextra -pedantic -finput-charset=UTF-8 .\Player.cpp -o .\build\Player.exe
python .\tests\protocol_smoke.py --player .\build\Player.exe
```

`Player.cpp` は幅16の基準版（`cpp16_baseline`）です。CodinGameへ提出する場合は、対応するC++の言語設定を選び、ファイル全体をエディタへ貼り付けます。入出力テストや候補の評価を行ってから提出してください。

モデル・テンプレートから全候補を再生成してビルドする場合は、同じフォルダで次を実行します。この操作は生成済みのソースも更新します。

```powershell
powershell -ExecutionPolicy Bypass -File .\build_all.ps1
```

全体の回帰テストには、コンパイル済みの11系Java版も必要です。[C++版README](OthelloAI_14_CodinGame_CPP/README.md)と [test_all.ps1](OthelloAI_14_CodinGame_CPP/test_all.ps1)を参照し、`-JavaClassPath` で手元のJavaクラスの場所を指定してください。

## Java版を試す

リポジトリのルートから、次を実行します。

```powershell
Set-Location .\OthelloAI_11_CodinGame
javac -encoding UTF-8 .\Player.java
python .\tools\protocol_smoke.py --player .\Player.java
python .\tools\verify_evaluator.py --player .\Player.java --param .\model\param.txt
```

CodinGameへ提出する場合は、言語をJavaにして `Player.java` 全体を貼り付けます。モデルやテンプレートを変更した場合は、個別READMEの手順で `Player.java` を再生成してください。

Java／C++のCodinGame版は、ゲーム側から盤面と合法手を受け取り、`d3` のような座標を返すプログラムです。手動操作用の画面はありません。05系Java版の `READY`／`y x evaluation` 形式とは入出力が異なります。

## 学習・モデル比較

学習は、各 `*_training` フォルダのREADMEと設定ファイルに従って行います。基本の流れは次のとおりです。

1. データの出典・利用条件を確認し、必要な入力データを用意する。
2. データを変換し、manifest・ハッシュ・件数を検証する。
3. 小規模な動作確認を行い、評価関数を学習する。
4. 出力したパラメータの形式、有限値、Java／Python間の評価の一致を確認する。
5. 同じ初期局面で先後を入れ替えたA/B対局を行い、勝敗・石差・応答時間・異常終了を比較する。

設定やスクリプトには、開発環境の絶対パスや、このリポジトリに含まれない元のJavaソース・モデルへの参照が残っています。実行前に入力データ、初期モデル、出力先の設定を手元の環境に合わせてください。データやチェックポイントが別途必要なため、cloneだけで全学習を再開できる構成ではありません。

幅16のモデルは25,436パラメータ、幅48のモデルは142,812パラメータです。**両者には互換性がありません。** 幅48のモデルは対応するローダー・評価器を使い、幅16用のモデルファイルへそのまま置き換えないでください。

## 学習データと収録対象

Egaroucidの学習データを利用しています。

> 山名琢翔: Egaroucid 学習データ

取得元と利用条件は、[OthelloAI_05_training/data/README.md](OthelloAI_05_training/data/README.md)にまとめています。

リポジトリには、ソース、設定、ドキュメント、検証用ツールと、一部の学習済みパラメータを収録しています。再配布不可のEgaroucid生データ・展開データ・処理済みサンプル、学習チェックポイント、ビルド生成物などは収録していません。除外範囲は、ルートと各フォルダの `.gitignore` を参照してください。

## ライセンス・出典

本リポジトリには、山名琢翔（Nyanyan）氏のEgaroucid 7.8.2に由来する探索・bitboard実装が含まれます。該当するコードは各フォルダのGPL-3.0-or-laterの表記に従い、生成した提出ソースでも著作権・ライセンス表示を保持してください。

詳しくは、各フォルダの `LICENSE` と、C++版の [THIRD_PARTY_NOTICES.md](OthelloAI_14_CodinGame_CPP/THIRD_PARTY_NOTICES.md)、[MODEL_PROVENANCE.md](OthelloAI_14_CodinGame_CPP/MODEL_PROVENANCE.md)を参照してください。コードのライセンスと学習データの利用条件は、それぞれの記載を確認してください。
