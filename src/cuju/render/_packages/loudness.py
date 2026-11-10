# Copyright 2026 The cuju Authors
# SPDX-License-Identifier: Apache-2.0

"""The loudness of a sound after ITU-R BS.1770, as the page measures it."""

from __future__ import annotations

import itertools
import math
import operator
import struct
import sys
from array import array
from typing import Any

from cuju.errors import ArgumentError

# The loudness ceilings of a team after the safety numbers, in LUFS and dBTP.
TARGET_LUFS = -23.0
SHORT_TERM_CEILING = -18.0
MOMENTARY_CEILING = -14.0
TRUE_PEAK_CEILING = -1.0
MAXIMUM_SECONDS = 60
# The PCM and float samples of WAV the page decodes, by format code and bytes per sample.
_SAMPLE_FORMATS = ((1, 1), (1, 2), (1, 3), (1, 4), (3, 4), (3, 8))


# Loudness after ITU-R BS.1770.


def _k_weighting(rate: float) -> tuple[float, ...]:
    """Returns the K weighting of BS.1770 at a sample rate, as the page derives it.

    The high shelf comes first as b0, b1, b2, a1 and a2, the high pass second as a1 and a2, its
    numerator being 1, -2 and 1.
    """
    f0, gain, q = 1681.974450955533, 3.999843853973347, 0.7071752369554196
    k = math.tan(math.pi * f0 / rate)
    vh = 10 ** (gain / 20)
    vb = vh**0.4996667741545416
    a0 = 1 + k / q + k * k
    shelf = (
        (vh + vb * k / q + k * k) / a0,
        2 * (k * k - vh) / a0,
        (vh - vb * k / q + k * k) / a0,
        2 * (k * k - 1) / a0,
        (1 - k / q + k * k) / a0,
    )
    f0, q = 38.13547087602444, 0.5003270373238773
    k = math.tan(math.pi * f0 / rate)
    a0 = 1 + k / q + k * k
    return (*shelf, 2 * (k * k - 1) / a0, (1 - k / q + k * k) / a0)


def _weights(channels: int) -> list[float]:
    """Returns the channel weights of BS.1770 in the order of WAV and the Web Audio API."""
    if channels == 5:
        return [1, 1, 1, 1.41, 1.41]
    if channels == 6:
        return [1, 1, 1, 0, 1.41, 1.41]
    return [1.0] * channels


def _interpolation(factor: int, taps: int = 16) -> list[list[float]]:
    """Returns the interpolation filter of the true peak, a row of taps for each phase."""

    def bessel(x: float) -> float:
        total = term = 1.0
        for k in range(1, 64):
            term *= (x / (2 * k)) ** 2
            total += term
            if term < 1e-17 * total:
                break
        return total

    half, beta = taps // 2, 5.0
    norm = bessel(beta)
    rows = []
    for phase in range(1, factor):
        row = []
        for k in range(taps):
            t = k - half + 1 - phase / factor
            sinc = 1.0 if t == 0 else math.sin(math.pi * t) / (math.pi * t)
            u = t / half
            row.append(sinc * (0.0 if abs(u) >= 1 else bessel(beta * math.sqrt(1 - u * u)) / norm))
        total = sum(row)
        rows.append([value / total for value in row])
    return rows


def _lufs(mean_square: float) -> float:
    return -0.691 + 10 * math.log10(mean_square) if mean_square > 1e-20 else -math.inf


def _round(value: float) -> int:
    """Rounds half up, as JavaScript's `Math.round` does."""
    return math.floor(value + 0.5)


def _wav(data: bytes) -> tuple[int, int, int, int, int, bytes]:
    """Returns the format, sample rate, channels, bits, frames and samples of a WAV file."""
    if len(data) < 12 or data[:4] != b'RIFF' or data[8:12] != b'WAVE':
        raise ArgumentError('expected a WAV file')
    offset, fmt, samples = 12, None, None
    while offset + 8 <= len(data):
        kind = data[offset : offset + 4]
        (size,) = struct.unpack_from('<I', data, offset + 4)
        body = data[offset + 8 : offset + 8 + size]
        if kind == b'fmt ':
            fmt = body
        elif kind == b'data':
            samples = body
        offset += 8 + size + (size & 1)
    if fmt is None or len(fmt) < 16 or samples is None:
        raise ArgumentError('expected a WAV file with its format and its samples')
    form, channels, rate, _, _, bits = struct.unpack_from('<HHIIHH', fmt)
    if form == 0xFFFE and len(fmt) >= 26:
        (form,) = struct.unpack_from('<H', fmt, 24)
    width = (bits + 7) // 8
    if channels < 1 or rate < 1 or (form, width) not in _SAMPLE_FORMATS:
        raise ArgumentError(f'expected PCM or float samples, found format {form} of {bits} bits')
    return form, rate, channels, width, len(samples) // (width * channels), samples


