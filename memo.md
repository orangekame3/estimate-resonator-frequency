# 解析メモ

## 前提

リポジトリ直下で実行する。

```sh
cd /Users/orangekame3/src/github.com/orangekame3/estimate-resonator-frequency
```

画像出力時に `src/bare_shift.py` が `matplotlib` を使うため、`pyproject.toml` に `matplotlib` を追加して `uv sync` した。

```sh
uv sync
```

## 推奨: Python スクリプトで解析する

長い shell ワンライナーを使わずに再実行できるよう、以下のスクリプトを追加した。

```text
tools/analyze_artifacts.py
```

このスクリプトは ZIP を入力にして、以下をまとめて実行する。

- ZIP 展開
- `_0.json` の抽出
- `z` データ digest による重複除外
- `src/main.py` による解析
- 画像出力
- `result.json` / `resonators.csv` / summary plot の作成
- marked plot だけの切り出し

使い方:

```sh
uv run tools/analyze_artifacts.py <artifact.zip> \
  --out-dir <output_dir> \
  --extract-dir <extract_dir> \
  --marked-dir <marked_plot_dir>
```

初回データを再解析する場合:

```sh
uv run tools/analyze_artifacts.py \
  data/64Qv3_CheckResonatorSpectroscopy_latest_artifacts.zip \
  --out-dir analysis_outputs/script_20260505_all \
  --extract-dir data/extracted/script_20260505_all \
  --marked-dir analysis_outputs/script_marked_20260505
```

2026-05-12 に追加でダウンロードした MUX08 データを再解析する場合:

```sh
uv run tools/analyze_artifacts.py \
  64Qv3_CheckResonatorSpectroscopy_20260512_artifacts.zip \
  --out-dir analysis_outputs/script_20260512_mux08 \
  --extract-dir data/extracted/script_20260512_mux08 \
  --marked-dir analysis_outputs/script_marked_20260512
```

実行確認済みの出力:

```text
analysis_outputs/script_20260512_mux08/result.json
analysis_outputs/script_20260512_mux08/resonators.csv
analysis_outputs/script_20260512_mux08/frequency_by_qubit.png
analysis_outputs/script_20260512_mux08/optimal_power_by_qubit.png
analysis_outputs/script_20260512_mux08/images/0e2e5a6ba3c4cd5b456b8048329cd7c8_MUX08_1_marked.png
analysis_outputs/script_marked_20260512/MUX08_marked.png
```

実行結果:

```text
input cases: 4
unique cases: 1
resonators: 4
```

以降の shell 手順は、スクリプト化前に実行した内容の記録として残している。

## 2026-05-12: shift 優先ロジックへの修正

このデータでは「ベアシフトしている応答」が答えなので、低パワー側の強いピークや shift していないピークを優先すると失敗する。

修正前の `Resonance.score` はおおむね以下の優先順位だった。

1. 高パワー帯ピークがある
2. 低パワー帯ピークがある
3. 曲がり
4. prominence

このため、最新 MUX08 では shift 幅 0 の `10.506 GHz` / `10.576 GHz` 付近の候補が選ばれてしまった。

修正後は `src/estimate_resonator_frequency.py` の `Resonance.score` に `high_power_x_span` を追加し、以下の優先順位にした。

1. 高パワー帯ピークがある
2. 高パワー帯ピークが周波数方向に shift している
3. 低パワー帯ピークがある
4. 曲がり
5. prominence

変更箇所:

```text
src/estimate_resonator_frequency.py
```

修正後の最新 MUX08 再解析:

```sh
uv run tools/analyze_artifacts.py \
  64Qv3_CheckResonatorSpectroscopy_20260512_artifacts.zip \
  --out-dir analysis_outputs/shift_priority_20260512_mux08 \
  --extract-dir data/extracted/shift_priority_20260512_mux08 \
  --marked-dir analysis_outputs/shift_priority_marked_20260512
```

出力:

```text
analysis_outputs/shift_priority_20260512_mux08/result.json
analysis_outputs/shift_priority_marked_20260512/MUX08_marked.png
```

修正後の最新 MUX08 結果:

```text
q32: 10.118 GHz, optimal -35 dB
q33: 10.452 GHz, optimal -40 dB
q34: 10.246 GHz, optimal -40 dB
q35:  9.934 GHz, optimal -40 dB
```

初回 16 MUX データでも、画像なしで全件解析が通ることを確認した。

```sh
uv run tools/analyze_artifacts.py \
  data/64Qv3_CheckResonatorSpectroscopy_latest_artifacts.zip \
  --out-dir analysis_outputs/shift_priority_20260505_no_images \
  --extract-dir data/extracted/shift_priority_20260505 \
  --no-images
```

