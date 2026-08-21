# AI-Rabbit

池袋晶葉のウサちゃんロボットを作ろう

M5Stack CoreS3 を使ったウサギ型の卓上ロボット。話しかけると
キャラクターの声と口調で返事が返る。音声認識・LLM・音声合成すべてを
ローカルで動かすため、API 課金なしで動作する。

## ドキュメント

| | |
|---|---|
| [設計](docs/dialogue-system.md) | アーキテクチャ、実測値、決定の理由 |
| [PC 側の使い方](pc/README.md) | セットアップ、起動、設定、トラブル対応 |
| [CoreS3 のファーム](firmware/README.md) | 書き込み手順、配線なしの構成、プロトコル |

## 現在の状態

| # | 内容 | 状態 |
|---|---|---|
| 1 | PC 単体で対話ループ | 完了 |
| 2 | WebSocket サーバ + ダミークライアント | 完了 |
| 3 | CoreS3 のファーム | 実装済み・実機未検証 |
| 4 | 顔の描画と口パク | 最小限は実装済み |
| 5 | 割り込み・タッチ・加速度センサ | 一部のみ |

## 動かす

```powershell
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
ollama pull qwen3:4b-instruct
git config core.hooksPath tools/hooks

.venv\Scripts\python -m pc.main
```

VOICEVOX を起動しておく必要があります。詳細は [pc/README.md](pc/README.md)。
