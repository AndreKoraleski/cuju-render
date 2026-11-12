# Contributing

cuju-render is the browser renderer of cuju. Reports and pull requests about the pages, recordings,
teams, tournaments, video export and the command `cuju render` belong here, and reports about the
engine and its outputs belong to [cuju](https://github.com/AndreKoraleski/cuju).

## Layout

`src/cuju/render/` holds the package, every public name in `__init__.py` and the command in
`__main__.py`. Everything else is private, in subpackages whose `__init__.py` holds a docstring
alone. A module imports a sibling under its old name, as in
`from .._http import server as _server`, and imports cuju by its absolute name, so a search for
`from cuju` lists every use.

| Subpackage | Concern |
| --- | --- |
| `_text/` | the server's messages and the page's languages |
| `_format/` | the recording format, its codec, the recorder's writer, filters and annotations |
| `_store/` | the home folder, the library of recordings and the samples |
| `_moments/` | the moments of a match, their search and their captions |
| `_watch/` | live sources, the grid of environments, `show` and notebooks |
| `_registry/` | the team registry, celebration clips and model joints |
| `_packages/` | team presentation packages, their contract, checks and author tools |
| `_playing/` | requested matches, games, the demo, challenges, achievements and policy errors |
| `_tournaments/` | tournament rules, their runner and their command |
| `_export/` | video export, the clean feed and the shared picture sizes |
| `_http/` | the server, finding or starting it, the page commands, the installable app, the app window and its launchers |
| `_guide/` | Help, the agent tutorial and the diagnostic report |

The layers run from `_text`, `_format` and `_store` at the bottom to `_http` and the root at the
top. A module imports lower layers at the top of the file and higher ones only inside a function.
`_moments/events.py`, `_moments/captions.py`, `_playing/draw.py` and `_http/headers.py` keep no
relative imports at the top, and `_tournaments/tournament.py` and `_text/messages.py` import only each other and
`cuju.errors`, since the mock servers load them from their files alone, and
`_tournaments/results.py` uses the standard library alone for the same reason.
`_playing/policy_worker.py` runs as a script of its own in each team's process under strict rules,
so it imports nothing of the renderer. `_http/headers.py` holds
the security headers of every response, so the page checks meet the server's rules of framing,
and a test holds the mock's headers equal to the server's. Python rules that the page mirrors keep a
test that holds both sides equal, in `web/js/export/sizes.js`, `web/js/recording/moments.js`,
`web/js/presentation/catalog.js` and `web/js/play/tournament-layout.js`, whose entrant names
and abilities share their cases with the Python tests in `tests/support/entrant_names.json` and
`tests/support/entrant_abilities.json`.

The page is `web/`. `js/boot.js` is a classic script that runs before every module, and the
modules sit in folders by concern, from `core/` and `recording/` at the bottom through `world/`,
`players/`, `broadcast/` and `watch/` to `export/`, `teams/`, `play/`, `pages/`, `help/` and
`presentation/`. One edge runs upward, `core/accessibility.js` taking `h` from
`teams/library.js`, until `h` and `listKeys` move into a `core/dom.js`.

`tests/` holds the Python tests by area, `tests/support/` their shared parts and `tests/web/` the
page's Node tests, each copying its modules into a folder that mirrors `web/js/`. `ci/` holds the
mock servers `mock_*.py`, the page checks `page_*.py` in headless Chrome, the wheel check and the
asset scripts `make_*` that are run by hand, and `docs/` holds the user guides. The page ships
in English, `web/languages/en.json`, and `translations/` holds the drafts of other languages
outside the package, one folder per language named after its code of BCP 47, today `pt-BR` for
Brazilian Portuguese with its messages `pt-BR.json`, its style guide and its glossary, which the
tests that need a second language import.

A new module goes into the subpackage or folder of its concern. A module too long to read in one
sitting splits along its sections, the old one importing the moved names back.

## Before a pull request

1. Run `pytest tests` and the Node tests, `for f in tests/web/*.mjs; do node "$f"; done`.
2. Run `python ci/page_check.py` for a change to the page.
3. Run `ruff check src tests ci` and `ruff format --check src tests ci`.
4. Write each commit message as one line in the imperative, at most 72 characters, with no body.
5. Write docs to Wikipedia's Manual of Style, with prose that uses only words, commas and periods.

[AGENTS.md](AGENTS.md) holds the rules, commands and style in short form.
