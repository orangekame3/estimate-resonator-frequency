## 処理の流れ

1. 測定器由来の偽応答を除外する.
2. ベアシフト境界を検出する. 境界より上を高パワー帯, 境界より下を低パワー帯とする.
3. 高パワー帯のピークを検出し, グループ化する. 現在は単純にピークを左から順に見ていき, 右下にあれば同じグループ, 右上にあれば新しいグループとしている.
4. 低パワー帯のピークを検出する.
5. 高パワー帯のピークと低パワー帯のピークを対応づける.
6. 対応づけられた応答それぞれについて, 近くにある応答同士をグループ化する.
7. 各応答グループについて, 最大スコアの応答のみを残す.
8. 残った応答のスコア上位`num_resonators`個を真の応答とみなす.
9. 各応答について, 2で推定したベアシフト境界と応答を構成するピークの座標から, 応答個別のベアシフト境界を推定する.
10. パワー帯毎の相関係数から使用可能なパワー下限を推定する. 2で推定した境界を起点とし, 隣接パワー帯同士の相関係数が `minimum_usable_power.correlation_coefficient_min` を下回らない下限のパワーを採用する.

## 応答スコア

1. 高パワー帯のピークが存在する.
2. 高パワー帯のピークが周波数方向に大きくシフトしているほど高スコア.
3. 低パワー帯のピークが存在する.
4. 高パワー帯のピークの曲がりが強いほど高スコア.
5. 高パワー帯・低パワー帯関係なく, 最も突出したピークの突出度が高いほど高スコア.

1 -> 5の優先順位で順序づける.

## 設定ファイル

- `remove_false_spike`: 測定器由来の偽応答の除外に使うパラメータ. 除外範囲の配列
- `bare_shift_boundary_estimator`: ベアシフト境界検出の設定. 詳しくは[ベアシフト境界設定](#ベアシフト境界設定)を参照.
- `minimum_usable_power`: 使用可能パワー下限の推定に使うパラメータ.
- `minimum_usable_power.correlation_coefficient_min`: 隣接パワー帯同士の相関係数の下限. これを下回った時, 使用不可(ノイズが多すぎる)と判断する.
- `estimate_resonator_frequency`: 応答の検出に使うパラメータ. 以下それぞれのパラメータについて解説
- `num_resonators`: 検出する共振器の数
- `find_peaks_conf_(high/low)`: (高/低)パワー帯のピーク検出に使うパラメータ
- `find_peaks_conf_*.smooth_sigma`: 平滑化の強さ
- `find_peaks_conf_*.fp_conditions.distance`: 検出するピーク同士の最低距離(単位はxの1目盛)
- `find_peaks_conf_*.fp_conditions.prominence`: 検出するピークの最低突出度. この値が**低い**ほど敏感にピークを検出する
- `group_peaks_conf`: 高パワー帯のピークのグループ化に使うパラメータ
- `group_peaks_conf.x_backward_max`: ピークが逆側に曲がっていてもこの値までは同じグループとみなす(単位はxの1目盛)
- `group_peaks_conf.x_distance_max`: yの1目盛につきこの値以内の傾きなら同じグループとみなす(単位はxの1目盛)
- `compose_resonances_conf`: 高パワー帯のピークと低パワー帯のピークの対応づけに使うパラメータ
- `compose_resonances_conf.x_distance_max`: 高パワー帯の一番下のピークと低パワー帯のピークについて, yの1目盛につきこの値以内の傾きなら同じ応答のピークと見做して対応づけを行う(単位はxの1目盛)
- `compose_resonances_conf.x_backward_max`: 低パワー帯のピークの周波数 < 高パワー帯の一番下のピークの周波数 だったとしても, その差がこの値以内なら同じ応答のピークと見做して対応づけを行う(単位はxの1目盛)
- `group_resonances_conf`: 対応づけ後の応答同士のグループ化に使うパラメータ
- `group_resonances_conf.x_distance_max`: この値以内にある応答同士を同グループとみなす(単位はxの1目盛)

## ベアシフト境界設定

### 高周波強度による境界推定

- `strength_limit`: ベアシフト境界として認める高周波強度の最大値

```
  "bare_shift_boundary_estimator": {
    "type": "high_frequency_strength",
    "args": {
      "strength_limit": 4.0
    }
  },
  ...
```

### 手動境界値設定

- `low_power`: 低パワー帯(=応答が真っ直ぐな帯域)のピーク検出に使うパワー
- `high_power_min`: 高パワー帯(=応答が曲がる帯域)のピーク検出に使うパワー下限
- `high_power_max`: 高パワー帯(=応答が曲がる帯域)のピーク検出に使うパワー上限

```
  "bare_shift_boundary_estimator": {
    "type": "config",
    "args": {
      "low_power": -25.0,
      "high_power_min": -20.0,
      "high_power_max": 0
    }
  },
  ...
```

## インストール

```
uv sync
```

## 実行例

```
cp examples/config/config_64q_example.json ./config_64q.json
uv run src/main.py -c config.json -f /path/to/64q_data.json --mux 0
```

main.pyの出力オプション

- `--image-dir <image_dir>`: <image_dir>に実験画像・マーク済み画像・ベアシフト境界分析画像を出力する.

## 出力

- `resonators`: 共振器情報
- `resonators.[].mux`: 共振器が属するMUX
- `resonators.[].qubit`: 共振器に対応するqubitのインデックス
- `resonators.[].frequency`: 共振器の共振周波数(GHz)
- `resonators.[].bare_shift_boundary`: ベアシフト境界情報
- `resonators.[].bare_shift_boundary.high_power_max`: 高パワー領域の上限(dB)
- `resonators.[].bare_shift_boundary.high_power_min`: 高パワー領域の下限(dB)
- `resonators.[].bare_shift_boundary.low_power_max`: 低パワー領域の上限(dB)
- `resonators.[].bare_shift_boundary.low_power_min`: 低パワー領域の下限(dB)
- `resonators.[].optimal_power`: 推奨パワー(dB)

```
{
  "resonators": [
    {
      "mux": 11,
      "qubit": 44,
      "frequency": 6.239999999999946,
      "bare_shift_boundary": {
        "high_power_max": 0.0,
        "high_power_min": -20.0,
        "low_power_max": -25.0,
        "low_power_min": -40.0
      },
      "optimal_power": -35.0
    },
    ...
  ]
}
```
