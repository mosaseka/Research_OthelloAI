# Egaroucid v0002 C++ converter

`egaroucid_v2_converter.cpp`は、生棋譜を検証・再生してPython学習器が読む
schema-v2 shard/receipt/manifestを生成する、外部ライブラリ不要のC++17実装です。

プロジェクトルートからコンパイルします。

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\converter\build_converter.ps1
```

これは次と同等です。

```powershell
New-Item -ItemType Directory -Force .\build | Out-Null
& 'C:\msys64\ucrt64\bin\g++.exe' `
  -std=c++17 -O3 -DNDEBUG -march=native `
  -Wall -Wextra -Wpedantic -pthread `
  -static -static-libgcc -static-libstdc++ `
  .\converter\egaroucid_v2_converter.cpp `
  -o .\build\egaroucid_v2_converter.exe
```

本番データを使わない自己テスト：

```powershell
.\build\egaroucid_v2_converter.exe --self-test
```

本変換：

```powershell
.\build\egaroucid_v2_converter.exe --workers 12
```

既定値は以下です。

- 入力: `resources/Egaroucid_Train_Data_v0002_0` と `_1`
- 出力: `data/processed/egaroucid_v2`
- manifest: `data/processed/egaroucid_v2/conversion_manifest.json`
- split seed: `20260715`
- split比率: train 0.9、validation 0.05、test 0.05
- worker数: 12

既存のPython版schema-v2 receiptは、source fingerprintと全shardの行数・サイズ・
SHA-256を再検証して再利用します。receiptがないsourceだけを変換します。

重要：以前のPython変換処理を先に`Ctrl+C`で停止してください。同じoutputへ
2つの変換器を同時実行してはいけません。中断はsource単位で安全に再開できます。

変換完了後のPython学習：

```powershell
python .\training\run_training_pipeline.py `
  --config .\config\train_v0002.json `
  --stage all `
  --device cuda:0
```

Python側の`all`は変換を行わず、`verify → overfit → train`を実行します。
