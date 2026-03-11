# nhk-radio-music-assistant

[Music Assistant](https://music-assistant.io/) 用の NHK Radio プロバイダーです。NHK ラジオのライブ放送とオンデマンド番組を Music Assistant から再生できます。

## 機能

### ライブ放送
NHK ラジオ第1 (R1)・ラジオ第2 (R2)・FM の3チャンネルをリアルタイムで再生できます。番組が切り替わると自動でメタデータ（番組名・サムネイル）が更新されます。

> R2 は夜間帯の放送がありません。

### オンデマンド
過去の放送番組をオンデマンドで再生できます。以下の方法で番組を探せます:

- **新着** — 最近公開された番組
- **ジャンル** — 音楽、ドラマ、教養など
- **五十音順** — あ行〜わ行

### 検索
キーワードでオンデマンド番組を検索できます。検索結果はシリーズ単位で返され、再生すると最新エピソードが流れます。

### ライブラリ
お気に入りのラジオ局やオンデマンドシリーズをライブラリに保存できます。

## 対応地域

東京・大阪・名古屋・札幌・仙台・広島・松山・福岡

設定画面で地域を選択すると、その地域のライブ放送情報が取得されます。

## インストール

### 前提条件

- Music Assistant サーバー (Docker)
- Python 3.12 以上

### デプロイ

`deploy.sh` で Music Assistant の Docker コンテナに直接デプロイします。

```bash
# リモートの Docker ホストにデプロイ
./deploy.sh user@hostname

# ローカルの Docker にデプロイ
./deploy.sh local
```

スクリプトは以下を自動で行います:
1. プロバイダーファイルをコンテナにコピー
2. [nhk-radio-python](https://github.com/hideosasaki/nhk-radio-python) SDK をインストール
3. コンテナを再起動

デプロイ後、Music Assistant の設定画面から **NHK Radio** プロバイダーを有効化してください。

## 開発

```bash
# 依存関係のインストール
pip install -e ".[dev]"

# テスト実行
pytest

# Lint
ruff check .
```

## 技術的な詳細

### オンデマンドのカスタムストリーム

NHK オンデマンドは AES-128 で暗号化された HE-AAC (48kbps) の HLS ストリームを配信しています。ffmpeg の HLS デマクサ経由で再生すると、暗号化セグメント境界でデコードエラーが発生し音飛びが生じます。

この問題を回避するため、`StreamType.CUSTOM` による独自のストリーム処理を実装しています:

1. マスタープレイリスト (.m3u8) を解析してサブプレイリストを取得
2. 暗号化キーを取得
3. 各セグメントをダウンロードして AES-128-CBC で復号
4. 復号済みの生 AAC バイトを Music Assistant に供給

ffmpeg は HLS プロトコルの処理をせず、純粋な AAC デコードのみを行うため、安定した再生が可能です。

### ライブ放送

ライブ放送は Music Assistant 標準の HLS ストリーム (`StreamType.HLS`) をそのまま使用します。

## 依存関係

- [nhk-radio-python](https://github.com/hideosasaki/nhk-radio-python) — NHK Radio API クライアント
- [music-assistant-models](https://github.com/music-assistant/models) — Music Assistant データモデル
- [cryptography](https://cryptography.io/) — HLS セグメントの AES-128 復号 (Music Assistant に同梱)

## ライセンス

Apache-2.0
