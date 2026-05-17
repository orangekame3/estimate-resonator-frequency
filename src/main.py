import argparse
import json
import os
from dataclasses import dataclass
from typing import Any
from bare_shift import (
    BareShiftBoundary,
    BareShiftDebugOptions,
)
from config import create_bare_shift_boundary_estimator
from estimate_resonator_frequency import Resonance, estimate_resonator_frequency
from local_bare_shift import estimate_local_bare_shift_boundary
from minimum_usable_power import CorrelationBasedMinimumUsablePowerEstimator
from plot import output_images
from util import arg_closest
from remove_false_spike import remove_false_spike


QUBIT_ID_ORDER = [1, 3, 2, 0]
QID_OFFSET_BY_SORTED_SLOT = [3, 0, 2, 1]


@dataclass(frozen=True)
class MainArgs:
    conf_file: str
    input_file: str
    mux: int
    image_dir: str | None
    image_prefix: str | None
    plot: bool
    debug: bool


@dataclass(frozen=True)
class OutputPaths:
    bare_shift_artifact_prefix: str | None
    minimum_usable_power_artifact_prefix: str | None
    spectroscopy_image_prefix: str | None


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument('-c', '--conf-file', required=True)
    parser.add_argument('-f', '--input-file', required=True)
    parser.add_argument('--mux', type=int, required=True)
    parser.add_argument('--image-dir')
    parser.add_argument('--image-prefix')
    parser.add_argument('--plot', action='store_true')
    parser.add_argument('--debug', action='store_true')
    namespace = parser.parse_args()
    return MainArgs(
        conf_file=namespace.conf_file,
        input_file=namespace.input_file,
        mux=namespace.mux,
        image_dir=namespace.image_dir,
        image_prefix=namespace.image_prefix,
        plot=namespace.plot,
        debug=namespace.debug,
    )


def load_inputs(args: MainArgs) -> tuple[dict[str, Any], dict[str, Any]]:
    with open(args.input_file) as f:
        data = json.load(f)

    with open(args.conf_file) as f:
        conf = json.load(f)

    return data, conf


def build_output_paths(
    data: dict[str, Any], image_dir: str | None, image_prefix: str | None
) -> OutputPaths:
    if image_dir is None:
        return OutputPaths(
            bare_shift_artifact_prefix=None,
            minimum_usable_power_artifact_prefix=None,
            spectroscopy_image_prefix=None,
        )

    mux = data['layout']['title']['text'][-5:]

    if image_prefix is None:
        image_prefix = ''

    return OutputPaths(
        bare_shift_artifact_prefix=os.path.join(image_dir, f'{image_prefix}{mux}_2_'),
        minimum_usable_power_artifact_prefix=os.path.join(
            image_dir, f'{image_prefix}{mux}_3_'
        ),
        spectroscopy_image_prefix=os.path.join(image_dir, f'{image_prefix}{mux}_'),
    )


def denoise_data(
    data: dict[str, Any],
    conf: dict[str, Any],
) -> dict[str, Any]:
    for item in conf['remove_false_spike']:
        data = remove_false_spike(data, *item)
    return data


def estimate_bare_shift_boundary(
    data: dict[str, Any],
    conf: dict[str, Any],
    *,
    bare_shift_artifact_prefix: str | None = None,
) -> BareShiftBoundary:
    estimator = create_bare_shift_boundary_estimator(conf)
    debug = BareShiftDebugOptions(
        artifact_prefix=bare_shift_artifact_prefix,
    )

    boundary = estimator.estimate_bare_shift_boundary(
        data['data'][0]['x'],
        data['data'][0]['y'],
        data['data'][0]['z'],
        debug=debug,
    )

    return boundary


def estimate_resonances(
    data: dict[str, Any],
    conf: dict[str, Any],
    boundary: BareShiftBoundary,
):
    return estimate_resonator_frequency(
        data['data'][0]['y'],
        data['data'][0]['z'],
        high_power_min=boundary.high_power_min,
        high_power_max=boundary.high_power_max,
        low_power=boundary.low_power,
        **conf['estimate_resonator_frequency'],
    )