def _channels_numpy(form: int, width: int, channels: int, frames: int, raw: bytes) -> Any:
    import numpy as np

    raw = raw[: frames * channels * width]
    if (form, width) == (1, 1):
        values = (np.frombuffer(raw, np.uint8).astype(np.float64) - 128) / 128
    elif (form, width) == (1, 2):
        values = np.frombuffer(raw, '<i2') / 32768.0
    elif (form, width) == (1, 3):
        b = np.frombuffer(raw, np.uint8).reshape(-1, 3).astype(np.int32)
        v = b[:, 0] | (b[:, 1] << 8) | (b[:, 2] << 16)
        values = np.where(v >= 1 << 23, v - (1 << 24), v) / float(1 << 23)
    elif (form, width) == (1, 4):
        values = np.frombuffer(raw, '<i4') / float(1 << 31)
    else:
        values = np.frombuffer(raw, '<f4' if width == 4 else '<f8').astype(np.float64)
        values = np.where(np.isfinite(values), values, 0.0)
    return values.reshape(frames, channels).T


def _channels_python(form: int, width: int, channels: int, frames: int, raw: bytes) -> list:
    raw = raw[: frames * channels * width]
    if width == 3:
        values = [
            int.from_bytes(raw[i : i + 3], 'little', signed=True) / float(1 << 23)
            for i in range(0, len(raw), 3)
        ]
    else:
        code = {(1, 1): 'B', (1, 2): 'h', (1, 4): 'i', (3, 4): 'f', (3, 8): 'd'}[(form, width)]
        items = array(code)
        if items.itemsize != width:
            code = 'l' if code == 'i' else code
            items = array(code)
        items.frombytes(raw)
        if sys.byteorder == 'big':
            items.byteswap()
        if (form, width) == (1, 1):
            values = [(v - 128) / 128 for v in items]
        elif form == 1:
            scale = float(1 << (8 * width - 1))
            values = [v / scale for v in items]
        else:
            values = [v if math.isfinite(v) else 0.0 for v in items]
    return [values[c::channels] for c in range(channels)]


def _impulse(k: tuple[float, ...], rate: int) -> list[float]:
    """Returns the impulse response of the K weighting, run until it has died away."""
    b0, b1, b2, a1, a2, c1, c2 = k
    s1 = s2 = t1 = t2 = 0.0
    out = []
    for n in range(8 * rate):
        x = 1.0 if n == 0 else 0.0
        y = b0 * x + s1
        s1 = b1 * x - a1 * y + s2
        s2 = b2 * x - a2 * y
        z = y + t1
        t1 = -2 * y - c1 * z + t2
        t2 = y - c2 * z
        out.append(z)
        if n > 64 and abs(s1) + abs(s2) + abs(t1) + abs(t2) + abs(z) < 1e-18:
            break
    return out


def _energy_numpy(signals: Any, rate: int) -> Any:
    """Returns the weighted sum of the squares of the K weighted channels, frame by frame."""
    import numpy as np

    h = np.array(_impulse(_k_weighting(rate), rate))
    frames = signals.shape[1]
    energy = np.zeros(frames)
    block = 1 << 18
    size = 1 << math.ceil(math.log2(block + len(h) - 1))
    spectrum = np.fft.rfft(h, size)
    for weight, signal in zip(_weights(signals.shape[0]), signals, strict=True):
        if weight == 0:
            continue
        out = np.zeros(frames + size)
        for start in range(0, frames, block):
            part = signal[start : start + block]
            out[start : start + size] += np.fft.irfft(np.fft.rfft(part, size) * spectrum, size)
        energy += weight * out[:frames] ** 2
    return energy


def _energy_python(signals: list, rate: int) -> list[float]:
    b0, b1, b2, a1, a2, c1, c2 = _k_weighting(rate)
    frames = len(signals[0]) if signals else 0
    energy = [0.0] * frames
    for weight, signal in zip(_weights(len(signals)), signals, strict=True):
        if weight == 0:
            continue
        s1 = s2 = t1 = t2 = 0.0
        for n, x in enumerate(signal):
            y = b0 * x + s1
            s1 = b1 * x - a1 * y + s2
            s2 = b2 * x - a2 * y
            z = y + t1
            t1 = -2 * y - c1 * z + t2
            t2 = y - c2 * z
            energy[n] += weight * z * z
    return energy


