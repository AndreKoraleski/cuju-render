# Copyright 2026 The cuju Authors
# SPDX-License-Identifier: Apache-2.0

"""Shows the viewer inside a notebook of Jupyter or Google Colab.

The environment is read from the modules that the process has already loaded, so a script or a
terminal never imports IPython or Colab. Jupyter shows the page of the local server in a frame,
and Colab serves it through its own proxy, which carries the page from the machine of the notebook
to the browser of the person who uses it.
"""

from __future__ import annotations

import html
import importlib
import sys
from typing import Any

# The text of the link that opens the viewer at full size.
FULL_SIZE = 'Open the viewer full size'


def environment() -> str | None:
    """Returns `colab` or `jupyter` inside a notebook of either, and `None` elsewhere.

    The terminal of IPython counts as no notebook, since a browser shows its pages.
    """
    ipython = sys.modules.get('IPython')
    get = getattr(ipython, 'get_ipython', None)
    shell = get() if callable(get) else None
    if shell is None:
        return None
    kind = type(shell)
    if kind.__module__.startswith('google.colab'):
        return 'colab'
    if kind.__name__ == 'ZMQInteractiveShell' or hasattr(shell, 'kernel'):
        return 'colab' if 'google.colab' in sys.modules else 'jupyter'
    return None


def execution_count() -> int | None:
    """Returns the number of the cell that runs, or `None` outside IPython."""
    ipython = sys.modules.get('IPython')
    get = getattr(ipython, 'get_ipython', None)
    shell = get() if callable(get) else None
    count = getattr(shell, 'execution_count', None)
    return count if isinstance(count, int) else None


def markup(frame: str, full: str, height: int) -> str:
    """Returns the HTML of the viewer in a frame of `height` pixels, with a link to `full`."""
    return (
        '<div class="cuju-render">'
        f'<iframe src="{html.escape(frame)}" width="100%" height="{int(height)}" '
        'style="border: 0" allow="autoplay; fullscreen" title="cuju viewer"></iframe>'
        f'<p><a href="{html.escape(full)}" target="_blank" rel="noopener">{FULL_SIZE}</a></p>'
        '</div>'
    )


def display(kind: str, port: int, key: str, fragment: str, height: int) -> None:
    """Shows the page of the server on `port` in the output of the running cell.

    Args:
        kind: `jupyter` or `colab`, as `environment` returns it.
        port: The port of the server.
        key: The key of the server, which lets the notebook frame the page.
        fragment: The end of the address, from `#` on.
        height: The height of the frame in pixels.
    """
    framed = f'/?embed={key}{fragment}'
    if kind == 'colab':
        output: Any = importlib.import_module('google.colab.output')
        output.serve_kernel_port_as_iframe(port, path=framed, height=str(int(height)))
        output.serve_kernel_port_as_window(port, path=f'/{fragment}', anchor_text=FULL_SIZE)
        return
    shown: Any = importlib.import_module('IPython.display')
    base = f'http://127.0.0.1:{port}'
    shown.display(shown.HTML(markup(base + framed, f'{base}/{fragment}', height)))
