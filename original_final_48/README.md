# original_final_48

Linux arenaで`original_final`と比較するためのwidth48 MSE候補です。

## 比較対象

| ディレクトリ | value |
|---|---|
| `original_final` | width16 MSE、25,436パラメータ |
| `original_final_48` | width48 MSE、142,812パラメータ |

探索実装、定石設定、MPC設定は同系統です。`original_final_48`も
`DEFAULT_BOOK_STONES=4`で定石を無効化し、MPC既定値は`legacy`です。

valueパラメータのSHA-256は次のとおりです。

```text
9FA0820F15356561F8A576F3C306B48F0043BBAA3782A838D2CC6105BBA1D15B
```

## Linuxでのビルド

```bash
cd original_final_48
bash build_linux.sh
cd ..
```

Clientから直接使用する場合は次の形式です。

```bash
java Client --host tusedlsv01 --user 6324091 --port 25033 --ai original_final_48/OthelloAI_final_48 --time 9.5
```

arenaでは、Aに`original_final_48/OthelloAI_final_48`、Bに
`original_final/OthelloAI_final`を指定してください。採否は必ず色交換ペアで
判定し、timeout・異常終了・色別スコアも確認します。