def estimate_local_bare_shift_boundaries(
    data: dict[str, Any],
    resonances: list[Resonance],
):
    local_boundaries = [
        estimate_local_bare_shift_boundary(data['data'][0]['y'], resonance)
        for resonance in resonances
    ]
    return local_boundaries


def estimate_minimum_usable_power(
    data: dict[str, Any],
    conf: dict[str, Any],
    boundary: BareShiftBoundary,
    *,
    minimum_usable_power_artifact_prefix: str | None = None,
) -> float:
    y_idx_base = arg_closest(data['data'][0]['y'], boundary.low_power)
    estimator = CorrelationBasedMinimumUsablePowerEstimator(
        coef_min=conf['minimum_usable_power']['correlation_coefficient_min'],
    )
    y_idx_min = estimator.estimate_idx(
        zs=data['data'][0]['z'],
        idx_base=y_idx_base,
        artifact_prefix=minimum_usable_power_artifact_prefix,
    )

    return data['data'][0]['y'][y_idx_min]


def estimate_optimal_powers(
    data: dict[str, Any],
    local_boundaries: list[BareShiftBoundary],
    minimum_usable_power: float,
):
    y_idx_0 = arg_closest(data['data'][0]['y'], minimum_usable_power)

    def compute_mid(y: float) -> float:
        y_idx_1 = arg_closest(data['data'][0]['y'], y)
        y_idx_mid = (y_idx_0 + y_idx_1 + 1) // 2
        return data['data'][0]['y'][y_idx_mid]

    return [compute_mid(boundary.low_power) for boundary in local_boundaries]


def build_bare_shift_boundary_result(
    boundary: BareShiftBoundary,
    minimum_usable_power: float,
):
    return {
        'high_power_max': boundary.high_power_max,
        'high_power_min': boundary.high_power_min,
        'low_power_max': boundary.low_power,
        'low_power_min': minimum_usable_power,
    }


def reorder_by_qubit_id(arr):
    return [arr[i] for i in QUBIT_ID_ORDER]


def guess_sorted_slots_for_partial_mux(
    data: dict[str, Any],
    resonances: list[Resonance],
) -> tuple[list[int | None], str]:
    """Guess sorted-slot assignment for partial resonator detection.

    For 3 detected peaks:
    - If one adjacent gap is much larger than the other, assume an interior slot is missing.
    - Otherwise, decide between left-edge and right-edge missing based on where the 3-peak
      cluster sits within the full scan range.

    Returns per-resonance sorted-slot indices (0..3) in x-sorted order.
    """
    count = len(resonances)
    if count >= 4:
        return list(range(count)), "full"
    if count != 3:
        return [None] * count, "unassigned"

    xs = data["data"][0]["x"]
    freqs = [xs[resonance.x] for resonance in resonances]
    left_gap = float(freqs[1] - freqs[0])
    right_gap = float(freqs[2] - freqs[1])
    min_gap = max(min(left_gap, right_gap), 1e-12)
    gap_ratio = max(left_gap, right_gap) / min_gap

    if gap_ratio >= 1.6:
        if left_gap > right_gap:
            return [0, 2, 3], "slot1-missing-large-left-gap"
        return [0, 1, 3], "slot2-missing-large-right-gap"

    scan_min = float(min(xs))
    scan_max = float(max(xs))
    scan_center = (scan_min + scan_max) / 2.0
    cluster_center = sum(freqs) / len(freqs)
    if cluster_center < scan_center:
        return [0, 1, 2], "right-edge-missing-cluster-left"
    return [1, 2, 3], "left-edge-missing-cluster-right"


def qid_for_sorted_slot(mux: int, sorted_slot: int) -> int:
    return mux * 4 + QID_OFFSET_BY_SORTED_SLOT[sorted_slot]


def build_resonance_assignments(
    args: MainArgs,
    data: dict[str, Any],
    resonances: list[Resonance],
) -> tuple[list[dict[str, Any]], str]:
    if len(resonances) < 4:
        sorted_slots, assignment_mode = guess_sorted_slots_for_partial_mux(
            data,
            resonances,
        )
    else:
        sorted_slots = list(range(len(resonances)))
        assignment_mode = "full"

    assignments = [
        {
            "sorted_slot": sorted_slot,
            "qubit": (
                qid_for_sorted_slot(args.mux, sorted_slot)
                if sorted_slot is not None
                else None
            ),
            "assignment_mode": assignment_mode,
        }
        for sorted_slot in sorted_slots
    ]
    return assignments, assignment_mode


