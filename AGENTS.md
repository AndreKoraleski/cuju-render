# Notes for coding agents

cuju-render is the browser renderer of cuju. It installs into the folder of the package `cuju`,
as `cuju/render`, and uses only cuju's public interface. The engine, its outputs and its digests
belong to cuju, and the renderer reads states and never writes one.

## Layout

- `src/cuju/render/` holds the package, the public names in `__init__.py`, the command in
  `__main__.py`, the private subpackages and the page in `web/`. CONTRIBUTING.md maps them.
- `tests/` holds the Python tests by area, `tests/support/` their shared parts and `tests/web/`
  the page's Node tests.
- `ci/` holds the mock servers, the page checks in headless Chrome, the wheel check, and the link
  check and the asset scripts that are run by hand.
- `docs/` holds the user guides.

## Build and test

```sh
pip install cuju                              # or an editable cuju from its own checkout
pip install -e '.[test]'                      # the renderer, editable, from this checkout
pytest tests                                  # the Python tests
for f in tests/web/*.mjs; do node "$f"; done  # the page's logic on Node 18 or later
python ci/page_check.py                       # the page in headless Chrome against the mock
ruff check src tests ci && ruff format --check src tests ci
```

## Rules

- The server listens on loopback only, checks Host on every request and Origin on requests that
  change data. Uploads and file operations stay inside their folder.
- Submissions are Python code, and weights load with `weights_only`.
- The page starts muted and sound plays only on Watch or Play while not paused.
- Pointer lock is opt in and is released whenever a dialog, menu, card or panel opens.
- Every page string comes from a language file, and the whole page works by keyboard.
- JavaScript is ES modules, checked with `node --input-type=module --check < file.js`.
- Python follows `ruff` with line length 100 and single quotes, with docstrings and comments in
  full sentences.
