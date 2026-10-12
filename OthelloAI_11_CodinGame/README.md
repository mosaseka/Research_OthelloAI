# OthelloAI 11 — CodinGame版

このディレクトリは、`original_11`の暫定value評価と探索を、CodinGameの
[Othello](https://www.codingame.com/multiplayer/bot-programming/othello-1)
向け単一ソースへ移植したものです。元の`original_11`、Client、arenaは変更しません。

## 構成

- `Player.java`：生成後にCodinGameへ貼り付ける自己完結したJavaソース
- `model/param.txt`：value候補の25,436パラメータ（生成時だけ使用）
- `template/PlayerTemplate.java`：埋込みデータを除いた生成元
- `tools/build_submission.py`：量子化、埋込み、サイズ検査を行う生成ツール
- `tools/protocol_smoke.py`：コンパイル、入出力、応答時間、EOFのsmoke test

`Player.java`の実行時に外部ファイルは不要です。モデルデータを更新した場合は、
生成済み`Player.java`も作り直してからテストしてください。

## 採用している構成

- value：`original_11`暫定baselineの`exact-mobility-v1`
- value SHA-256：
  `FF16C4D3D697B1F838985091648CE4ACD63E708F14A1A9F693E19AFFFC6AB6B1`
- policy：off
- opening book：off
- 探索：単一スレッドの反復深化、PVS/NegaScout、TT、MPC、bitboard終盤探索
- 通常手番：CodinGameの150 ms制限に対し、内部探索を115 msで停止
- 初回：モデルを同期初期化し、その所要時間を1,600 msの初回予算から必ず差し引く（探索部分は最大1,500 ms、絶対上限1,800 ms）
- 初期黒：4候補が対称なので、モデル初期化後は探索せず合法手を即応答

policyはvalue-only版より弱かったA/B結果を受けて無効化しています。定石はコード量に
対する効果が小さく、外部ファイルも使用できないため含めていません。そのため、
デスクトップ版`original_11`の20石上限・44石安全策はこの提出版では発動せず、
CodinGame上で定石修正の効果を比較する用途には使えません。

## 生成、ビルド、smoke test

PowerShellでこのディレクトリへ移動して実行します。

```powershell
python .\tools\build_submission.py `
  --template .\template\PlayerTemplate.java `
  --param .\model\param.txt `
  --output .\Player.java

javac -encoding UTF-8 .\Player.java
python .\tools\protocol_smoke.py --player .\Player.java
python .\tools\verify_evaluator.py --player .\Player.java --param .\model\param.txt
```

生成ツールはパラメータ数・finite値、埋込みデータのround-trip、CRC/SHA、Java文字列
リテラル長、CodinGameの100,000 UTF-16 code unit制限を検査し、CUIへ進捗を表示します。
valueはphaseごとの対称int16へ量子化し、little-endian short列を15-bit単位でJava文字列へ
格納します。生成は決定的で、入力が同じなら`Player.java`も同じになります。

smoke testは一時ディレクトリへ改めてコンパイルし、次を検査します。

- `javac -encoding UTF-8`でコンパイルできる
- 初期局面の黒と、黒`d3`後の白が公式合法手を返す
- AIの初手と決定的な合法白着手を参照ルールで盤面へ適用し、同じ黒プロセスが
  複数合法手のある次局面を通常150 ms以内に処理する
- `actionCount=1`で`a1`と`h8`を正しく出力する
- 同一Javaプロセスで複数局面を処理する
- stdoutが小文字座標1行だけで、`READY`、評価値、ログなどを含まない
- 初回2,000 ms、通常手番150 ms以内に応答する
- stdinのEOF後に正常終了する

既定値は公式時間制限をそのまま検査します。ローカル環境の揺れを調べるだけなら、例えば
`--timing-slack-ms 20`を付けられますが、提出前の最終確認では0に戻してください。
`protocol_smoke.py`は実際に合法な盤面を使用するため、テスト専用モードを必要としません。
将来のテンプレートが明示的な`--legal-only`モードを持つ場合だけ、任意で
`--legal-only`を付けられます。提出用`Player.java`は通常モードで合格させてください。

## CodinGameへの提出

1. CodinGameの言語をJavaにする。
2. `Player.java`の内容全体をエディタへ貼り付ける。
3. 追加ファイルやコマンドライン引数を設定しない。
4. 標準出力が`d3`のような着手だけであることを確認する。

提出クラスは意図的に`class Player`（`public`なし）です。CodinGameは貼り付けた
ソースを別名の一時ファイルとしてコンパイルするため、`public class Player`へ変更すると
「should be declared in a file named Player.java」でコンパイルに失敗します。

CodinGameの入力は、起動時にplayer idとboard size、各手番に盤面8行、合法手数、
合法手文字列です。パスはrefereeが自動処理するため、`PASS`は出力しません。

## original_11との差異

- Client用の`READY`、`y x value`形式、JVM設定切替、METRICを削除
- root並列探索を削除し、単一スレッドで決定的に探索
- 外部`param.txt`をphase別int16量子化し、15-bit文字列へ埋め込んだvalueへ変更
- policyと`book.txt`を削除。したがって定石上限設定も提出版には存在しない
- Javaオブジェクト中心のTTをprimitive配列へ変更
- 150 ms向けに時間確認頻度と終盤完全読み開始点を調整

埋込み値は量子化されるため、デスクトップ版のdouble計算とbit単位では一致しません。
更新時は評価値parity、合法手、空き0～12の終盤solver一致、ローカルA/Bを別途確認して
ください。また、このsmoke testの時間合格はローカルPC上の結果であり、CodinGame実機の
時間を保証するものではありません。

## ライセンス

本移植にはEgaroucid 7.8.2由来のbitboard mobility、終盤着手順、探索設計が含まれ、
`original_11`と同じくGPL-3.0-or-laterです。`Player.java`先頭の著作権・ライセンス表示を
削除しないでください。再配布時はGPL-3.0-or-laterの条件と対応するソース提供義務に
従ってください。
