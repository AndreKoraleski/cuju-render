# cuju-render

cuju-render is the browser renderer of [cuju](https://github.com/AndreKoraleski/cuju), the
bit-exact, batched reimplementation of Google Research Football. It shows matches in three
dimensions, with sound, from recordings saved to files and live from a running batch, and it keeps
a registry of teams for requested matches, tournaments, challenges and games played by keyboard,
controller or touch. Every page has a command or a Python call beside it, so agents use it as
people do.

The renderer reads states and never writes one. Watching a match therefore leaves every
observation, reward, done flag and state of the batch as it would be unwatched, bit for bit.

## Installation

cuju-render installs into the folder of cuju and adds the module `cuju.render` and the command
`cuju render`. The extra `render` of cuju installs it with a version that fits.

```sh
pip install 'cuju[render]'
```

`pip install cuju-render` does the same and brings cuju along when it is missing. cuju-render 0.1
runs with cuju 0.2.1 and every later release of cuju 0.2.

The pages run in a recent Chrome, Edge, Firefox or Safari, and the Export video dialog of Watch
draws and encodes the video in that browser with nothing else installed. The command
`cuju render video` needs an installed Chrome, Edge or Chromium, which writes MP4 with H.264 or
WebM, and nothing beside it.

## Quick start

Three lines of Python show a running batch in the browser, in a new tab from a script and inside
the notebook in Jupyter and Google Colab.

```python
import cuju.render
batch = cuju.BatchEnvironment('11_vs_11_stochastic_l1_r0', environment_count=8)
cuju.render.show(batch)
```

The demo plays a live match of the built in AI with no script at all, and `serve` starts the
server on its own.

```sh
cuju render demo
cuju render serve --open
```

`cuju render app` opens the page in a window of its own, and `cuju render app --install` adds it to
the computer's apps, a shortcut on Windows, an entry of the applications menu on Linux and an app in
`~/Applications` on macOS. The extra `app`, `pip install 'cuju-render[app]'`, draws that window
with the system's web view, and without it the window comes from Edge, Chrome, Chromium or Brave.

## Documentation

- [Rendering][rendering], the full guide to the pages, recordings, live sources, teams,
  tournaments, challenges, video export, the clean feed and the command line
- [Team presentation packages][presentation], the contract of a team's own models, clips,
  effects and sounds
- [Python reference][reference], the reference of `cuju.render`
- [Changelog][changelog]

## License

The code is licensed under the Apache License 2.0. The page ships three.js and Fabric.js under the
MIT license, art converted from Gameplay Football under the Unlicense, characters, clips and sounds
under CC0 1.0, and copies of cuju's logo and montage under CC BY 4.0. [NOTICE][notice] names every
part, and the license texts are in [LICENSES][licenses]. cuju-render is an independent project,
neither affiliated with nor endorsed by Google.

[rendering]: https://github.com/AndreKoraleski/cuju-render/blob/main/docs/rendering.md
[presentation]: https://github.com/AndreKoraleski/cuju-render/blob/main/docs/presentation.md
[reference]: https://github.com/AndreKoraleski/cuju-render/blob/main/docs/reference.md
[changelog]: https://github.com/AndreKoraleski/cuju-render/blob/main/CHANGELOG.md
[notice]: https://github.com/AndreKoraleski/cuju-render/blob/main/NOTICE
[licenses]: https://github.com/AndreKoraleski/cuju-render/tree/main/LICENSES
