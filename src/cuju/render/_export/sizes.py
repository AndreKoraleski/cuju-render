# Copyright 2026 The cuju Authors
# SPDX-License-Identifier: Apache-2.0

"""The picture sizes of the renderer, shared by the clean feed, video export and the commands.

The page's module `web/js/export/sizes.js` holds the same presets, aliases, limits and layout, and a
test keeps the two equal, so a size means the same picture in the address of a feed, in the Export
video dialog, in photo mode and on the command line.
"""

from __future__ import annotations

import math
import re
from typing import Any

from cuju.errors import ArgumentError

# The named sizes, by the identifier that addresses and commands accept, with width and height.
PRESETS: dict[str, tuple[int, int]] = {
    '480p': (854, 480),
    '720p': (1280, 720),
    '1080p': (1920, 1080),
    '1440p': (2560, 1440),
    '4k': (3840, 2160),
    'square': (1080, 1080),
    'portrait': (1080, 1350),
    'vertical': (1080, 1920),
}
# Other names of sizes, each naming a preset or a size of its own.
ALIASES = {
    '360p': '640x360',
    '2160p': '4k',
    'uhd': '4k',
    'hd': '720p',
    'fhd': '1080p',
    'tall': 'vertical',
}
# The size that a feed takes when its address names none.
DEFAULT_SIZE = '1080p'
# The smallest and largest side of a picture, and its largest area, that of 4K.
MIN_SIDE = 90
MAX_SIDE = 3840
MAX_AREA = 3840 * 2160
# The page lays out with its shorter side at this many CSS pixels.
LAYOUT_SHORT = 720
# The scale of the graphics, which makes them larger or smaller than the layout gives them.
MIN_GRAPHICS = 0.5
MAX_GRAPHICS = 2.0
# The safe areas that the page keeps, and the largest margin as a percentage of a side.
SAFE_MODES = ('auto', 'none', 'social')
MAX_SAFE_PERCENT = 25

# A width and height, with a letter x or a multiplication sign between.
_SIZE = re.compile('(\\d{1,5})\\s*[x\u00d7]\\s*(\\d{1,5})')


def check_size(
    width: Any,
    height: Any,
    *,
    minimum: int = MIN_SIDE,
    maximum: int = MAX_SIDE,
    area: int = MAX_AREA,
    even: bool = False,
) -> tuple[int, int]:
    """Returns a checked width and height, or raises `ArgumentError` with what fits.

    Each side is a whole number from `minimum` to `maximum`, even when `even` asks for it as the
    video encoder does, and the picture holds at most `area` pixels.
    """
    for value, name in ((width, 'width'), (height, 'height')):
        if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
            raise ArgumentError(f'expected a {name} from {minimum} to {maximum}, found {value!r}')
        if even and value % 2:
            raise ArgumentError(f'expected an even {name}, found {value}')
    if width * height > area:
        raise ArgumentError(
            f'expected a picture of at most {area} pixels, as 3840 by 2160, '
            f'found {width} by {height}'
        )
    return width, height


def parse_size(text: Any, **limits: Any) -> tuple[int, int]:
    """Returns the width and height that a size names, as `check_size` checks them.

    A size is a preset such as `1080p` or `vertical`, an alias such as `2160p`, or a width and
    height such as `1280x720`.

    Raises:
        ArgumentError: If the text names no size or the size is out of range.
    """
    value = str(text).strip().lower()
    value = ALIASES.get(value, value)
    if value in PRESETS:
        return check_size(*PRESETS[value], **limits)
    match = _SIZE.fullmatch(value)
    if not match:
        raise ArgumentError(
            f'expected a size such as 1280x720 or one of {", ".join(PRESETS)}, found {text!r}'
        )
    return check_size(int(match[1]), int(match[2]), **limits)


def size_name(width: int, height: int) -> str:
    """Returns the name of a size, its preset's identifier or the width and height as `WxH`."""
    for name, size in PRESETS.items():
        if size == (width, height):
            return name
    return f'{width}x{height}'


def parse_graphics(text: Any) -> float:
    """Returns the scale of the graphics that a text or number names, or raises."""
    try:
        value = float(text)
    except (TypeError, ValueError):
        value = math.nan
    if not MIN_GRAPHICS <= value <= MAX_GRAPHICS:
        raise ArgumentError(
            f'expected a scale of the graphics from {MIN_GRAPHICS:g} to {MAX_GRAPHICS:g}, '
            f'found {text!r}'
        )
    return value


def parse_safe(text: Any) -> str | float:
    """Returns the safe area that a text names, `auto`, `none`, `social` or a percentage."""
    value = str(text).strip().lower()
    if value in SAFE_MODES:
        return value
    try:
        percent = float(value.removesuffix('%'))
    except ValueError:
        percent = math.nan
    if not 0 <= percent <= MAX_SAFE_PERCENT:
        raise ArgumentError(
            f'expected a safe area of {", ".join(SAFE_MODES)} or a percentage from 0 to '
            f'{MAX_SAFE_PERCENT}, found {text!r}'
        )
    return percent


def layout(width: int, height: int, graphics: float = 1.0) -> tuple[int, int, float]:
    """Returns the page's width and height in CSS pixels and the scale that gives the picture.

    The shorter side lays out at `LAYOUT_SHORT` CSS pixels, so the graphics keep their proportion
    at every size and shape, and a smaller picture lays out at its own size. The scale of the
    graphics shrinks or grows the layout around them.
    """
    graphics = min(MAX_GRAPHICS, max(MIN_GRAPHICS, float(graphics)))
    scale = max(1.0, min(width, height) / LAYOUT_SHORT) * graphics
    # Halves round up, as the page's Math.round does.
    css_width = max(1, math.floor(width / scale + 0.5))
    return css_width, max(1, math.floor(height / scale + 0.5)), scale