def _peak_numpy(signals: Any, rate: int) -> float:
    import numpy as np

    peak = float(np.max(np.abs(signals))) if signals.size else 0.0
    for row in _interpolation(4 if rate < 96000 else 2):
        kernel = np.array(row[::-1])
        for signal in signals:
            if len(signal):
                peak = max(peak, float(np.max(np.abs(np.convolve(signal, kernel)))))
    return peak


def _peak_python(signals: list, rate: int) -> float:
    peak = max((abs(v) for signal in signals for v in signal), default=0.0)
    rows = _interpolation(4 if rate < 96000 else 2)
    mul = operator.mul
    for signal in signals:
        padded = [0.0] * 15 + list(signal) + [0.0] * 16
        for n in range(len(signal) + 16):
            window = padded[n : n + 16]
            for row in rows:
                value = abs(sum(map(mul, row, window)))
                if value > peak:
                    peak = value
    return peak


def loudness(data: bytes, use_numpy: bool | None = None) -> dict[str, Any]:
    """Measures a WAV sample as the page does, after ITU-R BS.1770 and EBU Tech 3341.

    Args:
        data: The bytes of a WAV file of PCM or float samples.
        use_numpy: Whether to use numpy, by default when it imports.

    Returns:
        A dictionary with `integrated`, `maxMomentary` and `maxShortTerm` in LUFS, `truePeak` in
        dBTP, each `None` for silence, `seconds`, the sample's length, `measured`, the seconds read,
        at most 60, `rate` and `channels`. A sample shorter than one gating block of 400 ms reads
        its mean loudness over its whole length as its integrated loudness.

    Raises:
        ArgumentError: If the bytes are no WAV file of PCM or float samples.
    """
    form, rate, count, width, frames, raw = _wav(data)
    measured = min(frames, MAXIMUM_SECONDS * rate)
    if use_numpy is None:
        try:
            import numpy  # noqa: F401

            use_numpy = True
        except ImportError:
            use_numpy = False
    hop = _round(rate / 10)
    offsets = [_round(j * hop / 4) for j in range(4)]
    starts = [(k // 4) * hop + offsets[k % 4] for k in range(4 * (measured // hop + 2))]
    starts = [s for s in starts if s <= measured]
    if use_numpy:
        import numpy as np

        signals = _channels_numpy(form, width, count, measured, raw)
        energy = _energy_numpy(signals, rate)
        cumulative = np.concatenate(([0.0], np.cumsum(energy)))
        parts = list(np.diff(cumulative[starts])) if len(starts) > 1 else []
        total = float(cumulative[-1])
        peak = _peak_numpy(signals, rate)
    else:
        signals = _channels_python(form, width, count, measured, raw)
        energy = _energy_python(signals, rate)
        parts = [sum(energy[a:b]) for a, b in itertools.pairwise(starts)]
        total = sum(energy)
        peak = _peak_python(signals, rate)
    momentary = short = 0.0
    sums = [0.0]
    for part in parts:
        sums.append(sums[-1] + part)
    blocks = []
    for i in range(len(parts)):
        window = sums[i + 1] - sums[max(0, i + 1 - 16)]
        momentary = max(momentary, window)
        short = max(short, sums[i + 1] - sums[max(0, i + 1 - 120)])
        if (i + 1) % 4 == 0 and i + 1 >= 16:
            blocks.append(window / (4 * hop))
    gated = [b for b in blocks if _lufs(b) > -70]
    if len(parts) < 16:
        integrated = _lufs(total / measured) if measured else -math.inf
    elif gated:
        relative = _lufs(sum(gated) / len(gated)) - 10
        kept = [b for b in gated if _lufs(b) > relative]
        integrated = _lufs(sum(kept) / len(kept)) if kept else -math.inf
    else:
        integrated = -math.inf

    def value(level: float) -> float | None:
        return round(level, 3) if math.isfinite(level) else None

    return {
        'integrated': value(integrated),
        'maxMomentary': value(_lufs(momentary / (4 * hop))),
        'maxShortTerm': value(_lufs(short / (30 * hop))),
        'truePeak': value(20 * math.log10(peak) if peak > 0 else -math.inf),
        'seconds': round(frames / rate, 3),
        'measured': round(measured / rate, 3),
        'rate': rate,
        'channels': count,
    }
