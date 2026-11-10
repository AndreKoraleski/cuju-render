# Copyright 2026 The cuju Authors
# SPDX-License-Identifier: Apache-2.0

"""`show`, which opens the viewer on a batch, a recording or a live source in one call.

`show` reuses the server of the home folder or starts one in the background, gives a batch a live
source, and opens the page in the browser, or inline in a notebook of Jupyter or Google Colab.
"""

from __future__ import annotations

import os
from typing import Any

from cuju.errors import ArgumentError

from .._http import launch as _launch
from . import notebook as _notebook
from .live import LiveSource

# The ways `show` may open the page.
_DISPLAYS = ('auto', 'browser', 'inline', 'none')


class View:
    """The viewer that `show` opened, with its address and the live source it attached.

    A view is a context manager, and leaving it closes the live source that `show` gave a batch,
    while the server goes on.

    Attributes:
        url: The address of the page on this machine.
        server: The server, with its `port` and its process `pid`.
        source: The live source that the page shows, or `None` for a recording or the Home page.
    """

    def __init__(
        self,
        server: _launch.Server,
        fragment: str,
        source: LiveSource | None,
        owned: bool,
        height: int,
        kind: str | None,
    ) -> None:
        self.server = server
        self.url = fragment if '://' in fragment else server.url + fragment
        self.source = source
        self._fragment = fragment
        self._owned = owned
        self._height = height
        self._kind = kind
        # The cell that `show` displayed the view in, which the value of the cell shows again.
        self._shown_in: int | None = None

    def __repr__(self) -> str:
        return f'View({self.url!r})'

    def __enter__(self) -> View:
        return self

    def __exit__(self, *exception: object) -> None:
        self.close()

    def close(self) -> None:
        """Closes the live source that `show` attached to a batch, and leaves any other one."""
        if self._owned and self.source is not None:
            self.source.close()

    def display(self) -> None:
        """Shows the viewer inline in the output of the running notebook cell."""
        kind = self._kind or _notebook.environment()
        if kind is None:
            raise ArgumentError('expected a notebook of Jupyter or Google Colab to show the viewer')
        if '://' in self._fragment:
            raise ArgumentError(f'expected a page of this server, found {self._fragment}')
        self._shown_in = _notebook.execution_count()
        _notebook.display(kind, self.server.port, self.server.key, self._fragment, self._height)

    def _ipython_display_(self) -> None:
        # A view that `show` returns as the value of its own cell is already on screen, and the
        # terminal of IPython prints the view's address.
        if self._shown_in is not None and self._shown_in == _notebook.execution_count():
            return
        if (self._kind or _notebook.environment()) is None or '://' in self._fragment:
            print(repr(self))
            return
        self.display()


def _fragment_of(
    target: Any, environment: int, title: str | None, teams: Any
) -> tuple[str, LiveSource | None, bool]:
    """Returns the end of the page's address for `target`, its live source and whether `show`
    attached that source."""
    from .. import watch

    if isinstance(target, LiveSource):
        return f'#live={target.identifier}', target, False
    if callable(getattr(target, 'add_observer', None)):
        for observer in target.observers:
            if isinstance(observer, LiveSource) and observer.environment == environment:
                return f'#live={observer.identifier}', observer, False
        source = watch(target, environment, title, teams)
        return f'#live={source.identifier}', source, True
    if target is None or isinstance(target, (str, os.PathLike)):
        return _launch.resolve(target), None, False
    raise ArgumentError(
        'expected a batch, a live source, a recording file, the identifier of a recording or None, '
        f'found {type(target).__name__}; for a MultiDeviceBatch show one of its parts'
    )


def show(
    target: Any = None,
    *,
    environment: int = 0,
    title: str | None = None,
    teams: list[dict[str, Any]] | None = None,
    display: str = 'auto',
    port: int | None = None,
    stay: bool = False,
    height: int = 600,
) -> View:
    """Opens the viewer on a batch, a recording or a live source, starting the server when needed.

    The server of the home folder answers when one runs, and otherwise `show` starts one in a
    process of its own, which ends with this process unless `stay` is true. A batch receives a
    live source of `environment`, or keeps the one it has, and the page opens on it. A recording
    file outside the library is copied into it first.

    Args:
        target: A batch, a `LiveSource`, a `.cjr` file, the identifier of a recording or live
            source, a URL of the page, or `None` for the Home page.
        environment: The environment of a batch to show.
        title: The title of a new live source, as for `watch`.
        teams: The names and colors of the teams of a new live source, as for `watch`.
        display: `auto` shows the viewer inline in a notebook of Jupyter or Colab and opens the
            browser elsewhere, `browser` and `inline` choose one, and `none` opens nothing.
        port: The port of a server that `show` starts, by default 8780 when it is free.
        stay: Whether a server that `show` starts outlives this process.
        height: The height of the inline viewer in pixels.

    Returns:
        The view, with the page's `url` and its live `source`. Leaving it as a context manager
        closes a source that `show` attached.

    Raises:
        ArgumentError: If the target names nothing to show, or `display` is not one of the four.
    """
    if display not in _DISPLAYS:
        raise ArgumentError(
            f'expected display to be one of {", ".join(_DISPLAYS)}, found {display!r}'
        )
    fragment, source, owned = _fragment_of(target, environment, title, teams)
    kind = _notebook.environment()
    try:
        server = _launch.start(port, stay, colab=kind == 'colab')
    except BaseException:
        if owned and source is not None:
            source.close()
        raise
    view = View(server, fragment, source, owned, height, kind)
    if display == 'auto':
        display = 'inline' if kind is not None and '://' not in fragment else 'browser'
    if display == 'inline':
        view.display()
    elif display == 'browser':
        opened = _launch.open_browser(view.url)
        print(f'cuju render {"opened" if opened else "serves"} {view.url}', flush=True)
    return view
