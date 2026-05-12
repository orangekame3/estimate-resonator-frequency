import argparse
import csv
import hashlib
import json
import pathlib
import re
import shutil
import subprocess
import sys
import zipfile
from dataclasses import asdict, dataclass
from typing import Any


REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
MAIN_SCRIPT = REPO_ROOT / "src" / "main.py"
DEFAULT_CONFIG = REPO_ROOT / "examples" / "config" / "config_64q_example.json"


@dataclass(frozen=True)
class SpectroscopyCase:
    qubit: str
    version: str
    date: str
    mux: str
    z_digest: str
    src_path: str


@dataclass(frozen=True)
class MainArgs:
    zip_file: pathlib.Path
    out_dir: pathlib.Path
    extract_dir: pathlib.Path
    config_file: pathlib.Path
    qubit: str
    version: str
    date: str
    write_images: bool
    marked_dir: pathlib.Path | None


def parse_args() -> MainArgs:
    parser = argparse.ArgumentParser(
        description="Analyze CheckResonatorSpectroscopy artifact ZIP files."
    )
    parser.add_argument("zip_file", type=pathlib.Path)
    parser.add_argument(
        "--out-dir",
        type=pathlib.Path,
        help="Output directory. Default: analysis_outputs/<zip stem>",
    )
    parser.add_argument(
        "--extract-dir",
        type=pathlib.Path,
        help="Extraction directory. Default: data/extracted/<zip stem>",
    )
    parser.add_argument("--config-file", type=pathlib.Path, default=DEFAULT_CONFIG)
    parser.add_argument("--qubit", default="64")
    parser.add_argument("--version", default="3")
    parser.add_argument("--date", help="YYYYMMDD. Default: inferred from ZIP name.")
    parser.add_argument("--no-images", action="store_true")
    parser.add_argument(
        "--marked-dir",
        type=pathlib.Path,
        help="Directory to copy only *_1_marked.png files into.",
    )
    namespace = parser.parse_args()

    zip_file = namespace.zip_file.resolve()
    out_dir = namespace.out_dir or REPO_ROOT / "analysis_outputs" / zip_file.stem
    extract_dir = (
        namespace.extract_dir or REPO_ROOT / "data" / "extracted" / zip_file.stem
    )

    return MainArgs(
        zip_file=zip_file,
        out_dir=out_dir.resolve(),
        extract_dir=extract_dir.resolve(),
        config_file=namespace.config_file.resolve(),
        qubit=namespace.qubit,
        version=namespace.version,
        date=namespace.date or infer_date(zip_file.name),
        write_images=not namespace.no_images,
        marked_dir=namespace.marked_dir.resolve() if namespace.marked_dir else None,
    )


def infer_date(name: str) -> str:
    if match := re.search(r"(20[0-9]{6})", name):
        return match[1]
    return "unknown"


def extract_zip(zip_file: pathlib.Path, extract_dir: pathlib.Path) -> None:
    extract_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_file) as zf:
        zf.extractall(extract_dir)


def load_json(path: pathlib.Path) -> dict[str, Any]:
    with path.open() as f:
        return json.load(f)


def compute_z_digest(data: dict[str, Any]) -> str:
    return hashlib.blake2b(
        json.dumps(
            data["data"][0]["z"], separators=(",", ":"), sort_keys=False
        ).encode("utf-8"),
        digest_size=16,
    ).hexdigest()


def extract_mux(data: dict[str, Any]) -> str:
    title = data["layout"]["title"]["text"]
    if match := re.match(r".*MUX([0-9]+)$", title):
        return match[1]
    raise ValueError(f"could not extract mux from title: {title}")


def spectroscopy_index(path: pathlib.Path) -> int:
    if match := re.search(r"_(\d+)_0\.json$", path.name):
        return int(match[1])
    raise ValueError(f"unexpected spectroscopy filename: {path}")


def build_cases(args: MainArgs) -> list[SpectroscopyCase]:
    paths = sorted(
        args.extract_dir.glob("**/CheckResonatorSpectroscopy_*_0.json"),
        key=spectroscopy_index,
    )
    cases = []
    for path in paths:
        data = load_json(path)
        cases.append(
            SpectroscopyCase(
                qubit=args.qubit,
                version=args.version,
                date=args.date,
                mux=extract_mux(data),
                z_digest=compute_z_digest(data),
                src_path=str(path.resolve()),
            )
        )
    return cases


def unique_cases(cases: list[SpectroscopyCase]) -> list[SpectroscopyCase]:
    unique: dict[str, SpectroscopyCase] = {}
    for case in cases:
        unique.setdefault(case.z_digest, case)
    return list(unique.values())