結果:

```text
input cases: 64
unique cases: 16
resonators: 64
```

## 初回データ解析

入力 ZIP:

```text
data/64Qv3_CheckResonatorSpectroscopy_latest_artifacts.zip
```

展開先:

```sh
mkdir -p data/extracted/64Qv3_CheckResonatorSpectroscopy_20260505
unzip -q -n data/64Qv3_CheckResonatorSpectroscopy_latest_artifacts.zip \
  -d data/extracted/64Qv3_CheckResonatorSpectroscopy_20260505
```

この ZIP には `CheckResonatorSpectroscopy_{0..63}_{0,1}.json/png` が入っていた。解析対象にしたのは `_0.json`。64 件あるが、MUX ごとに 4 件ずつ同じ `z` データで、ユニークな測定は 16 MUX 分だった。

重複除外済み batch file と batch 用 config を作成した。

```sh
uv run python -c "import glob,json,hashlib,re,pathlib; src='data/extracted/64Qv3_CheckResonatorSpectroscopy_20260505'; cases=[]
for p in sorted(glob.glob(src+'/CheckResonatorSpectroscopy_*_0.json'), key=lambda s:int(re.search(r'_(\\d+)_0\\.json$', s).group(1))):
 d=json.load(open(p)); mux=re.search(r'MUX([0-9]+)$', d['layout']['title']['text']).group(1); digest=hashlib.blake2b(json.dumps(d['data'][0]['z'], separators=(',', ':'), sort_keys=False).encode(), digest_size=16).hexdigest(); cases.append({'qubit':'64','version':'3','date':'20260505','mux':mux,'z_digest':digest,'src_path':str(pathlib.Path(p).resolve())})
pathlib.Path('analysis_outputs').mkdir(exist_ok=True); json.dump(cases, open('analysis_outputs/batch.json','w'), indent=2); conf64=json.load(open('examples/config/config_64q_example.json')); json.dump({'common':{},'64':conf64,'144':conf64}, open('analysis_outputs/config_batch.json','w'), indent=2); print(len(cases))"
```

```sh
uv run python -c "import json; cases=json.load(open('analysis_outputs/batch.json')); unique={}; [unique.setdefault(c['z_digest'], c) for c in cases]; out=list(unique.values()); json.dump(out, open('analysis_outputs/batch_unique.json','w'), indent=2); print(len(out)); print([(c['mux'], c['src_path'].split('/')[-1]) for c in out])"
```

出力は 16 件。

一括解析と画像出力:

```sh
mkdir -p analysis_outputs/batch_runs
uv run tools/batch/batch.py \
  --batch-file analysis_outputs/batch_unique.json \
  --conf-file analysis_outputs/config_batch.json \
  --dst-dir analysis_outputs/batch_runs \
  --pool 4 \
  --write-images
```

主な出力:

```text
analysis_outputs/batch_runs/latest/result.json
analysis_outputs/batch_runs/latest/images/
```

追加で集計 CSV と summary plot を作成した。

```sh
uv run python -c "import csv,json,pathlib,statistics; import matplotlib.pyplot as plt
base=pathlib.Path('analysis_outputs/batch_runs/latest'); data=json.load(open(base/'result.json'))
rows=[]
for item in data.values():
    for r in item['resonators']:
        b=r['bare_shift_boundary']; rows.append({'mux':r['mux'],'qubit':r['qubit'],'frequency_GHz':r['frequency'],'optimal_power_dB':r['optimal_power'],'high_power_max_dB':b['high_power_max'],'high_power_min_dB':b['high_power_min'],'low_power_max_dB':b['low_power_max'],'low_power_min_dB':b['low_power_min']})
rows=sorted(rows,key=lambda r:(r['qubit'] if r['qubit'] is not None else 9999,r['mux']))
with open(base/'resonators.csv','w',newline='') as f:
    w=csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
qs=[r['qubit'] for r in rows]; fs=[r['frequency_GHz'] for r in rows]; ps=[r['optimal_power_dB'] for r in rows]
plt.figure(figsize=(12,4)); plt.scatter(qs,fs,s=22); plt.xlabel('Qubit'); plt.ylabel('Frequency (GHz)'); plt.grid(True,alpha=.3); plt.tight_layout(); plt.savefig(base/'frequency_by_qubit.png',dpi=180); plt.close()
plt.figure(figsize=(12,4)); plt.scatter(qs,ps,s=22); plt.xlabel('Qubit'); plt.ylabel('Optimal power (dB)'); plt.grid(True,alpha=.3); plt.tight_layout(); plt.savefig(base/'optimal_power_by_qubit.png',dpi=180); plt.close()
print('rows',len(rows)); print('frequency_min_max',min(fs),max(fs)); print('optimal_power_counts', {p:ps.count(p) for p in sorted(set(ps))})"
```

