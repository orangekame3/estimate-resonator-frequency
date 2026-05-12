import functools
import itertools
from operator import attrgetter, itemgetter
from typing import (
    NamedTuple,
    Sequence,
)
from scipy.signal import find_peaks as _find_peaks
from scipy.ndimage import convolve1d
import numpy as np
from util import arg_closest


class Peak(NamedTuple):
    x: int
    y: int
    prominence: float


class PeakGroup:
    def __init__(self, peaks: Sequence[Peak]):
        self.peaks = peaks

    @functools.cached_property
    def bottom(self):
        return sorted(self.peaks, key=attrgetter("y"))[0]

    @property
    def x(self):
        return self.bottom.x

    @property
    def y(self):
        return self.bottom.y


class Resonance:
    def __init__(
        self,
        high_power_peaks: PeakGroup | None,
        low_power_peak: Peak | None,
        complementary_peaks: list[Peak] | None = None,
    ):
        if complementary_peaks is None:
            complementary_peaks = []

        self.high_power_peaks = high_power_peaks
        self.low_power_peak = low_power_peak
        self.complementary_peaks = complementary_peaks

    @property
    def x(self):
        if self.low_power_peak:
            return self.low_power_peak.x

        if self.high_power_peaks:
            return self.high_power_peaks.x

        return -1

    @functools.cached_property
    def score(self):
        return (
            self.has_high_power_peaks,
            self.high_power_x_span,
            self.has_low_power_peak,
            self.high_power_grad,
            self.max_prominence,
        )

    @functools.cached_property
    def has_high_power_peaks(self):
        return bool(self.high_power_peaks)

    @functools.cached_property
    def has_low_power_peak(self):
        return bool(self.low_power_peak)

    @functools.cached_property
    def high_power_grad(self):
        if len(self.peaks) <= 1:
            return float("-inf")

        return max(
            Resonance.compute_grad(p0, p1)
            for p0, p1 in itertools.combinations(self.peaks, 2)
        )

    @functools.cached_property
    def high_power_x_span(self):
        if not self.high_power_peaks:
            return float("-inf")

        xs = [peak.x for peak in self.high_power_peaks.peaks]
        return max(xs) - min(xs)

    @functools.cached_property
    def peaks(self):
        peaks: Sequence[Peak] = []

        if self.high_power_peaks:
            peaks.extend(self.high_power_peaks.peaks)

        peaks.extend(self.complementary_peaks)

        if self.low_power_peak:
            peaks.append(self.low_power_peak)

        return peaks

    @property
    def max_prominence(self):
        if not self.peaks:
            return 0.0

        return max(peak.prominence for peak in self.peaks)

    @staticmethod
    def compute_grad(p0: Peak, p1: Peak):
        if p0.x == p1.x:
            return float("-inf")

        grad = float((p1.y - p0.y) / (p1.x - p0.x))

        if grad > 0:
            return float("-inf")

        return grad


def find_peaks(
    trace: Sequence[float],
    *,
    num_resonators: int,
    smooth_sigma: float,
    fp_conditions: dict,
) -> tuple[Sequence[int], Sequence[float]]:
    _trace = np.asarray(trace)

    if smooth_sigma and smooth_sigma > 0:
        radius = int(3 * smooth_sigma)
        x = np.arange(-radius, radius + 1)
        kernel = np.exp(-0.5 * (x / smooth_sigma) ** 2)
        kernel /= kernel.sum()
        trace_smooth = convolve1d(_trace, kernel, mode="nearest")
    else:
        trace_smooth = _trace

    peaks, props = _find_peaks(trace_smooth, **fp_conditions)

    if peaks.size == 0:
        return [], []

    # fmt: off
    sorted_peaks = sorted(zip(props["prominences"], peaks), reverse=True)  # pyright: ignore[reportTypedDictNotRequiredAccess]
    # fmt: on
    top_peaks = sorted(sorted_peaks[:num_resonators], key=itemgetter(1))
    prominences, peaks = zip(*top_peaks)

    return peaks, prominences