def build_result(
    args: MainArgs,
    data: dict[str, Any],
    resonances: list[Resonance],
    local_boundaries: list[BareShiftBoundary],
    minimum_usable_power: float,
    optimal_powers: list[float],
) -> dict[str, Any]:

    result = {}
    assignments, assignment_mode = build_resonance_assignments(args, data, resonances)

    if len(resonances) < 4:
        result['resonators'] = [
            dict(
                mux=args.mux,
                qubit=assignment["qubit"],
                assigned_slot=assignment["sorted_slot"],
                assignment_mode=assignment["assignment_mode"],
                frequency=data['data'][0]['x'][resonance.x],
                bare_shift_boundary=build_bare_shift_boundary_result(
                    local_boundary, minimum_usable_power
                ),
                optimal_power=optimal_power,
            )
            for resonance, local_boundary, optimal_power, assignment in zip(
                resonances, local_boundaries, optimal_powers, assignments
            )
        ]
    else:
        resonances = reorder_by_qubit_id(resonances)
        local_boundaries = reorder_by_qubit_id(local_boundaries)
        optimal_powers = reorder_by_qubit_id(optimal_powers)
        result['resonators'] = [
            dict(
                mux=args.mux,
                qubit=args.mux * 4 + i,
                assigned_slot=QUBIT_ID_ORDER[i],
                assignment_mode=assignment_mode,
                frequency=data['data'][0]['x'][resonance.x],
                bare_shift_boundary=build_bare_shift_boundary_result(
                    local_boundary, minimum_usable_power
                ),
                optimal_power=optimal_power,
            )
            for i, (resonance, local_boundary, optimal_power) in enumerate(
                zip(resonances, local_boundaries, optimal_powers)
            )
        ]

    return result


def build_debug_output() -> dict[str, Any]:
    return {}


def print_result(
    result: dict[str, Any],
    debug: bool,
    debug_output: dict[str, Any] | None = None,
):
    if debug:
        if debug_output is None:
            debug_output = {}
        result = result | {'debug': debug_output}

    print(json.dumps(result))


def maybe_output_spectroscopy_images(
    data: dict[str, Any],
    resonances: list[Resonance],
    rests: list[Resonance],
    local_boundaries,
    minimum_usable_power: float,
    resonance_assignments: list[dict[str, Any]],
    image_prefix: str | None,
    plot: bool,
    debug: bool,
) -> None:
    if image_prefix or plot:
        output_images(
            data,
            resonances,
            rests,
            local_boundaries,
            minimum_usable_power,
            resonance_assignments,
            image_prefix,
            plot,
            debug,
        )


def main():
    args = parse_args()
    data, conf = load_inputs(args)
    output_paths = build_output_paths(data, args.image_dir, args.image_prefix)
    data = denoise_data(data, conf)
    boundary = estimate_bare_shift_boundary(
        data, conf, bare_shift_artifact_prefix=output_paths.bare_shift_artifact_prefix
    )
    resonances, rests = estimate_resonances(data, conf, boundary)
    local_boundaries = estimate_local_bare_shift_boundaries(data, resonances + rests)
    minimum_usable_power = estimate_minimum_usable_power(
        data,
        conf,
        boundary,
        minimum_usable_power_artifact_prefix=output_paths.minimum_usable_power_artifact_prefix,
    )
    optimal_powers = estimate_optimal_powers(
        data, local_boundaries, minimum_usable_power
    )

    result = build_result(
        args, data, resonances, local_boundaries, minimum_usable_power, optimal_powers
    )
    resonance_assignments, _ = build_resonance_assignments(args, data, resonances)
    debug_output = build_debug_output()
    print_result(result, args.debug, debug_output)
    maybe_output_spectroscopy_images(
        data,
        resonances,
        rests,
        local_boundaries,
        minimum_usable_power,
        resonance_assignments,
        output_paths.spectroscopy_image_prefix,
        args.plot,
        args.debug,
    )


if __name__ == '__main__':
    main()
