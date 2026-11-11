# Python reference

The package cuju-render adds the module `cuju.render` to cuju. [Rendering](rendering.md) describes
the renderer as a whole, its pages, commands and settings, and cuju's [API reference][cuju-api]
describes the batch, its step observers and the rest of cuju.

| Module | Names |
| --- | --- |
| `cuju.render` | `Recorder(batch, environment=0, title=None, teams=None, scenario=None, version=2, keep=None, every=1, min_reward=None)` with `capture(done=None)`, `save()`, `flush()`, `annotate(values=None, text=None, player=None, step=None, probabilities=None, action=None)`, `saved`, `episodes` and `dropped`, `watch(batch, environment=0, title=None, teams=None, backlog=False)` and `LiveSource` with the same `annotate`, `add_team(folder, name=None, format='11v11')`, `play(left, right, scenario='11_vs_11_kaggle', seed=None, title=None, device='cpu', ability=(None, None))`, `show(target=None, environment=0, title=None, teams=None, display='auto', port=None, stay=False, height=600)` returning a `View`, `record(batch, environment=0, **options)` and `Recorder.close()`, `serve(port=8780, open_browser=False, page='', remote=False, parent=None)`, `home()` and `on_batch_created(batch)`, and the command `cuju render [serve\|open\|team\|play\|sample]`, also `python -m cuju.render`. Described in [Rendering](rendering.md) |

`Recorder` and `watch` add a step observer to their batch, so a recorder captures every reset and
step by itself and saves an episode when it ends. `Recorder.capture(done)` captures by hand, as
programs written for cuju 0.2.0 do, and its first call turns the automatic capture off.
`Recorder.save()` saves the frames captured so far. Both return a path or `None`. A thread of the
renderer codes and writes each recording, so the step that ends an episode only hands its frames
over, `saved` gains a path once its file is written, and `save()`, `flush()` and closing the batch
wait for the writes, `save()` and `flush()` raising the error of one that failed. A recorder writes
the recording format of version 2, and `version=1` writes the larger version 1 that the page of
cuju 0.2.0 reads.
`keep`, `every` and `min_reward` decide at the end of each episode whether to save it, from a
summary of its score, goals, length, rewards and annotations, and `dropped` counts the episodes
left out. `Recorder.annotate` and `LiveSource.annotate` attach named numbers, a text, the chosen
action and the likely actions to a captured step, for one player or the whole match, which the
page shows. A recorder writes them into the recording, and a source streams them to its viewers
and returns whether a frame took them.
`LiveSource.close()` withdraws a source, and `watch` replaces any source already attached to that
batch.
`LiveSource.select_environment(index)` shows another environment of the batch from its next step
on. `home()` returns the renderer folder. Every batch that cuju creates while `CUJU_RENDER` is set
calls `on_batch_created(batch)`, which gives it the live source that the variable asks for.

`play` runs a requested match and returns its recording path. Each team's saved control settings
choose the count, dynamic or fixed assignment, indices or roles, goalkeeper and action set.
The scenario may be bundled or one of the six renderer GRF MARL scenarios. Each entry of `ability`
sets GRF's team difficulty from 0 to 1, with `None` keeping that side's scenario value.
The browser also provides Play a game with keyboard and controller input, described in
[Rendering](rendering.md#playing-a-game).

[cuju-api]: https://github.com/AndreKoraleski/cuju/blob/main/docs/api.md