def group_peaks(
    peaks: Sequence[Peak], x_backward_max: int, x_distance_max: int
) -> Sequence[PeakGroup]:
    if not peaks:
        return []

    peaks = sorted(peaks, key=lambda p: (p.x, -p.y))

    groups: Sequence[PeakGroup] = []
    group: Sequence[Peak] = [peaks[0]]
    x_bottom = peaks[0].x
    y_bottom = peaks[0].y

    for peak in peaks[1:]:
        cond1 = peak.y >= y_bottom and peak.x > x_bottom + x_backward_max
        cond2 = (
            peak.y < y_bottom
            and (peak.x - x_bottom) > (y_bottom - peak.y) * x_distance_max
        )
        if cond1 or cond2:
            group = sorted(group, key=attrgetter("y"))
            groups.append(PeakGroup(group))
            group = [peak]
            x_bottom = peak.x
            y_bottom = peak.y
        else:
            group.append(peak)
            if peak.y < y_bottom:
                x_bottom = peak.x
                y_bottom = peak.y

    if group:
        groups.append(PeakGroup(group))

    return groups


def compose_resonances(
    peak_groups: Sequence[PeakGroup],
    low_power_peaks: Sequence[Peak],
    x_distance_max: int,
    x_backward_max: int,
):
    arr_high = [(peak_group, 0) for peak_group in peak_groups]
    arr_low = [(peak, 1) for peak in low_power_peaks]

    arr = sorted(arr_high + arr_low, key=lambda item: (item[0].x, item[1]))
    arr = [item[0] for item in arr] + [None]

    resonances: Sequence[Resonance] = []
    skip = False

    for p0, p1 in zip(arr[:-1], arr[1:]):
        if skip:
            skip = False
            continue

        match p0, p1:
            case Peak(), PeakGroup():
                if p1.x - p0.x <= x_backward_max:
                    resonances.append(Resonance(p1, p0))
                    skip = True
                else:
                    resonances.append(Resonance(None, p0))
            case PeakGroup(), Peak():
                if p1.x - p0.x < (p0.y - p1.y) * x_distance_max:
                    resonances.append(Resonance(p0, p1))
                    skip = True
                else:
                    resonances.append(Resonance(p0, None))
            case Peak(), Peak() | None:
                resonances.append(Resonance(None, p0))
            case PeakGroup(), PeakGroup() | None:
                resonances.append(Resonance(p0, None))

    return resonances


def group_resonances(resonances: Sequence[Resonance], x_distance_max: int):
    groups: Sequence[Sequence[Resonance]] = []

    if not resonances:
        return groups

    resonances = sorted(resonances, key=attrgetter("x"))
    group = [resonances[0]]

    for resonance in resonances[1:]:
        if resonance.x - group[-1].x > x_distance_max:
            groups.append(group)
            group = [resonance]
        else:
            group.append(resonance)

    if group:
        groups.append(group)

    return groups


def detect_high_power_peak_groups(
    ys: Sequence[float],
    zs: Sequence[Sequence[float]],
    high_power_min: float | None,
    high_power_max: float | None,
    num_resonators: int,
    find_peaks_conf_high: dict,
    group_peaks_conf: dict,
) -> Sequence[PeakGroup]:
    if high_power_min is None or high_power_max is None:
        return []

    y_idx_high_min = arg_closest(ys, high_power_min)
    y_idx_high_max = arg_closest(ys, high_power_max)

    if y_idx_high_min > y_idx_high_max:
        y_idx_high_min, y_idx_high_max = y_idx_high_max, y_idx_high_min

    high_power_peaks = []

    for y_idx in range(y_idx_high_min, y_idx_high_max + 1):
        _xs, prominences = find_peaks(
            trace=zs[y_idx], num_resonators=num_resonators * 2, **find_peaks_conf_high
        )
        high_power_peaks.extend(
            Peak(peak_idx, y_idx, prominence)
            for peak_idx, prominence in zip(_xs, prominences)
        )

    return group_peaks(high_power_peaks, **group_peaks_conf)


def detect_complementary_peaks(
    ys: Sequence[float],
    zs: Sequence[Sequence[float]],
    high_power_min: float | None,
    high_power_max: float | None,
    num_resonators: int,
    find_peaks_conf: dict,
    resonances: Sequence[Resonance],
) -> dict[int, Sequence[Peak]]:
    if high_power_min is None or high_power_max is None:
        return {}

    y_idx_high_min = arg_closest(ys, high_power_min)
    y_idx_high_max = arg_closest(ys, high_power_max)

    if y_idx_high_min > y_idx_high_max:
        y_idx_high_min, y_idx_high_max = y_idx_high_max, y_idx_high_min

    known_peaks = list(itertools.chain.from_iterable(res.peaks for res in resonances))

    def is_known_peak(x_idx: int, y_idx: int):
        return any(
            x_idx == known_peak.x and y_idx == known_peak.y
            for known_peak in known_peaks
        )

    peaks: dict[int, Sequence[Peak]] = {}

    for y_idx in range(y_idx_high_min, y_idx_high_max + 1):
        _xs, prominences = find_peaks(
            trace=zs[y_idx], num_resonators=num_resonators * 2, **find_peaks_conf
        )
        peaks[y_idx] = [
            Peak(peak_idx, y_idx, prominence)
            for peak_idx, prominence in zip(_xs, prominences)
            if not is_known_peak(peak_idx, y_idx)
        ]

    return peaks