def write_json(path: pathlib.Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        json.dump(value, f, indent=2, sort_keys=True)


def write_context(args: MainArgs, cases: list[SpectroscopyCase]) -> None:
    args.out_dir.mkdir(parents=True, exist_ok=True)
    write_json(args.out_dir / "batch.json", [asdict(case) for case in cases])

    conf64 = load_json(args.config_file)
    write_json(
        args.out_dir / "config_batch.json",
        {"common": {}, args.qubit: conf64},
    )
    write_json(args.out_dir / f"config_{args.qubit}q.json", conf64)


def run_case(args: MainArgs, case: SpectroscopyCase) -> dict[str, Any]:
    command = [
        sys.executable,
        str(MAIN_SCRIPT),
        "--conf-file",
        str(args.config_file),
        "--input-file",
        case.src_path,
        "--mux",
        str(int(case.mux)),
    ]

    if args.write_images:
        command.extend(
            [
                "--image-dir",
                str(args.out_dir / "images"),
                "--image-prefix",
                f"{case.z_digest}_",
            ]
        )

    result = subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    return json.loads(result.stdout)


def run_cases(args: MainArgs, cases: list[SpectroscopyCase]) -> dict[str, Any]:
    if args.write_images:
        (args.out_dir / "images").mkdir(parents=True, exist_ok=True)

    # Keep execution sequential: image generation is the slow part and Plotly/Kaleido
    # failures are easier to read one case at a time.
    results = {}
    for case in cases:
        print(f"processing MUX{case.mux}: {case.z_digest}")
        results[case.z_digest] = run_case(args, case)
    return results


def flatten_resonators(results: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for result in results.values():
        for resonator in result.get("resonators", []):
            boundary = resonator["bare_shift_boundary"]
            rows.append(
                {
                    "mux": resonator["mux"],
                    "qubit": resonator["qubit"],
                    "frequency_GHz": resonator["frequency"],
                    "optimal_power_dB": resonator["optimal_power"],
                    "high_power_max_dB": boundary["high_power_max"],
                    "high_power_min_dB": boundary["high_power_min"],
                    "low_power_max_dB": boundary["low_power_max"],
                    "low_power_min_dB": boundary["low_power_min"],
                }
            )
    return sorted(rows, key=lambda row: (row["qubit"] is None, row["qubit"], row["mux"]))


def write_csv(path: pathlib.Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def write_summary_plots(out_dir: pathlib.Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return

    import matplotlib.pyplot as plt

    qubits = [row["qubit"] for row in rows]
    frequencies = [row["frequency_GHz"] for row in rows]
    powers = [row["optimal_power_dB"] for row in rows]

    plt.figure(figsize=(12, 4))
    plt.scatter(qubits, frequencies, s=22)
    plt.xlabel("Qubit")
    plt.ylabel("Frequency (GHz)")
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(out_dir / "frequency_by_qubit.png", dpi=180)
    plt.close()

    plt.figure(figsize=(12, 4))
    plt.scatter(qubits, powers, s=22)
    plt.xlabel("Qubit")
    plt.ylabel("Optimal power (dB)")
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig(out_dir / "optimal_power_by_qubit.png", dpi=180)
    plt.close()


def copy_marked_plots(args: MainArgs) -> list[pathlib.Path]:
    if args.marked_dir is None or not args.write_images:
        return []

    args.marked_dir.mkdir(parents=True, exist_ok=True)
    copied = []
    for path in sorted((args.out_dir / "images").glob("*_MUX*_1_marked.png")):
        if match := re.search(r"_(MUX[0-9]+)_1_marked\.png$", path.name):
            dst = args.marked_dir / f"{match[1]}_marked.png"
            shutil.copy2(path, dst)
            copied.append(dst)
    return copied


def main() -> None:
    args = parse_args()
    extract_zip(args.zip_file, args.extract_dir)

    all_cases = build_cases(args)
    cases = unique_cases(all_cases)
    write_context(args, cases)

    results = run_cases(args, cases)
    write_json(args.out_dir / "result.json", results)

    rows = flatten_resonators(results)
    write_csv(args.out_dir / "resonators.csv", rows)
    write_summary_plots(args.out_dir, rows)
    copied_marked = copy_marked_plots(args)

    print(f"input cases: {len(all_cases)}")
    print(f"unique cases: {len(cases)}")
    print(f"resonators: {len(rows)}")
    print(f"output: {args.out_dir}")
    if copied_marked:
        print(f"marked plots: {args.marked_dir}")


if __name__ == "__main__":
    main()
