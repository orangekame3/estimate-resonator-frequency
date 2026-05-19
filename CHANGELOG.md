# Changelog

## 2026-05-20: 近接した共振ピークの選択改善

### 背景

64Qv2 の新規データセットでは、2 本目と 3 本目の共振周波数が近い MUX があり、従来の選択ロジックだけでは miss assignment が起きやすかった。

特に MUX00 では候補として以下の 5 本が検出されていた。

```text
10.120, 10.218, 10.284, 10.338, 10.432 GHz
```

従来の選択では右端の `10.432 GHz` が残り、左端の `10.120 GHz` が落ちていた。目視確認の結果、MUX00 は `10.432 GHz` を落とすのが妥当と判断した。

### 変更内容

- 近接候補の deduplication で、高パワー側の shift 幅を距離閾値に上乗せしないようにした。
- 初期選択後に弱い候補や高パワーのみの候補が残る場合だけ、候補全体から多様性を考慮して再選択する処理を追加した。
- 左外側に高パワー側で追跡幅のある候補が残り、右端候補が弱い場合に限って、右端を左外側候補へ入れ替える補正を追加した。

この補正は MUX 番号や周波数値を直接指定しない一般ルールとして実装している。設定ファイルや CLI の使い方は変更していないため、従来と同じ実行方法で使える。

### 64Qv2 での効果

修正後の MUX00 は以下になった。

```text
MUX00: 10.120, 10.218, 10.284, 10.338 GHz
```

64Qv2 全体では 15 MUX、60 resonators を検出した。

```text
input cases: 57
unique cases: 15
resonators: 60
```

### 64Qv3 への影響確認

`data/64Qv3_CheckResonatorSpectroscopy_latest_artifacts.zip` を最新コードで再解析し、既存ベースラインと比較した。

```text
baseline rows: 64
current rows: 64
missing: 0
added: 0
frequency changed: 0
optimal_power changed: 0
```

64Qv3 latest については、周波数と optimal power の出力差分はない。

### 実行した確認

```sh
python -m compileall src tools
```

```sh
uv run tools/analyze_artifacts.py \
  64Qv2_CheckResonatorSpectroscopy_latest_artifacts.zip \
  --out-dir analysis_outputs/64qv2_adaptive_diverse_mux00edgefix \
  --extract-dir data/extracted/regression_new_64qv2_latest \
  --no-images \
  --version 2
```

```sh
uv run tools/analyze_artifacts.py \
  data/64Qv3_CheckResonatorSpectroscopy_latest_artifacts.zip \
  --out-dir analysis_outputs/regression_existing_current_check \
  --extract-dir data/extracted/regression_existing_20260505 \
  --no-images
```