def complement_peaks(
    len_ys: int, complementary_peaks: dict[int, Sequence[Peak]], resonance: Resonance
):
    if resonance.high_power_peaks and resonance.low_power_peak:
        peak0 = resonance.high_power_peaks.bottom
        peak1 = resonance.low_power_peak
    elif resonance.high_power_peaks:
        peak0 = resonance.high_power_peaks.bottom
        peak1 = resonance.high_power_peaks.bottom
    elif resonance.low_power_peak:
        peak0 = Peak(x=resonance.low_power_peak.x, y=len_ys, prominence=0)
        peak1 = resonance.low_power_peak
    else:
        raise Exception

    x_min = min(peak0.x, peak1.x)
    x_max = max(peak0.x, peak1.x)
    y_min = min(peak0.y, peak1.y) + 1
    y_max = max(peak0.y, peak1.y) - 1

    if y_min > y_max:
        return resonance

    target_peaks: list[Peak] = []
    for y_idx in range(y_min, y_max + 1):
        if y_idx not in complementary_peaks:
            continue

        candidates = [
            peak for peak in complementary_peaks[y_idx] if x_min <= peak.x <= x_max
        ]

        if not candidates:
            continue

        target_peaks.append(sorted(candidates, key=lambda peak: peak.x)[0])

    return Resonance(
        high_power_peaks=resonance.high_power_peaks,
        low_power_peak=resonance.low_power_peak,
        complementary_peaks=target_peaks,
    )


def estimate_resonator_frequency(
    ys: Sequence[float],
    zs: Sequence[Sequence[float]],
    *,
    high_power_min: float | None,
    high_power_max: float | None,
    low_power: float,
    num_resonators: int,
    find_peaks_conf_high: dict,
    find_peaks_conf_low: dict,
    group_peaks_conf: dict,
    compose_resonances_conf: dict,
    group_resonances_conf: dict,
):

    ## 1. Detect peaks in the high-power region
    high_power_peak_groups = detect_high_power_peak_groups(
        ys,
        zs,
        high_power_min,
        high_power_max,
        num_resonators,
        find_peaks_conf_high,
        group_peaks_conf,
    )

    ## 2. Detect peaks in the low-power region
    y_idx_low = arg_closest(ys, low_power)

    _xs, prominences = find_peaks(
        trace=zs[y_idx_low], num_resonators=num_resonators * 2, **find_peaks_conf_low
    )
    low_power_peaks = [
        Peak(peak_idx, y_idx_low, prominence)
        for peak_idx, prominence in zip(_xs, prominences)
    ]

    ## 3. Integrate the results from 1 and 2, and estimate genuine resonance through scoring.
    resonances: list[Resonance] = []
    rests: list[Resonance] = []

    for res_group in group_resonances(
        compose_resonances(
            high_power_peak_groups, low_power_peaks, **compose_resonances_conf
        ),
        **group_resonances_conf,
    ):
        res_group = sorted(res_group, key=attrgetter("score"), reverse=True)
        resonances.append(res_group[0])
        rests.extend(res_group[1:])

    resonances = sorted(resonances, key=attrgetter("score"), reverse=True)
    rests.extend(resonances[num_resonators:])
    resonances = resonances[:num_resonators]

    resonances = sorted(resonances, key=attrgetter("x"))
    rests = sorted(rests, key=attrgetter("x"))

    complementary_peaks = detect_complementary_peaks(
        ys,
        zs,
        high_power_min,
        high_power_max,
        num_resonators,
        find_peaks_conf_low,
        resonances + rests,
    )

    def _complement_peaks(resonance: Resonance):
        return complement_peaks(len(ys), complementary_peaks, resonance)

    resonances = list(map(_complement_peaks, resonances))
    rests = list(map(_complement_peaks, rests))

    return resonances, rests