marked plot だけを切り出した。

```sh
mkdir -p analysis_outputs/marked_plots
cp analysis_outputs/batch_runs/latest/images/*_MUX00_1_marked.png analysis_outputs/marked_plots/MUX00_marked.png
cp analysis_outputs/batch_runs/latest/images/*_MUX01_1_marked.png analysis_outputs/marked_plots/MUX01_marked.png
cp analysis_outputs/batch_runs/latest/images/*_MUX02_1_marked.png analysis_outputs/marked_plots/MUX02_marked.png
cp analysis_outputs/batch_runs/latest/images/*_MUX03_1_marked.png analysis_outputs/marked_plots/MUX03_marked.png
cp analysis_outputs/batch_runs/latest/images/*_MUX04_1_marked.png analysis_outputs/marked_plots/MUX04_marked.png
cp analysis_outputs/batch_runs/latest/images/*_MUX05_1_marked.png analysis_outputs/marked_plots/MUX05_marked.png
cp analysis_outputs/batch_runs/latest/images/*_MUX06_1_marked.png analysis_outputs/marked_plots/MUX06_marked.png
cp analysis_outputs/batch_runs/latest/images/*_MUX07_1_marked.png analysis_outputs/marked_plots/MUX07_marked.png
cp analysis_outputs/batch_runs/latest/images/*_MUX08_1_marked.png analysis_outputs/marked_plots/MUX08_marked.png
cp analysis_outputs/batch_runs/latest/images/*_MUX09_1_marked.png analysis_outputs/marked_plots/MUX09_marked.png
cp analysis_outputs/batch_runs/latest/images/*_MUX10_1_marked.png analysis_outputs/marked_plots/MUX10_marked.png
cp analysis_outputs/batch_runs/latest/images/*_MUX11_1_marked.png analysis_outputs/marked_plots/MUX11_marked.png
cp analysis_outputs/batch_runs/latest/images/*_MUX12_1_marked.png analysis_outputs/marked_plots/MUX12_marked.png
cp analysis_outputs/batch_runs/latest/images/*_MUX13_1_marked.png analysis_outputs/marked_plots/MUX13_marked.png
cp analysis_outputs/batch_runs/latest/images/*_MUX14_1_marked.png analysis_outputs/marked_plots/MUX14_marked.png
cp analysis_outputs/batch_runs/latest/images/*_MUX15_1_marked.png analysis_outputs/marked_plots/MUX15_marked.png
```

出力:

```text
analysis_outputs/marked_plots/MUX00_marked.png
...
analysis_outputs/marked_plots/MUX15_marked.png
```

## 2026-05-12 最新データ確認

新しくダウンロードされた ZIP:

```text
64Qv3_CheckResonatorSpectroscopy_20260512_artifacts.zip
```

これはリポジトリ直下にあり、`data/` 配下ではなかった。

中身は 16 ファイルだけ。

```text
CheckResonatorSpectroscopy_32_0.png
CheckResonatorSpectroscopy_32_1.png
CheckResonatorSpectroscopy_32_0.json
CheckResonatorSpectroscopy_32_1.json
...
CheckResonatorSpectroscopy_35_0.json
CheckResonatorSpectroscopy_35_1.json
```

つまり `CheckResonatorSpectroscopy_32..35` のみで、全 MUX ではなく MUX08 相当の更新データだった。

展開:

```sh
mkdir -p data/extracted/64Qv3_CheckResonatorSpectroscopy_20260512
unzip -q -n 64Qv3_CheckResonatorSpectroscopy_20260512_artifacts.zip \
  -d data/extracted/64Qv3_CheckResonatorSpectroscopy_20260512
```

前回データとの digest 比較:

```sh
uv run python -c "import json,hashlib,glob,re,pathlib; old='data/extracted/64Qv3_CheckResonatorSpectroscopy_20260505'; new='data/extracted/64Qv3_CheckResonatorSpectroscopy_20260512';
def digest(p):
 d=json.load(open(p)); return d, hashlib.blake2b(json.dumps(d['data'][0]['z'], separators=(',', ':'), sort_keys=False).encode(), digest_size=16).hexdigest()
for p in sorted(glob.glob(new+'/*_0.json'), key=lambda s:int(re.search(r'_(\\d+)_0\\.json$',s).group(1))):
 d,h=digest(p); idx=re.search(r'_(\\d+)_0\\.json$',p).group(1); op=f'{old}/CheckResonatorSpectroscopy_{idx}_0.json'; _,oh=digest(op); print(pathlib.Path(p).name, d['layout']['title']['text'], 'new', h, 'old', oh, 'same' if h==oh else 'CHANGED')"
```

結果:

```text
CheckResonatorSpectroscopy_32_0.json Resonator spectroscopy : MUX08 new 0e2e5a6ba3c4cd5b456b8048329cd7c8 old d3d6705e4ea56d80de15077323001cd7 CHANGED
CheckResonatorSpectroscopy_33_0.json Resonator spectroscopy : MUX08 new 0e2e5a6ba3c4cd5b456b8048329cd7c8 old d3d6705e4ea56d80de15077323001cd7 CHANGED
CheckResonatorSpectroscopy_34_0.json Resonator spectroscopy : MUX08 new 0e2e5a6ba3c4cd5b456b8048329cd7c8 old d3d6705e4ea56d80de15077323001cd7 CHANGED
CheckResonatorSpectroscopy_35_0.json Resonator spectroscopy : MUX08 new 0e2e5a6ba3c4cd5b456b8048329cd7c8 old d3d6705e4ea56d80de15077323001cd7 CHANGED
```

4 件は同一 digest なので、`CheckResonatorSpectroscopy_32_0.json` だけを代表として解析した。

```sh
mkdir -p analysis_outputs/20260512_mux08/images
uv run src/main.py \
  -c examples/config/config_64q_example.json \
  -f data/extracted/64Qv3_CheckResonatorSpectroscopy_20260512/CheckResonatorSpectroscopy_32_0.json \
  --mux 8 \
  --image-dir analysis_outputs/20260512_mux08/images \
  --image-prefix latest_
```

結果 JSON を保存:

```sh
uv run src/main.py \
  -c examples/config/config_64q_example.json \
  -f data/extracted/64Qv3_CheckResonatorSpectroscopy_20260512/CheckResonatorSpectroscopy_32_0.json \
  --mux 8 \
  > analysis_outputs/20260512_mux08/result.json
```

marked plot だけを切り出し:

```sh
mkdir -p analysis_outputs/marked_plots_20260512
cp analysis_outputs/20260512_mux08/images/latest_MUX08_1_marked.png \
  analysis_outputs/marked_plots_20260512/MUX08_marked.png
```

出力:

```text
analysis_outputs/20260512_mux08/result.json
analysis_outputs/20260512_mux08/images/latest_MUX08_0_filtered.png
analysis_outputs/20260512_mux08/images/latest_MUX08_1_marked.png
analysis_outputs/20260512_mux08/images/latest_MUX08_2_0_fft.png
analysis_outputs/20260512_mux08/images/latest_MUX08_2_1_high_frequency_strength.png
analysis_outputs/20260512_mux08/images/latest_MUX08_3_0_corrcoefs.png
analysis_outputs/marked_plots_20260512/MUX08_marked.png
```

## 最新 MUX08 の解析結果

```json
{
  "resonators": [
    {
      "mux": 8,
      "qubit": 32,
      "frequency": 10.452000000000234,
      "bare_shift_boundary": {
        "high_power_max": 0.0,
        "high_power_min": -20.0,
        "low_power_max": -25.0,
        "low_power_min": -55.0
      },
      "optimal_power": -40.0
    },
    {
      "mux": 8,
      "qubit": 33,
      "frequency": 10.576000000000276,
      "bare_shift_boundary": {
        "high_power_max": 0.0,
        "high_power_min": -50.0,
        "low_power_max": -55.0,
        "low_power_min": -55.0
      },
      "optimal_power": -55.0
    },
    {
      "mux": 8,
      "qubit": 34,
      "frequency": 10.506000000000252,
      "bare_shift_boundary": {
        "high_power_max": 0.0,
        "high_power_min": -50.0,
        "low_power_max": -55.0,
        "low_power_min": -55.0
      },
      "optimal_power": -55.0
    },
    {
      "mux": 8,
      "qubit": 35,
      "frequency": 10.118000000000123,
      "bare_shift_boundary": {
        "high_power_max": 0.0,
        "high_power_min": -10.0,
        "low_power_max": -15.0,
        "low_power_min": -55.0
      },
      "optimal_power": -35.0
    }
  ]
}
```

## 前回 MUX08 との差分

```text
old q32: 10.118 GHz, optimal -30 dB
new q32: 10.452 GHz, optimal -40 dB

old q33: 10.452 GHz, optimal -35 dB
new q33: 10.576 GHz, optimal -55 dB

old q34: 10.244 GHz, optimal -30 dB
new q34: 10.506 GHz, optimal -55 dB

old q35: 9.934 GHz, optimal -40 dB
new q35: 10.118 GHz, optimal -35 dB
```
