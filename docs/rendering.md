# Rendering

In cuju, the **renderer** is a browser page that shows matches in three dimensions, with the
players, the ball, the pitch and the crowd drawn from the art of Google Research Football, or GRF,
and from free characters, and with sound mixed in the browser. It watches two kinds of source. A
**recording** is a match saved to a file, which the page plays at any speed, forwards and backwards,
and a **live source** is one environment of a running batch, which the page shows while the batch
plays. The renderer is the package cuju-render, which installs beside cuju with
`pip install 'cuju[render]'` and adds the module `cuju.render`. Its server needs only Python's
standard library beside cuju's own dependencies, and its page runs in the browser. Video export
needs a browser and nothing else, the page's own browser on the Watch page, and an installed
Chrome, Edge or Chromium for the command `cuju render video`.

The viewer reads states. Watching a match therefore leaves every observation, reward, done flag and
state of the batch as it would be unwatched, bit for bit. GRF's own renderer runs inside the engine
and changes the matches it draws. In cuju, a saved or watched match is the same match that training
sees, which the public tests check on both backends.

## Quick start

Three lines of Python show a running batch in the browser.

```python
import cuju.render
batch = cuju.BatchEnvironment('11_vs_11_stochastic_l1_r0', environment_count=8)
cuju.render.show(batch)
```

`cuju.render.show` starts the renderer's server in the background, gives environment 0 of the
batch a live source and opens the page on it, in the default browser from a script or a terminal
and inside the notebook in Jupyter or Google Colab, as [Notebooks](#notebooks) describes. The batch
then steps as it always does, in a training loop or any other code, and the page shows its matches
while it plays. A second call reuses the server, and the server ends with the process that started
it. [Showing from code](#showing-from-code) describes every argument.

The quickest first look is the demo, which needs no script at all.

```sh
cuju render demo
```

The demo starts the server, or uses the server that already answers on its port, and plays a match
between the built in AIs in a process of its own, five a side by default. It opens the page on that
match as a live source, so play shows within seconds of the command, and one match follows another
until Ctrl+C, which ends the match, any server that the demo started and the command itself within
about a second. The option `--eleven` plays eleven a side, `--scenario` plays another shipped
scenario, such as `academy_corner`, `--port` names the port of the server, `--seed` fixes the seed
and `--no-open` leaves the browser as it is. A server that keeps another folder lists other sources,
so the demo then says so and opens the page at its start, and the option `--home` of `cuju render`
gives both the same folder.

The page runs as a local server, which listens on the loopback interface of the machine and keeps
its files in a hidden folder, `~/.cuju/render` by default. The package installs the command `cuju`,
whose subcommand `cuju render` runs the renderer, as `python -m cuju.render` does. The first command
starts the server and opens Home, the second opens a recording file, and the third plays a script
with one of its environments shown live.

```sh
cuju render
cuju render open match.cjr
CUJU_RENDER=on python train.py
```

The server prints its address, `http://127.0.0.1:8780/` by default. The option `--port` of `serve`
accepts ports from zero to 65535, with zero choosing a free port. The option `--home` of
`cuju render`, written before the subcommand, picks another folder, as in
`cuju render --home ./matches serve --port 8790`. A running batch with
`CUJU_RENDER` set appears in the page's list of live sources when the list next refreshes, every
eight seconds, and saved recordings appear on the next library refresh.

cuju imports the renderer only when a command, a script or `CUJU_RENDER` asks for it, so a program
that only trains loads none of it. Where the renderer is missing, `cuju render`,
`python -m cuju.render` and `import cuju.render` each end with one message naming
`pip install 'cuju[render]'`, which installs it. `CUJU_RENDER` then gives one warning through the
logger `cuju`, and every batch of the process runs on as it would without the variable.

### Showing from code

`cuju.render.show(target=None, environment=0, title=None, teams=None, display='auto', port=None,
stay=False, height=600)` opens the viewer on its target, which may be any of these.

| Target | The page opens |
| --- | --- |
| a batch | a live source of `environment`, the one the batch has or a new one with `title` and `teams` as for `watch` |
| a `LiveSource` | that source |
| a path of a `.cjr` file | the recording, which `show` copies into the library first unless the library holds it |
| the identifier of a recording or a live source | that recording or source |
| a URL of the page | that address |
| `None` | Home |

The server of the renderer's folder answers when one runs, whether `cuju render` or an earlier
`show` started it. Otherwise `show` starts one in a process of its own, on port 8780 when it is
free and on a free port otherwise, or on `port`. That server writes its messages to `server.log`
in the renderer's folder and ends with the process that started it, so a script that ends closes
its page. With `stay=True` it keeps running until it is stopped, which suits a short script that
only opens a recording. The argument `display` chooses where the page opens, `auto` inline in a
notebook and in the default browser elsewhere, `browser` or `inline` for one of them, and `none`
for neither. A machine without a display, such as a server reached over SSH, opens no browser,
and `show` prints the address instead.

`show` returns a view, whose attribute `url` holds the address of the page on this machine and
`source` the live source it shows. Leaving a view used as a context manager closes the live source
that `show` attached and leaves the server running.

```python
with cuju.render.show(batch, environment=2) as view:
    train(batch, steps=100_000)
```

`cuju.render.record(batch, environment=0, **options)` creates a [recorder](#recordings) that also
serves as a context manager, and `cuju.render.watch` returns a live source that does the same.
Leaving the `with` block of a recorder detaches it from the batch and saves the episode it was
capturing, and leaving the block of a source withdraws it from the page. `Recorder.close()` does
the same for a recorder outside a `with` block.

```python
with cuju.render.record(batch, environment=3, title='Evaluation') as recorder:
    evaluate(batch)
print(recorder.saved)
```

## Notebooks

In a notebook of Jupyter, JupyterLab or VS Code, `show` places the viewer in the output of its
cell, a frame of the page 600 pixels high with a link beneath it that opens the viewer full size in
a new tab. The argument `height` sets the height of the frame, and `display='browser'` opens a tab
of the browser instead. A view that ends its cell appears once, and naming it in a later cell shows
the viewer again.

```python
import cuju.render
cuju.render.show('sample-11v11', height=480)
```

A shipped sample opens by its name in any home folder, also one whose server never started, since
`show` and `cuju render open` add it to the library first, as `cuju render sample` does. A sample
in the Trash stays there until it is restored.

The frame shows the page of the server on the machine of the kernel at `127.0.0.1`, which is the
machine of the browser when Jupyter runs locally. A kernel on another machine needs its port
forwarded to the machine of the browser, as [Remote use](#remote-use) describes, and VS Code
forwards it from its Ports view.

In Google Colab, `show` serves the page through Colab's port proxy, the functions of
`google.colab.output`, which carry it from the machine of the notebook to the browser of the
person using Colab. A server that `show` starts there also answers the requests that arrive
under the addresses of that proxy, so the inline viewer and its full size link work in that browser
with no tunnel. A request that changes data through the proxy comes from a page whose origin names
the very address that the request names, so the page of another notebook, under another address of
Colab, changes nothing. The server ends with the notebook's runtime.

The server lets a page sit in a frame only when its address carries the key of the server, which
`show` reads from the renderer's folder, and only inside a notebook on this machine, in VS Code or
in Colab. Every other site that frames the page finds it refused, as the server refuses its
requests. `show` tells a notebook from a script by the modules that the process has already
loaded, so a script or a terminal never imports IPython or Colab.

## Recordings

A recording holds the captured steps of one episode, each as the world position and rotation of
every joint
of every player, the position and rotation of the ball, the score, the clock, the game mode, the
owner of the ball, and the action and touches of every player. `cuju.render.Recorder` captures one
environment of a batch and saves one recording per episode into the library. The recorder is a
[step observer][cuju-api-step-observers] of its batch, so from its creation on it captures every
reset of its environment and every step by itself, and saves a recording when an episode ends.
The training loop stays as it was.

```python
import cuju
import cuju.render

batch = cuju.BatchEnvironment('11_vs_11_stochastic_l1_r0', environment_count=8, device='cuda')
recorder = cuju.render.Recorder(
    batch,
    environment=3,
    title='Training run 12, environment 3',
    teams=[{'name': 'Agent', 'color': [214, 48, 49]}, {'name': 'Built-in AI'}],
)
observation = batch.reset()
for step in range(3001):
    actions = policy(observation)
    observation, reward, done, information = batch.step(actions)
print(recorder.saved)
```

Programs written for cuju 0.2.0 call `recorder.capture()` after `reset` and
`recorder.capture(done)` after each step, and they keep working. The first call of `capture` turns
the automatic capture off for good and drops the frames that it took and has not saved, so such a
program records the same frames as before. `capture` returns the path of a recording when its call
ends an episode, and it also suits a program that records chosen steps only.

Each capture reads the state of one environment and keeps about 4 KB of it, at a cost of about
5 milliseconds on one core of a laptop processor, more than two steps of an eleven a side match on
the CPU. A batch with automatic resets already shows the start of the next episode on the step that
ends one, so the recorder closes the recording at the step before, which it marks as the end, adds
the goal of the ending step to that frame's score from the scoring signal, and opens the next
recording with the new kick off. The positions of the ending step itself are gone, so a goal shows
the step before the ball crosses the line. A batch with `auto_reset=False` keeps the last step,
and the recording ends on it.

Call `recorder.save()` to keep an episode before it ends, for example when a training run stops.
It returns the saved path, or `None` when there are no captured frames, and starts a fresh
recording on the next capture. The list `recorder.saved` holds the paths written so far.

The step that ends an episode only hands its frames over. One thread of the renderer codes and
writes each recording while training steps on, in the order the episodes ended, and holds up to
four recordings, so a recorder that saves faster than the thread writes waits for room. The list
`recorder.saved` gains a recording once its file is written, and the path that `capture` returns
names the file before it exists. `recorder.save()` and closing the batch wait until every
recording handed over is written, and `recorder.flush()` waits without saving the frames of the
current episode. A write that fails, from a full disk for example, logs one warning through the
logger `cuju`, and the next `save` or `flush` raises its error. A process that exits waits for the
recordings handed over, and `recorder.episodes` counts the episodes that ended.

A recorder can keep only the episodes worth watching. `keep='goals'` saves the episodes with at
least one goal, `every=10` saves the first episode and every tenth after it, and `min_reward=1.0`
saves the episodes whose reward reaches 1. `keep` also takes a function, which receives the
summary of each episode as it ends and returns whether to save it.

```python
recorder = cuju.render.Recorder(
    batch, environment=3, keep=lambda summary: summary['goals'] >= 2 or summary['reward'] > 0.5
)
```

The summary holds the `episode` number, counted from 0 over the episodes that the recorder ended,
the `environment`, the `score` of the left and the right team, the number of `goals`, the `length`
in frames, the `steps` number of the last frame, the `rewards` of each agent of the environment
summed over the captured steps, their sum as `reward`, and the episode's
[annotations](#annotations), each with its `frame`, `step`, `player`, `values`, `text`, `action` and
`probabilities`. The agents count in the batch's order, the left team's first, and an annotation's
`player` is the number that `annotate` took, which counts the left team's players first as well,
whatever order the file lists the teams in. An episode is saved when every condition holds, and
`every` counts every episode that ends, saved or not. The recorder decides when the episode ends,
and discards the frames of an episode that it drops without writing anything, which
`recorder.dropped` counts. A filter reads only what the recorder captured and the rewards that the
step returned, so filters leave every output of the batch as it was. A call of `recorder.save()`
writes the frames captured so far whatever the filters say, and a function that raises an exception
removes the recorder from its batch as any failure of capture does. A recorder that captures by hand
does so after every step to preserve consecutive motion. Each recorder takes one batch of a
`MultiDeviceBatch`, as a live source does. A recorder that fails while it captures by itself, from a
full disk for example, leaves its batch with one warning through the logger `cuju`, and the batch
steps on.

A full match of eleven a side takes 3001 frames with automatic resets and 3002 without, about 4.4 MB
on disk, and one of five a side about 1.1 MB with the built in AI on both sides and more when agents
keep the players moving. A full match of
eleven a side plays and records in about half a minute on one core of a laptop processor, and the
recorder's writing thread codes its frames in a few seconds. The recorder writes the
[recording format](#recording-format) of version 2 by default, and `Recorder(batch, version=1)`
writes version 1, about two and a half times larger, for the page of cuju 0.2.0. The
library keeps each recording as a `.cjr` file beside a small summary that the page lists. The
summary also holds the favorite mark, tags and notes that the page edits, and the time a recording
went to the Trash, so every one of these changes rewrites the small file and leaves the frames as
they are. Deleting a recording on the page moves it to the Trash, which keeps both files on disk
until a recording is deleted from there for good.

The recordings of one run of a [challenge](#challenges) form a group, which the Recordings page
shows as one row, as [Page layout](#page-layout) describes. The summary of each such recording
holds its `group`, with the run's identifier `id`, its `title`, `competitor` and `result`, each an
English text with its message beside it in `title_id` and `title_values` and so on, the `attempt`
of the recording counted from zero, and the run's `challenge`, `attempts`, `state`, `value`,
`seconds`, `medal` and `practice`. The state is `playing` while a headless run plays, `done` once
the run is scored, `left` for a run that a person left and `stopped` for a run that ended on a
failure. `GET /api/matches` lists the summaries of the library and `GET /api/trash` those of the
Trash, both with `?group=ID` for the recordings of one group in the order of their attempts.
`DELETE /api/groups/ID` moves every recording of a group to the Trash at once and answers with
their identifiers in `trashed`, and `POST /api/groups/ID/restore` brings them all back and answers
with `restored`. Each recording of the group also restores on its own, like any other.

The command `cuju render recordings` prints the library with each group on one line, its title,
result and count, and its recordings indented below it in the order of their attempts.
`--group ID` lists one group, `--trash` lists the Trash, `--delete-group ID` and
`--restore-group ID` move a whole group, and `--json` prints the summaries. From Python,
`cuju.render.recordings` returns the same summaries, and `cuju.render.delete_group` and
`cuju.render.restore_group` move a group and return the identifiers of its recordings.

```python
import cuju.render

result = cuju.render.challenge('corner', team='builtin')
for summary in cuju.render.recordings(group=result['group']):
    print(summary['group']['attempt'], summary['id'], summary['score'])
cuju.render.delete_group(result['group'])
```

Two sample matches ship with the renderer, a full match of eleven a side and one of five a side,
both played by the built-in AI. The first start of the server copies each into the library as
`sample-11v11` and `sample-5v5`, where they appear on Home and in Recordings and open in Watch like
any other recording, dated from its shipped file, so the recordings of the user list above it.
The folder notes each sample it has received in `samples.json`, so a deleted
sample stays deleted, and a recording of the same name stays as it is. A sample in the Trash stays
there when the server starts, and Restore brings it back. The command `cuju render sample` adds
both samples again, and `cuju render sample 11v11` or `cuju render sample 5v5` adds one. A sample
that sits in the Trash comes back from there with its folder, tags and notes, and the command says
which samples it restored and which it added.

The page opens a recording in stages and shows each on a bar over the view, the download with its
share, the reading of the frames, and the players and the stadium while their files still load. A
background worker of the browser unpacks the recording and reads its frames, so the page keeps
drawing and loading meanwhile, and where a worker cannot start the page reads the recording itself
into the same frames. A worker that starts and then fails on a recording leaves it unopened and
shows why. The art of the players, the ball, the goals and the stands loads all at once
beside the recording, and the players of a recording are built once, with their models. The rest
loads when the page first needs it, the montage of Home when Home shows, the sounds when the sound
is turned on, and the models and animations of other characters when a team wears them.

The page opens a recording that decompresses to at most 128 MB, holds at most 50,000 frames and
at most 1,000,000 frames times players, and lists at most 64 players, which leaves room for fifteen
full matches of eleven a side in one file. It refuses a larger recording with a message before it
reads the frames. It also refuses a header that is no JSON object and a header whose player
entries lack a team of 0 or 1 or a whole index within the team. A header whose teams are no
objects reads with the teams Left and Right in their place, and a rate of steps that is no number
from 1 to 100 reads as ten steps a second.

## Live sources

A live source streams one environment of a running batch to the page. The environment variable
`CUJU_RENDER` gives every batch of a process a source, with `on` for environment 0 or an index for
another environment, the call `cuju.render.watch` gives one batch a source from code, and
`cuju.render.show` gives one and opens the page on it. Every
batch that cuju creates while the variable is set calls `cuju.render.on_batch_created`, which
gives it a source, and either way the source joins the [step observers][cuju-api-step-observers] of
its batch.

```python
source = cuju.render.watch(batch, environment=0, title='Self-play, league match')
```

A source listens on a free port of the loopback interface and announces itself with a small file in
the renderer's folder, which the server lists and relays to the page. The server lists a file only
while its process runs and when each field it reads has its kind, with a port from 1024 on, and
leaves out any other file alone, so the list of every other source stays whole. While a viewer
watches, the source reads passages of 50 consecutive steps, five seconds of play, and starts the
next passage when the wall clock has caught up. A batch that runs faster than real time therefore
reaches the page as continuous passages, which the page joins with cuts, and pays for about ten
state reads per second of wall time, about 5 milliseconds each. A batch that runs slower than real
time is shown step by step. Each step checks whether the batch has step observers, and a batch
without any does nothing more. An attached source also checks its viewers under a lock and reads
states for viewers or the backlog.
On the GPU, each read also waits for the step in flight, as `get_state` does, and a GPU batch that
queues many steps ahead of the device may take tens of seconds to send its first frame.

A source keeps the last 10 seconds of the steps it read, and a viewer who joins late receives them
first, so a second viewer, or a page reopened, starts with that history. The first viewer of a quiet
source starts at the present. The variable `CUJU_RENDER_BACKLOG`, or `backlog=True` for `watch`,
makes the source read every step, watched or not, at the cost of one state read per step, so that
every viewer starts 10 seconds back.

A browser keeps six connections at most to one server, shared by every tab of the page, and each
live stream holds one of them for as long as it plays. A page out of sight for half a minute
therefore lets its live stream go and takes it up again as soon as it shows, the steps in between
marked as a cut, so tabs left behind others leave the connections to the pages in use. A clean
feed keeps its stream, since a streaming program shows it unseen. Six pages on screen that each
play a live source take every connection, so a seventh page of the same server waits until one of
them closes or goes out of sight.

A source shows one environment at a time, and a viewer may switch it to any other environment of
the batch, from the Watch page or from code.

```python
source.select_environment(3)
```

The switch takes effect when the batch next finishes a step, so a batch that waits between steps
keeps the choice until it steps again, and the last choice before that step wins. The source then
reads the new environment and nothing else changes, so every observation, reward and state of
the batch stays as it was, bit for bit. The stream of the old environment ends, and the source
starts a new stream with a header of its own, since the new environment may field other players.
Its history starts afresh, and the default title and the entry in the list of sources name the
new environment, while a title given to `watch` stays. A source that cannot rewrite its entry,
from a full disk for example, keeps running on the new environment with one warning through the
logger `cuju`, and the list shows its old entry until the next switch succeeds.

The page asks a source for numbered frames, each after a serial number, and a source that closes
sends an end marker last. When the connection drops before that marker, the page keeps the frames
it holds and reconnects, waiting one, two and then four seconds between attempts. Each outage has
three attempts, and a connection that sends its header again ends the outage, so a stream that
drops now and then reconnects every time. The source sends its history again on every
connection, and the page drops the frames it already holds. Frames that the source captured
during the outage and no longer holds are lost, and the page shows the place where they are
missing as a cut. A source that the server no longer lists ends reconnection at once, and so does
a stream that comes back with another identifier, such as one from a switched environment. A
stream that closes before its header ends at once as well, as the stream of a game that ends
early does, and a stream on another server whose header has no serial numbers ends when its
connection closes.

The batch keeps stepping through any trouble of watching. A source that fails, from a full disk or
a closed port among other causes, closes itself, and the batch removes it from its observers with
one warning through the logger `cuju` and steps on. A step
captured into a CUDA graph and a step of a compiled function under `torch.compile` run without
Python, so a source shows the steps that the batch takes outside them. Each batch of a
`MultiDeviceBatch` announces a source of its own under `CUJU_RENDER`, with the index counted within
that batch, and `watch` takes one of those batches.

### The grid of environments

A source also answers for many environments at once, for the grid of environments on the Watch
page. The page asks the server for a range of up to 64 environments, with
`GET /api/live/<id>/grid?first=0&count=16`, about once a second while the grid shows, and the
server passes the request to the source. The source answers at once with what it holds for each
environment of the range, the step, the score, the clock, the game mode, the ball and the position,
team and state of every player, and an empty entry for an environment it has not read yet. The
server checks the host of every request, refuses a page of another origin, and checks the range
against the source's number of environments. The source answers the server alone, and refuses any
request that carries an origin or a body. A source of cuju 0.2.0 has no grid, and the server then
answers 404 with a message that says so.

The grid reads states only while a viewer asks for it, and stops 15 seconds after it last answered a
request, so an unwatched source pays one attribute check per step for it. The source keeps the tiles
it read until the range changes or the source closes, and a pass over the range that stopped goes on
where it stopped. A busy machine can relay the page's requests many seconds apart, and each such
request still receives the tiles read before it while the grid reads again. While it reads, the
reads stay small and bounded four ways. They happen at the end of a step of the batch, as the
stream's do, and no step reads more than 4 states for the grid. The grid reads at most 10 states a
second of wall time, the pace at which a watched stream reads its own, and starts a pass over the
range at most twice a second, so a grid of 4 environments refreshes twice a second, one of 16 about
every 1.6 seconds and one of 64 about every 6.4 seconds. After each step that read, the grid also
waits until its reads amount to at most a twentieth of the wall time, which a slow machine reaches
first. Each read leaves every observation, reward, done flag and state of the batch as it was, bit
for bit, and consumes no random numbers. On a laptop with 64 environments of eleven a side, a state
read and the gathering of its fields took about 2 milliseconds on the CPU and 3.5 milliseconds on
CUDA, and a watched grid took about 3.5 percent of the wall time on either. The stream of the source
goes on beside the grid at its own cost.

## Annotations

A training loop or a policy can attach numbers and text to the steps that a recorder or a live
source captures, and the page shows them with the match. `annotate` takes named numbers such as a
value estimate or a reward, a short text, the probabilities of the actions and the action chosen,
for one player or for the whole match.

```python
recorder = cuju.render.Recorder(batch, environment=0)
source = cuju.render.watch(batch, environment=0)
observation = batch.reset()
for step in range(3001):
    probabilities, value = policy(observation)
    actions = probabilities.argmax(-1)
    for annotated in (recorder, source):
        annotated.annotate(
            values={'value': value[0, 0]},
            probabilities=probabilities[0, 0],
            action=actions[0, 0],
            player=(0, 3),
        )
    observation, reward, done, information = batch.step(actions)
    recorder.annotate(values={'reward': reward[0, 0]}, player=(0, 3))
```

An annotation belongs to a step and to a player. `player` takes the number of a player, which counts
the players of the left team first and then those of the right team, each team from its goalkeeper
on, as the rewards and observations of a batch count them, or a pair of the team, 0 for the left,
and the index within the team, and `None` leaves the annotation to the whole match. The file keeps
the player's index in the header's list of players, which may list the right team first, and the
summary that a [filter](#recordings) reads names the player by its number again. `step` takes the
step number of the current episode, as the frame counts it, and by default the annotation goes to
the step captured last. A call before `batch.step` therefore describes the step that the policy
looked at, and a call after it the step that the batch has just played. Several calls for one step
and player join their numbers, and a later text, action or probabilities replace the earlier ones.

`values` holds at most 16 names of at most 40 characters, each number finite and kept to six
significant digits. The text is cut at 200 characters, and of the probabilities the three most
likely actions are kept. Numbers of numpy and PyTorch arrive as plain numbers, and probabilities
may be a sequence indexed by action or a mapping of action to probability. An invalid annotation
raises `ArgumentError`.

A recorder keeps the annotations of the recording it is capturing and writes them with it, in a
section of the file that version 2 holds and version 1 leaves out. They join the summary that a
[filter](#recordings) reads, so a filter can keep the episodes whose value estimate fell, for
example. A recorder that has captured no step raises `ArgumentError`, as does a step outside the
current episode.

A live source attaches an annotation to a frame of its history, the last by default, and sends it
to its viewers before the next frame, and a viewer who joins later receives the annotations of the
frames of its history. `source.annotate` returns whether a frame took the annotation, which fails
for a step that the source did not read while nobody watched.

Annotating reads nothing of the batch and changes nothing of it, so every observation, reward and
state stays as it was, bit for bit.

On the page, a recording or a live source with annotations shows the Annotations button, a symbol of
stacked layers, among the Watch controls, and a recording without them keeps the button and the overlay hidden. Under the feet
of each player in view, clear of the player, the overlay shows the player's numbers, the action
chosen with the three most likely actions and their probabilities, and the text, and the annotation
of the whole match shows in a box over the controls. A label that would reach the controls shows
over the player's head instead. The labels of the nearest players come first, and a label that
would cover another stays out, as the player labels do. Lines over the timeline draw the chosen
series, one series for each name of each player and each name of the whole match, each scaled from
its smallest value to its largest. The Annotations panel turns the numbers, the actions and the
text on or off, a choice that the page keeps in the browser, and picks the series of the timeline.
The first series shows when a recording opens. The panel works by keyboard, and Esc closes it.

## Moments and captions

The renderer names the moments of every match, the goals, shots, saves, blocks, shots off the
woodwork and near misses, the passes, sliding tackles, fouls, cards and offsides, the restarts with
their set pieces, the changes of possession, half time and full time. Each moment carries the step
and time of its event, the team and the player, the score and the clock at that step, and what
later frames settle, such as the end of a shot, the receiver of a pass, whether a tackle won the
ball and the scorer and assist of a goal. The moments come from the event catalog of
[team presentation packages](presentation.md#events), version 1 of its rules, and the page and the
server read the same moments from the same frames, with the same identifiers and times, for
recordings of both versions of the format.

A change of possession counts when the ball passes to the other team from the team that last held
it, so a loose ball that its team wins back counts as none. A set piece is a restart other than the
kick off, a corner, a free kick, a penalty, a throw in or a goal kick.

### Searching moments

The server keeps an index of the moments of every recording of the library in the subfolder
`index` of the renderer's folder, one small file per recording. The index catches up when the
server starts and before each search, so a recording that arrives is read once, a recording whose
file changes is read again, and the file of a recording deleted for good goes with it. A recording
in the Trash keeps its file and leaves the results until it is restored. A new version of the
moments or of the index rebuilds every file. A full match of eleven a side takes about a second to
read on one core of a laptop processor.

Search moments on the Recordings page opens a panel above the list with a query field, filters and
the results. The filters choose the kind, either team or one team by name, a player by number or
roster name, the time, first half, second half, the first or last fifteen minutes, the score state
of the team of the moment, the scenario, the source, such as requested matches, played games,
tournaments, challenges, recorders and live sources, and the date. Each filter adds its term to the
query, and typing narrows the results as it goes. The results list the minute of the clock, a
plain line of what happens and the recording with its date, the newest recording first and the
moments of each recording in order. A click or Enter on a result opens Watch a few seconds before
its moment, and a moment of the recording already open seeks there. Down moves from the field into
the results, Up and Down move through them, Home and End reach either end, and Up on the first
result returns to the field.

The command palette searches moments as well. A line that starts with a kind, such as `goal` or
`corners`, or holds a filter, such as `team:Greens`, lists the eight newest moments it finds and
Search moments, which opens the panel with the line. Moments of this match in the Match menu of
Watch opens the panel on the moments of the open recording.

### The query language

A query is a line of words and filters, all of which a moment must match. Words that name kinds
choose moments of any of those kinds, and other words match the title, scenario, folder, teams and
tags of the recording and the roster name of the player. A filter is a name, a colon and a value,
and quotes hold a value of several words together, as in `team:"Harbour Rovers"`. A minus sign
before a word or a filter leaves out what it matches. Case and accents never matter.

| Word | Moments |
| --- | --- |
| `goal`, `own-goal` | goals, and own goals alone |
| `shot`, `header` | shots, and headers at goal alone |
| `save`, `block` | saves by a goalkeeper and blocks by a defender |
| `woodwork`, `post`, `bar` | the ball off the frame of a goal, of a post or of the bar |
| `near-miss` | a ball just wide of a post or just over the bar |
| `pass`, `tackle` | passes and sliding tackles |
| `foul`, `card`, `yellow`, `red`, `offside` | fouls, cards of either color or one of them, offsides |
| `restart`, `set-piece` | every restart, or the set pieces alone |
| `corner`, `free-kick`, `penalty`, `throw-in`, `goal-kick`, `kickoff` | one kind of restart |
| `possession` | changes of possession |
| `halftime`, `fulltime` | half time and full time |

| Filter | Matches |
| --- | --- |
| `kind:goal,corner` | any of the kinds listed, by the same words |
| `team:Greens`, `team:left`, `team:right` | moments of a team, by a part of its name or by its side |
| `player:9`, `player:Okafor` | moments of a player, by shirt number or by a part of the roster name |
| `scenario:5_vs_5` | recordings of a scenario, by a part of its name, with spaces or underscores |
| `source:tournament` | recordings by source, `requested`, `game`, `challenge`, `recorder`, `live`, `tournament` or `unknown` |
| `tournament:Spring`, `challenge:corner` | recordings of a tournament or a challenge, by a part of its name |
| `match:sample-5v5` | one recording by identifier, or recordings by a part of the title |
| `date:2026-11-10`, `since:2026-11-01`, `until:2026-11-30` | recordings by the day they were made |
| `after:60`, `before:45` | moments by the match clock, in minutes, as `60:30` or in seconds as `90s` |
| `score:leading`, `score:level`, `score:trailing`, `score:2-1` | the standing of the team of the moment just before it, or the score at the moment, left first |
| `outcome:saved`, `outcome:wide`, `outcome:complete`, `outcome:won` | how a shot, a pass, a save or a tackle ended |
| `limit:20` | the most results, 50 by default and at most 1000 |

The outcome of a shot is `goal`, `saved`, `woodwork`, `blocked`, `redirected`, `keeper`, `wide`,
`over`, `stopped` or `none`, of a pass `complete`, `intercepted`, `out` or `stopped`, of a tackle
`won` or `lost`, and of a save `saved` or `scored`. An unknown filter or a value out of place stops
the search with a message that names what the query expects.

```text
goal team:Greens after:60
shot outcome:saved player:9
corner source:tournament since:2026-11-01
card -yellow
possession team:right score:trailing before:15
```

### Captions

Captions put the events of a match into short plain lines, such as `Goal, number 9 of Greens, 2 to
1`, timed to the events, on Watch and Play and for live sources. The setting Captions of the
events of the match in the settings panel turns them on and off, and Size of the captions picks
small, medium or large. The command palette turns them on and off too, and the browser keeps both
settings. Captions name goals with the scorer and the score, own goals, shots and headers at goal,
saves, blocks, the ball off a post or the bar, near misses, sliding tackles, fouls, cards,
offsides, corners, free kicks, penalties, throw ins, goal kicks, half time and full time with the
result. A player is named by shirt number and roster name as a player of the team, as in
`number 4 of Right`, and a team by its name alone, or as Left or Right when it has none. The
roster is the one the page dresses the players in, the team's current one for a team of the
registry and the one saved in the match otherwise.

A caption starts at the moment of its event, which for a touch of the ball is the estimated contact
inside its step, and stays four seconds or until the next caption starts, and at least a second and
a half. The view shows the newest three captions at once, centered above the controls and inside the
safe areas of the screen, and lower once the controls fade or in broadcast mode. Each caption that
forward play reaches also goes to a live region of the page, so a screen reader reads it once. A
live source captions its steps once they are three seconds old, which the view of a live source
stays behind anyway, so the outcome of every caption is settled.

Save captions in the Match menu of Watch saves the captions of the open recording as a WebVTT file
named after it, which a video player shows beside a video exported from the same recording. Every
caption is a message of the language files, such as `caption.goal` with its values `player`,
`team`, `left` and `right`, so the captions of the page and the file it saves follow the language
of the page, as [Languages](#languages) describes. The server and `cuju render captions` write
their captions in English. Each cue of a file, whether the page saves it or the server writes it,
holds its text on one line, a line break inside a team name becomes a space, and the characters
`&`, `<` and `>` are written as `&amp;`, `&lt;` and `&gt;`, so a video player shows a name as text
and a name never adds a cue or a tag.

### Agents

Agents reach the same index and captions without the page, and the server answers the same queries
with the same results.

| Route or command | Returns |
| --- | --- |
| `GET /api/search?q=QUERY&limit=N` | the results of a query |
| `GET /api/matches/ID/moments` | every moment of a recording with its line of text |
| `GET /api/matches/ID/captions.vtt` | the captions of a recording as WebVTT |
| `cuju render search QUERY [--limit N] [--json]` | the results under the identifier and title of each recording, or as JSON |
| `cuju render captions RECORDING [-o FILE] [--json]` | the captions of a recording or a `.cjr` file, as WebVTT or JSON |
| `cuju.render.search(query, limit=None)` | the results as a dictionary |
| `cuju.render.captions(recording, path=None)` | the cues, written as WebVTT to `path` when given |

Each result holds the recording as `match` with its `title`, `scenario`, `created` date and
`source`, the moment's `id`, `kind`, `step` and time `t` in seconds of the recording, the `seek`
time four seconds before it, the `clock` in milliseconds and the `minute` as minutes and seconds,
the `team` and `team_name`, the `player` with its `number` and `name`, the `score`, a plain line of
`text`, the `data` of the moment and the `url` of the page that opens Watch at the seek time. The
search also returns the `total` number of moments before the limit and the number of `recordings`
searched. A cue holds its `start` and `end` in seconds, its message `id`, its `params` and its
`text`.

The command prints each recording's identifier and title, then each of its moments with the
minute of the clock, the time `t` of the moment in seconds of the recording, its line of text and
the whole address that opens Watch at the seek time. The address names the server of the folder
when one runs, and otherwise port 8780, the port of `cuju render serve`, and the command then adds
that `cuju render open` with an address in quotes starts the server and opens it.

```console
$ cuju render search goal team:left
sample-5v5  Sample match, 5 vs 5
    2:54  t=9.7  Goal, number 3 of Lakeside United, 1 to 0
          http://127.0.0.1:8780/#match=sample-5v5&t=5.7
sample-11v11  Sample match, 11 vs 11
   12:46  t=42.6  Goal, number 10 of Harbour Rovers, 1 to 0
          http://127.0.0.1:8780/#match=sample-11v11&t=38.6
2 of 2 moments in 2 recordings
No server runs, and cuju render open with an address above in quotes starts one.
$ cuju render captions sample-5v5 -o sample-5v5.vtt
wrote sample-5v5.vtt
```

## Teams and requested matches

The page keeps a **team registry**, a list of agents that can play requested matches. A team is a
submission folder in the format of Kaggle's GRF competition, a folder whose `main.py` defines the
agent as its last function, together with any modules and weights that it loads. The built in AI of
GRF is always a team as well. A team is added on the page by choosing or dropping its folder, or
from the command line, and each team carries a **format**, `5v5` or `11v11`, its size for
competition.

```sh
cuju render team add path/to/submission --name "Rule-based baseline" --format 11v11
cuju render team list
cuju render play --left t-20261106-101500-3fa9 --right builtin --seed 7 --right-ability 0.4
cuju render play --left random --right random --scenario 5_vs_5 --pool t-20261106-101500-3fa9,builtin
cuju render team export t-20261106-101500-3fa9 --out baseline.zip
```

The team add command also accepts exported zip files, keeping the team name, format, control
settings and assets. The option `--name` can rename the import. From a folder it takes the files
themselves, leaves out `__pycache__` and every link, to a file or to a folder, and names each link
it leaves out in the log, so no file outside the folder reaches the team or its exports.

`cuju render team show ID` prints a team with its control, and `cuju render team set ID` changes
its name with `--name`, its format with `--format` and its control with the options that `add`
also takes. `--players` sets the count of controlled players, `--assignment` takes `dynamic` or
`fixed`, `--selection` takes the fixed players as indices of the formation or as roles, such as
`1,2,3` or `CB,CM`, and makes the assignment fixed, `--goalkeeper` takes `agent`, `builtin` or
`scenario`, and `--action-set` takes `default` or `v2`. A change keeps every setting it leaves
out, and dynamic assignment drops the selection. The option `--json` of `list`, `show`, `add` and
`set` prints the team or the list as the server returns them, and `remove` deletes a team's
folder and says so. A new team takes the next of eight kits in turn, the one that fewest teams of
the registry wear, so teams added one after another differ on the pitch.

The command `cuju render challenge` plays a challenge headless with a team, or benchmarks several
teams on several challenges, as described under Challenges, and `cuju render challenge list` names
them all.

`cuju render play` plays the match in its own process and prints the path of the recording it
saved, or with `--json` one line of JSON with the recording's identifier `match` and its `path`.
In a terminal a line on standard error follows the share of the match played, and a script or a
pipe reads the result alone, since whatever a submission prints goes to standard error as well. A
submission that fails ends the command with one line that names the team and the reason, while
`cuju.render.play` raises the submission's own error. The recording appears under Recordings,
with the source `requested_match` in its provenance. The list of requested matches on the Matches
page holds the requests of the server, those made on the page or through `POST /api/requests`, so
a match of the command line shows under Recordings alone.

A match requested on the page plays in a process of its own on the CPU and becomes a recording in
the library. The play command also takes a device. Each submission runs from its own folder,
with its own modules, as on Kaggle. Every Python process that the renderer starts, for a match, a
game, a tournament, a challenge, an export or the server, runs with `-P` on Python 3.11 and later,
which keeps the renderer's folder off its path of modules, so folders such as `teams` and
`requests` never import as packages, and on Python 3.10 it starts in the empty folder `run` of the
renderer's folder instead. Full matches follow the format of the team, five or eleven a
side. Academy scenarios accept either format when the requested players exist on that side.
The default scenario is the Kaggle competition scenario. The built in AI plays any scenario.

Each side of a requested match takes an **ability**, a number from 0 to 1 that sets how well the
built in AI plays the players it controls on that side, which is GRF's team difficulty under
another name. It steers the whole team of the built in AI and, in a scenario where a submission
controls one player of its side, that player's teammates as well. A side left alone plays the
scenario's own difficulty, and the recording keeps the ability that each team played with. The
options `--left-ability` and `--right-ability` of `cuju render play`, the argument `ability` of
`cuju.render.play` and the Ability controls on the Matches page set it. The page enables a slider
for each side with a checkbox, in
steps of 0.05, and leaving it unchecked keeps the scenario value. The same controls on Play
set the ability of the teammates and opponents there.

Each submission sets its count, assignment, player selection, goalkeeper and action set in the
add form or the Identity section of the editor. The count runs from one to every controllable
player of the scenario. A requested match checks both sides separately and reports the team,
scenario and conflicting setting when they cannot play together. A smaller scenario refuses an
excess count rather than reducing it. Exported teams carry these settings with them. An import
keeps the control settings from its archive unless the user edits the control form. Earlier
teams with only a count and goalkeeper setting load with the same control as before.

Dynamic assignment gives GRF the requested count of agents. With fewer agents than controllable
players, GRF switches them among players near the ball. One dynamic agent is the Kaggle case.
With every controllable player, each agent keeps a player when both sides use full counts or AI.
The scenario goalkeeper setting lets GRF decide whether the keeper can be selected. The agent
setting requires a controllable keeper, and leaves selection to GRF in dynamic assignment.

Fixed assignment takes a list of player indices starting at zero, or GRF roles, in agent order.
The roles are GK, CB, LB, RB, DM, CM, LM, RM, AM and CF. Repeated roles select successive players
of that role in lineup order. The form shows the default lineup for the format. Its player buttons
show lineup indices and roles and select fixed players in agent order. The match checks against
the actual scenario lineup, which may differ. A missing role, repeated index or
uncontrollable selected player gives an error. Agent goalkeeper control requires the keeper in
the selection. Builtin goalkeeper control requires fixed assignment and leaves the controllable
keeper outside the selection. Scenario goalkeeper control in fixed assignment requires a keeper
that the scenario makes uncontrollable.

Fixed assignment gives the engine every controllable agent of the side. On each step the runner
reads the active player of every agent from its raw observation. It sends the observations of the
selected players to the submission in the chosen order, and routes each returned action to the
agent holding that player. Agents holding players outside the selection send builtin AI, 19.
GRF clears the selected players of both sides at set pieces when either side uses dynamic
selection. A side with every controllable agent keeps every controllable player under control,
while the agents holding those players may change. The runner follows those changes on each step.
During a handover an agent may briefly report minus one as its active player. For that step the
fixed side uses the built in AI for all its players and skips the submission call. Other missing
selections receive replacement agent columns, and the submission is called in selected order even
when two agents report the same player. The built in AI then replaces its actions in the columns
of missing selected players.

The default action set has 19 actions. The v2 set adds builtin AI at index 19, so a submission may
hand any selected player to the AI for one step. Each side keeps its own action set, including
its range checks and negative indices, when the other side needs v2. Every player left to the
AI uses the ability of its side. A fixed team may meet a dynamic team, a single agent or the AI.

The renderer includes six training scenarios from GRF MARL by Light MALib. Each format has easy,
medium and hard variants, with team difficulties of 0.05, 0.6 and 1.0. They take 3001 calls to
`step`, with the second half at step 1500, swap the formations by episode parity and leave both
goalkeepers uncontrollable. Their names are shown below.

```text
benchmark_full_game_5_vs_5_easy
benchmark_full_game_5_vs_5_medium
benchmark_full_game_5_vs_5_hard
benchmark_full_game_11_vs_11_easy
benchmark_full_game_11_vs_11_medium
benchmark_full_game_11_vs_11_hard
```

Pass their names to `cuju.render.play` or to the server's match and game requests. They are
available to the renderer through scenario files and the bundle cache. The scenario lists on Matches
and Play hold the full matches, `1_vs_1_easy` and the academies, and leave out these six and
GRF's example scenario `test_example_multiagent`, which stay playable from Python and the API.

The add form also accepts a single `main.py` or a `.zip` or `.tar.gz` archive. Uploads allow up to
100 MB,
with at most 10000 files and 500 MB after unpacking. The submission needs `main.py` at its root.
A tar archive may be plain or compressed with gzip, bzip2 or xz. The server counts the entries of
a zip archive from its bytes before it opens it, and counts the members of a tar archive and their
sizes as it reads them, so an archive past a limit is refused at once, however small it is. An
archive with a file or folder whose name opens a device on Windows, such as `nul`, `con.txt` or
`COM1.log`, or whose name ends in a dot or a space, is refused on every system, so a submission
imports alike everywhere.

A submission is Python code that runs with the permissions of the server's user, so only trusted
code belongs in the registry, and a submission that imports Kaggle's helpers needs the package
`kaggle_environments` installed beside cuju. A submission that fails ends only its own match, and
the page shows its error in one line. The variable `CUJU_RENDER_DEBUG`, set to `on` for the server
or the command, also prints the full traceback of a policy's error to standard error, in requested
matches, games and challenges alike. A match that runs past 30 minutes ends, and the page cancels a
waiting or running match on request.

### Matches drawn at random

A side of a requested match may be drawn at random. On the Matches page the list of each side
starts with Random team, and on the command line `--left random` or `--right random` stands in for
a team identifier. When the request is made, the server draws a team for each random side from
the **pool**, the teams that the person ticks under Pool of the draw on the page or names with
`--pool` as identifiers separated by commas, and every team of the registry, the built in AI
among them, when no pool is given. A team takes part in the draw of a side only when it can play
that side of the scenario, so its format must match the scenario's and its control settings must
fit the players of that side. In the drill `academy_3_vs_1_with_keeper`, for example, the left
side holds four controllable players and the right side two, so a team that controls three
players can be drawn for the left side alone. A random side that no team of the pool can play is
refused with the message `server.draw.left` or `server.draw.right`, which names the scenario.

Two sides that are drawn, or a drawn side that meets a named team, take different teams whenever
another team of the pool fits. A pool with a single team that fits plays that team on both sides.
Let a team meet itself on the page, or `--same-team` on the command line, lets the draw pick one
team for both sides however many fit, which suits a team that should play against its own copy
now and then.

The scenario can be drawn too. The scenario list of the page offers Random scenario first
whenever two or more scenarios fit, and `--scenario random` asks for it on the command line. The
draw then picks one of the scenarios that the page lists, the full matches, `1_vs_1_easy` and the
academies, among those where each side has a team that can play it. The six training scenarios and
GRF's example scenario stay out of the draw. When both the scenario and a side are random, the
scenario comes first, and the teams then fit it. A request where no listed scenario has a team for
each side is refused with the message `server.draw.scenario`.

The seed of the request decides the draw, the same seed that the match plays with. A request
without a seed takes one that the server draws, as always, and the draw then follows it. The same
seed and the same pool always draw the same teams and scenario, on every computer, so the draw
of a match is repeatable from its seed. A team added to the registry or removed from it changes the
draw of a request without a pool, since the pool is then the whole registry at the time of the
request. `cuju render play` prints the teams, scenario and seed that it drew before the match
plays, and with `--json` adds `left`, `right`, `scenario`, `seed` and `draw` to its answer. The
recording keeps the draw in its provenance, beside the teams that played.

### Teams and matches over HTTP

Scripts and agents reach the registry and the requested matches through the routes of the server,
which pass the same checks of host and origin as every other route.

| Route | Body | Answer |
| ----- | ---- | ------ |
| `GET /api/teams` | none | every team of the registry, the built in AI first |
| `POST /api/teams?name=NAME&filename=FILE&format=5v5&control=CONTROL` | the bytes of a `main.py`, a `.zip` or a `.tar.gz` | the new team, with 201 |
| `PATCH /api/teams/ID` | `{"name": "Visitors", "format": "5v5", "control": {...}, "style": {...}}`, each field optional | the changed team |
| `POST /api/teams/ID/duplicate` | none | the copy, with 201 |
| `DELETE /api/teams/ID` | none | 204 once the team is gone |
| `PUT /api/teams/ID/model?joints=JOINTS` | the bytes of a skinned `.glb` of at most 30 MB | the changed team, its model checked as an upload of the team editor |
| `PUT /api/teams/ID/images/SLOT` | the bytes of a PNG, JPEG or WebP image, or the JSON of an editor document for a slot ending in `-edit` | the changed team |
| `PUT /api/teams/ID/sounds/KIND` | the bytes of an Ogg, MP3 or WAV sound of at most 2 MB | the changed team |
| `PUT /api/teams/ID/clips/NAME?joints=JOINTS` | the bytes of a celebration clip, a `.glb` of at most 10 MB | the changed team |
| `GET /api/teams/ID/model`, `images/SLOT`, `sounds/KIND`, `clips/NAME` | none | the file |
| `DELETE /api/teams/ID/model`, `images/SLOT`, `sounds/KIND`, `clips/NAME` | none | 204 once the file is gone |
| `GET /api/requests` | none | every requested match with its `state`, `progress`, `match` and `error` |
| `POST /api/requests` | `{"left": "ID", "right": "builtin", "scenario": "5_vs_5", "seed": 7, "ability": [null, 0.4], "pool": null, "same_team": false}` | the new request, with 201 |
| `DELETE /api/requests/ID` | none | 204 once a waiting or running request is cancelled |

`JOINTS` is the JSON of the bone each of GRF's joints follows, such as `{"body": "Hips"}`, encoded
for the address, and an empty mapping maps the bones by their names. `SLOT` is one of
`shirt-front`, `shirt-back`, `sponsor-1` to `sponsor-4` and each of them followed by `-edit`, and
`KIND` one of `goal`, `shot`, `pass`, `tackle`, `save`, `kick`, `celebration` and `chant`. A sound
is read past its first bytes, so a WAV file holds a format chunk and samples, an Ogg file starts
with a page of Vorbis, Opus or FLAC and an MP3 file holds a frame, and a file that only starts
like a sound answers 400 with the message `server.teams.sound_damaged`.

`CONTROL` is the JSON of a control, encoded for the address, such as
`{"players": 2, "assignment": "fixed", "selection": [1, 2], "goalkeeper": "scenario", "action_set": "default"}`,
and the fields it leaves out take their defaults. A request goes from `queued` to `running` and then
to `done`, with the identifier of its recording in `match`, or to `failed`, with the reason in
`error`. A refused field answers 400 with the reason.

A request draws a side at random when `left` or `right` is `random`, and draws its scenario when
`scenario` is `random`, as Matches drawn at random describes. `pool` is the list of team
identifiers that a random side draws from, or `null` for every team of the registry, and
`same_team`, true or false, lets one team play both sides. The new request answers with the teams
and the scenario drawn in `left`, `right` and `scenario`, and with `draw`, which names the random
sides as `sides`, a pair of true or false, whether the `scenario` was drawn, the `pool` and
`same_team`. A request without anything random has `draw` set to `null`. A pool that is no list of
identifiers is refused with `server.draw.pool`, a team of the pool outside the registry with
`server.teams.unknown`, and a `same_team` other than true or false with `server.draw.same_team`.
To retry a drawn request, a script sends `random` again for each random part, with the same pool,
`same_team` and seed, and to draw again it leaves the seed out.

### Multi agent teams

A team trained with one network per player, such as GRF_MARL or TiZero, becomes a submission folder
whose `main.py` answers Kaggle's multi agent form. The observation `obs['players_raw']` then holds
one raw observation per controlled player, in agent order for dynamic assignment or selected
player order for fixed assignment, each with the
team as `left_team` and its own player as `active`, and `obs['controlled_players']` holds their
count. The agent returns one action per controlled player in the same order, each an index of the
action set, so a team of five that controls 4 players returns four actions and a team of eleven
that leaves its goalkeeper to the built in AI returns ten.

```python
import torch

weights = torch.load('weights.pt', map_location='cpu', weights_only=True)
networks = build_networks(weights)


def agent(obs):
    return [act(networks, raw) for raw in obs['players_raw']]
```

Here `build_networks` and `act` stand for the architecture and inference code of the training
project, which travel with `main.py`. Build the networks once when the file loads, put them in
evaluation mode and run inference without gradients. Reproduce the feature encoder, normalization,
available action masking and recurrent state handling used in training. A recurrent policy needs
separate memory for each controlled player and must clear it at the start of each episode.
A single controlled player may return one action, while several return a list of the same length
as `players_raw`. Keep `agent` as the last callable defined or imported in `main.py`.

The weights travel best as plain tensors, loaded with weights only enabled. A checkpoint saved
as a pickled module converts once inside a Docker container with the project code, then saves
its state dictionary as tensors. The submission builds the network and loads those tensors.
For one network per player, index the networks by the active player rather than the current
position of an observation in the list, as the following example does.

```python
import torch

weights = torch.load('weights.pt', map_location='cpu', weights_only=True)
networks = build_networks(weights)


def agent(obs):
    return [act(networks[raw['active']], raw) for raw in obs['players_raw']]
```

For GRF MARL training scenarios, choose fixed assignment, ten players for eleven a side or four
for five a side, indices one through ten or one through four, scenario goalkeeper control and
the action set used in training. For the Kaggle scenario with ten outfield players, choose the
builtin goalkeeper setting instead. A role selection such as CB, CB, CF keeps the first two
centre backs and the centre forward in that order. The checkpoint must use the same observation
features and action set as the submission.

### Customization

Each team has customization of its own, which the renderer alone draws, so a customized team plays
exactly
the matches it would play in its plain kit. The editor on the Teams page groups the look into nine
sections, identity, kit, roster, model and colors, fans, celebrations, sounds, sponsors and export,
with a preview of a player that idles, walks or keeps goal. The section menu and its previous
and next buttons move between sections. Changes wait for Save, except artwork, sound and clip
uploads and removals, which save immediately. The identity holds the team name, its format and a
badge of up to three characters.

The look starts from the **player model**, which is GRF's own skinned player by default. A team may
instead take one of the characters that ship with the renderer, the skeletons and adventurers of Kay
Lousberg's KayKit packs and KayKit's mannequin, or a rigged model of its own, as described under
Custom models, and each player of the roster may take a model of its own in place of the team's.

Every model wears the team's kit. The editor reads the colors present in a model other than GRF's,
up to twelve by the share of its surface, and finds the part of the figure that each one covers from
the names of the model's meshes and materials, such as body, arm, leg, cape, hood, hat or helmet on
KayKit's characters, or shirt, pants and boots on an uploaded model. The heaviest color above the
legs takes the shirt color of the kit, the other colors of the body, capes, hoods and hats take the
trim, the upper legs take the shorts and the lower legs and boots the socks. Skin, bone, faces,
eyes, hair, metal and small accents keep the model's own colors, and a model whose names tell
nothing takes the shirt, shorts, trim and socks by surface share. Each mapped part keeps the
shading painted into the model. The goalkeeper wears the same parts in the goalkeeper's colors, and
when the right team plays in its away kit, its players wear the away kit's colors.
The viewer compares the shirts, patterns and shorts of both sides and chooses an away kit for
the right side when they clash. It tries the team's swapped kit first, then alternative sash
and plain kits, keeping the first suitable option or the most distinct available option.
Default goalkeeper kits are separated when needed, while an explicit goalkeeper kit is kept.

Under Model and colors, a swatch for each color shows the color drawn and a label, the part of the
kit that it follows, Custom for a color of the team's own, or Model color. Picking a color makes it
the team's own, Reset returns it to the kit, and Reset all to the kit clears every color of the
team's
own. The box Dress the model in the kit colors turns the kit mapping off and on for that model. A
swatch that is focused, picked or pointed at blinks its parts on the preview, and the preview shows
the model whose colors are listed, a player who wears it, so the Colors of list, which appears when
the roster uses several models, and the preview always agree. The team's own colors save with the
team and travel in its export.

On GRF's model, the team chooses the colors of its shirt, shorts and socks, a pattern for the shirt
among plain, stripes, hoops, halves, a sash and checkers, the colors of the goalkeeper's kit, a
badge of up to three characters and the color of the numbers. The roster lists five or eleven
players by the team's format, each with a name, a number from 0 to 99, a skin tone, a hairstyle and
a hair color, and each left alone keeps the look that GRF gives that position. The front and back of
the shirt are flat images, painted in an editor on the page with brushes, shapes, text and placed
images, and laid over the colors and the pattern. The pattern, the artwork, the badge and the
numbers
dress GRF's model, and the other models wear the kit's colors as described above.

Every other model, KayKit's characters and a team's own model among them, wears each player's number
on its back as GRF's model does, in the color of the numbers, following the upper back, sized and
placed from the model's torso in GRF's standing pose. A model whose torso is too small to hold a
number shows none. Clearing Shirt numbers on the back, beside the colors of each model in Model and
colors, turns the numbers off for that model alone, for a model where they do not fit, and the
choice saves with the team as `hidden_numbers` in its style.

A goal brings the scorer's celebration, picked from the moves that the team ticks, or from every
move when it ticks none, and each player of the roster may take a celebration of its own. The moves
include arms up, a knee slide, a jump and punch, dances, the airplane, a backflip, a salute, the
shush, heart hands, the robot, a bow and the worm, and on KayKit's characters the clips of KayKit's
animations, such as cheering, waving to the fans, jumps, taunts, push ups, an air punch, a forward
roll and sitting or lying on the grass, together with the clips of a custom model and the
animations of the team's own celebration clips, as described under Celebration clips. Each move
plays in the editor before it is chosen.

A team may also bring sounds of its own, in Ogg, MP3 or WAV files of up to 2 MB, for eight moments,
a goal, a shot, a pass, a tackle, a save, any kick, the scorer's celebration and a chant that the
fans sing now and then in every arena. The page plays each one from where it happens, cut to four
seconds and brought to the level of the other sounds on the page. A sound is stored as soon as it is
chosen, and the match on the page plays the new sound from then on, a sound replaced under the same
moment included. `cuju render team sound ID goal goal.ogg` gives a team the same sound from the
command line, and `--remove` in place of the file takes it away.

A team also holds up to four sponsors, wide images made in the same editor from uploaded images and
drawing, which the advertising boards around the pitch show while the team plays. Boards alternate
between the sponsors of the two teams and fall back to GRF's boards. The fans of a team wear one to
four colors of its choosing, its kit's colors by default, and fill the stands behind its goal and
its half of the side stands.

#### Surprise me

The Identity and Kit sections of the editor open with a **Surprise me** panel, a button with a Seed
field and a Style choice beside it. The button makes a whole new look for the team and fills the
name, the badge, the kit's pattern and colors, the goalkeeper's kit, the color of the numbers, the
colors of the fans and the names of the roster. Everything it fills is an unsaved change like any
other edit, so Save keeps it and Cancel or leaving the team discards it. The format, the control,
the models, the looks and numbers of the roster, the celebrations, the sounds and the artwork stay
as they are. Enter in the Seed field presses the button, and the focus returns to the button after
each press, so the panel works from the keyboard alone. A screen reader hears the new name and the
line under the panel after each press, and the same after Surprise me in the form that adds a
team.

A seed is any text or number. With the Seed field empty, each press draws a fresh seed of six digits
and names it in the line under the panel, together with the kit style and the color scheme it used.
The same seed and style make the same team again on every machine, so typing that seed back brings
the team back. The name and the roster follow the seed alone, so trying the styles on one seed keeps
the name and changes the kit. Any style lets the seed pick one, and makes the same team as that seed
with the style it picked.

The styles set the pattern and how the colors relate.

- **Classic stripes**, a striped shirt with a second color from the scheme or a white, cream, black
  or charcoal stripe.
- **Retro hoops**, hooped shirts in softer colors, often with cream.
- **Sash**, a band across the chest in a strong second color.
- **Halves**, a shirt split in two colors of the scheme.
- **Checkers**, a checkered shirt in two colors or two shades of one.
- **Minimal**, a plain shirt with shorts and socks of the same color and a quiet trim.
- **Bold neon**, a plain shirt in a neon green, pink, orange, cyan, lime, aqua, purple or coral,
  with black shorts.

The colors come from color theory in the CIE LCh space. The shirt takes a hue, and the second color
takes a complementary, split complementary, analogous or triadic hue, or the same hue in another
lightness for a monochrome scheme. Each team the button makes passes these checks.

- The numbers have a WCAG contrast ratio of at least 3 to 1 on the shirt and on the goalkeeper's
  shirt.
- The pattern differs from the shirt by a CIEDE2000 of at least 25, and the shorts by at least 20,
  apart from Minimal, which wears shorts of the shirt's color.
- The goalkeeper's kit differs from the outfield kit, from the outfield kit with its colors swapped,
  from the default goalkeeper's kit and from every common kit below.
- The outfield kit stays clear of the built in AI's blue kit, the default red kit and plain red,
  white, blue, black, yellow and green kits, by the measure the viewer uses to choose an away kit.

A seed whose draws all fail these checks takes a safe purple kit with a teal goalkeeper, which
passes them.

Names come from word lists of invented places, adjectives, creatures and club words, such as
Harbor Herons FC, Northgate United or Crimson Comets, and the roster takes distinct surnames. The
badge holds the initials of the name, up to three, leaving out FC and AFC.

The form that adds a team on the Teams page has a Surprise me button under the name. It fills the
name with a new one and shows the kit beside the button, and the team added wears that kit, with a
badge from the name it is given. Plain kit drops the generated kit and keeps the name.

Scripts and agents that drive the page call `cuju.surprise`, a function of the page object
`window.cuju`. It takes an object with `seed`, `style`, `format` and `apply`, each optional. The
`style` is one of `any`, `stripes`, `hoops`, `sash`, `halves`, `checkers`, `minimal` and `neon`,
`format` is `5v5` or `11v11` and sets the length of the roster names, and `apply` set to `true`
fills the editor open on the Teams page as the button does, and throws while no editor shows
there. The seed is text or a number, and any other seed throws. The function returns the seed,
the kit style, the scheme, the name, the badge and a `style` that `PATCH /api/teams/<id>` takes
as it is.

```js
const team = cuju.surprise({ seed: 'harbor', style: 'stripes', format: '5v5' });
// team.name, team.badge, team.style.kit, team.style.goalkeeper, team.style.number
await fetch(`/api/teams/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name: team.name, style: team.style }),
});
```

The generator is the module `js/teams/surprise.js` of the page, which also runs in Node where the
`three` package is installed, since it reads the kit helpers of `js/players/kits.js`.

### Custom models

A custom model is a binary glTF 2.0 file, `.glb`, with a skinned mesh, up to 30 MB, holding all its
data within the file. The page maps the joints of GRF's skeleton onto the bones of the model, by
name where they match and by the conventions of common rigs such as Mixamo's, and the mapping
remains editable. Only the pelvis, GRF's joint `body`, is required, so a simple rig whose arm is one
bone maps its shoulder and leaves the elbow out, and the bones without a joint follow their parents.

The renderer drives each mapped bone by the rotation of its joint relative to GRF's rest pose,
applied to the bone's own rest pose, and keeps the bone lengths of the model, so a model of other
proportions or another rest pose moves as GRF's player does without stretching. The pelvis follows
GRF's pelvis, scaled to the model's own height.

### Celebration clips

A team may bring celebrations of its own as clips, binary glTF 2.0 files, `.glb`, that each hold
one or more animations of a skinned skeleton. The Celebrations section of the editor lists the
team's clips below the moves, and Upload a clip, or a file dropped beside it, adds one. Each
animation of a clip joins the moves of the section under its own name, marked as a clip of the
team, where Play previews it on the team's model and a tick puts it among the team's celebrations.
The roster offers the same animations, so each player may take one as a celebration of its own.
Clips save immediately, as sounds do, and removing a clip takes its animations out of the team's
celebrations and the roster.

A clip plays on every model of the team, GRF's player, a shipped character or a custom model. The
page maps the joints of GRF's skeleton onto the bones of the clip as it does for a custom model, by
name and by the conventions of common rigs such as Mixamo's, and Joint mapping under each clip
shows that mapping and lets it change. Save mapping keeps a mapping chosen by hand, and Map by bone
names returns to the mapping by names. The pelvis, GRF's joint `body`, is required, and a clip
whose bone names leave the pelvis unmapped joins the moves once Joint mapping names it.

The page reads each animation thirty times a second on the clip's own skeleton and gives every
mapped joint the rotation of its bone relative to the bone's rest pose, the inverse of the way a
custom model follows GRF's joints, and a joint without a bone keeps its rest turn from its parent.
The poses then drive the team's model as the built in moves do, at the model's own bone lengths,
so a clip made for a tall or a short figure suits every player. The height of the pelvis above
the floor is scaled from the clip's figure to GRF's player, so crouches, kneels and jumps keep
their depth.

Movement of the whole figure stays near the scorer. A clip whose pelvis ends more than a quarter of
a meter from where it began walks or runs, and that steady travel is taken out, so the clip plays
in place and loops smoothly. The movement that remains stays within a meter and a half of the
spot, and the scorer stays inside the touch lines and the goal lines. Teammates who join the move,
and players on the podium of the show after the match, keep to their own places. A clip loops for
as long as the celebration lasts, and the first thirty seconds of a longer animation play.

A clip holds at most 10 MB, and a team holds at most 16 clips and 40 MB of them. The server checks
each upload as it checks other uploads, a binary glTF 2.0 file whose header and chunks fit
together, with a skin, at least one animation and every buffer and image inside the file. A file
that requires Draco or meshopt compression or Basis Universal textures is refused, since the page
reads none of them. The page names a clip after its file, in lowercase letters, digits and
underscores, so a clip of the same file name replaces the earlier one. The clips travel in the
team's export, in the folder `clips` of `cuju-team`, and an import checks each one again.

The animation packs of KayKit's Character Animations that ship with the renderer, in the folder
`assets/animations` of the page, upload as clips as they are, which makes a quick first test.

#### Making a clip in Blender

Blender, free from blender.org, turns animations of other formats into clips. Characters and
animations from Mixamo suit it well, since the page knows Mixamo's bone names, and the same steps
from the second onwards serve an FBX file of any other source.

1. On Mixamo, choose a character and an animation, and download it as FBX Binary, With Skin. In
   Place keeps a walk or a run on the spot, and the page takes steady travel out in any case.
2. In Blender, start a General file, delete the default cube, camera and light, and choose File,
   Import, FBX on the downloaded file. Blender keeps Mixamo's centimeters as a scale on the
   armature, and the page reads centimeters and meters alike.
3. For a clip of several animations, import each further file of the same character in turn.
   Keep one armature with its mesh and delete the others, give the remaining armature each
   action in turn in the Action Editor of the Dope Sheet, and press Push Down after each one, so
   every action sits on a track of the Nonlinear Animation editor. A clip of one animation needs
   none of this.
4. Name each action as the editor should show it, such as `Victory dance`, in the Action Editor.
5. Choose File, Export, glTF 2.0. Set Format to glTF Binary, keep Skinning checked under Data,
   and under Animation keep Animation checked with its mode set to Actions or NLA Tracks, so every
   action leaves as an animation of its own.
6. Upload the `.glb` file under Celebrations, open Joint mapping when a joint looks wrong, and
   press Play on each new move to preview it.

A clip needs its mesh as well as its bones, since a skin binds the two, and any mesh skinned to
the armature serves. The page plays the bones alone, so the mesh of the clip stays out of sight
and the team's own model performs the move.

### Presentation packages

A team may also carry a presentation package, the folder `presentation` inside its `cuju-team`
folder, which decides how the team looks, moves and sounds beyond its kit, model and clips. A
package brings models by role and shirt number, clips by semantic role that can drive the whole
figure in place of GRF's joints, sockets, attachments, persistent behaviours such as spins,
hovers and gaze, material looks, reflexes that answer the match's events, and an optional worker
module that runs sandboxed with no network. The page reads the package when it draws the team,
the server checks it on import, export and every request, and the engine never reads it, so the
match plays the same with or without one. Contract 1.1 adds particles, trails, decals, team
lights, custom shaders, team passes, music stems, sound processors on governed buses, camera,
time and environment moments, overlay slots, reach and the bend of the ball through each contact.
[Team presentation packages](presentation.md) is the reference of the contract, with the manifest,
the events, the worker's messages, the budgets, the safety rules and the pack tools for authors.
The settings panel chooses the team whose presentation each side draws and the level of team
music.

### Export

A team leaves the page as its submission folder, a zip archive with `main.py` and the submission's
files at its top, as Kaggle reads them, and a folder `cuju-team` that holds the team's format,
style, roster, images, sponsors, model, celebration clips and presentation package. Kaggle ignores
the extra folder, and a submission folder that holds one brings the whole look back when it is
added to a registry again, on the page or from the command line, each file checked as an upload
is. The built in AI exports its look alone.

An import keeps every file of `cuju-team` that the page leaves unread, such as notes, source artwork
or a folder of drafts, so these files travel on with the next export. Each image, sound, model and
clip that the page reads is checked as an upload is, and a file that fails its check stays in the
folder under its own name followed by `.rejected`, which the page never reads, so the team plays
without it and its bytes remain for its owner. A file whose name is the name of such a file in
another case or with more after the slot, such as `Shirt-Front.png`, `shirt-front.x.png` or
`clips/wave.GLB`, is set aside as well, and the server serves each image, sound, model and clip of
a team by its exact name alone and never through a link, on every system, whether or not the
system finds names whatever their case. A link, which could point outside the team's folder,
and a file whose name opens a device on Windows, such as `con.txt`, are removed. The server's log
names every file set aside or removed and the reason. The team takes the identifier of its new
folder whatever its `team.json` says, values of the wrong type in that file fall back to the
defaults, and an import that fails at any step removes the folder it began, so the registry lists
only whole teams. The name in a team file, imported or edited by hand, keeps the characters that
print, and the escapes of a terminal, line breaks and the marks that turn the direction of text
become spaces, so `cuju render team list` prints the name as the page shows it.

Duplicate saved team, in the same section, makes a new team of the registry from a submission
team as it was last saved, with the submission's files, its format, controls, style, roster,
images, sounds, model and clips, under the team's name followed by `copy`. The two teams change
independently from then on, so a copy is a starting point for trying other controls or another look
while the original keeps playing as before. Changes that wait for Save stay out of the copy, so
saving first carries them over. The built in AI is one shared entry of the registry and offers
Export alone.

## Page layout

The page holds nine pages, chosen from the bar along its top. The cuju logo at the left of the bar
opens Home, and tabs open Watch, Play, Recordings, Matches, Tournaments, Teams, Field and Help.
Each tab shows a symbol beside its name, a television for Watch, a controller for Play, a box of
files for Recordings, crossed swords for Matches, a trophy for Tournaments, a shirt for Teams, a
plot of land for Field and a question mark for Help. On a screen of middle width the tabs show
their symbols alone, and the tooltip of each names the page and what it holds. Commands, a
magnifying glass, Settings, a gear, and Fullscreen, four corners, sit at the right end of the bar.
On a narrow screen the tabs fold into one menu of pages, each entry with its symbol and its name.

### Symbols

The controls of the page show symbols wherever a symbol reads clearly, from one set of icons, the
Lucide icons, drawn in the color of the text so that they follow the theme. A control that shows
its symbol alone keeps its name. The pointer resting on it shows the name as a tooltip, keyboard
focus shows the same tooltip beside it, and a screen reader reads the name, so every control reads
the same by mouse, by keyboard and by ear, in every language of the page. The guides and the tour
name each control by that name.

The symbols that recur across the pages are these.

| Symbol | Name |
| --- | --- |
| a triangle | Play, Open, Start, Watch a match |
| two bars | Pause |
| a cross | Close, Cancel, Remove an entry, Not now |
| a tick | Got it, Apply |
| a pencil | Rename, Edit, the name of an entrant |
| the letter i in a circle | Details |
| a folder with an arrow | Move to a folder |
| a folder with a plus | New folder |
| a waste bin | Move to Trash, Remove, Delete |
| an arrow turning back | Restore, Reset |
| two arrows in a circle | Refresh, Try again |
| an arrow looping round | Repeat, Run again, Replay |
| an arrow down onto a line | Export, Download, Save the report |
| an arrow up from a line | Import, Upload |
| two sheets | Copy, Duplicate |
| a floppy disk | Save |
| two dice | Draw a seed, Surprise me, Random team, drawn at random |
| a plus | Add |
| chevrons up and down | Move earlier, Move later |
| arrows left and right | Back, Next |
| a square | Stop, Cancel a run |
| a trophy | Trophy ceremony, Match summary |
| a medal | Leaderboard |
| a robot | Run headless |
| a gauge | Speed |
| a calendar | Date |
| lines of falling length | Sort |
| a funnel | Show, the state of requested matches |
| a shirt | Team, Use the kits saved in the match |
| a plot of land | Scenario, GRF classic pitch |
| a folder | Folder, Open a file |
| a star | Favorites |
| a keyboard | All shortcuts |
| a screen with an arrow down | Install cuju as an app |
| a terminal | the command `cuju render app` |
| a screen | Made in this browser |
| a server | Made by the server |
| a sign of warning | A name that repeats another |

The states of requested matches, tournaments and lessons show as symbols too, a clock while a
request waits, a turning wheel while it runs, a ticked circle once it is done, a crossed circle
when it failed and two bars while it stands still, each with its name as its tooltip. The choices
of the Field page show the time of day as a rising sun, a sun, a setting sun and a moon, the
weather as a sun, a cloud, rain, a storm, snow and haze, and each way of mowing as its pattern.

The lists that choose a value keep the value in words, and the name of the list shows as a symbol
before it. Speed on Watch, the filters and the order of Recordings, Matches and the search of
moments show a gauge, a folder, a plot of land, a shirt, a calendar, a star, a clock or lines of
falling length, and the View list of Recordings shows a box for the library and a waste bin for
the Trash. The tooltip of each list names it, and a screen reader reads the name with the value,
such as Sort, Newest first. The settings show a symbol beside the words of each choice whose
symbol reads clearly, such as a route for Ball trail, a television for Broadcast mode, two people
for Lineups, a popper for Celebrations, a snail for Slow motion in replays, a mouse for Capture the
mouse, a palette for Theme and the symbol of languages for Language.

Lines of state show their symbol before their words. The line of progress of Export video opens
with the symbol of the export's state, its notes show a screen when the browser makes the video
and a server when the server makes it, and Install the app on Help shows a ticked circle for an
installed app and a terminal before the command `cuju render app`. On Tournaments, a name of an
entrant that repeats another shows a warning beside the field and in the review, and the note that
proposes a free name, such as Rex 2, shows a pencil. The card on Home that offers the app shows a
screen with an arrow down, Install with its words and Not now as a cross.

Some controls keep their words beside the symbol, where the words are the content or a symbol
alone could be read two ways. The main action of a page keeps its words, such as Play on Play,
Play match on Matches, New tournament and Start tournament on Tournaments and Take the tour on
Help. Deleting for good keeps its words, Delete permanently in the Trash, Delete for a team, a
preset or a tournament. The menus of a paused game and the card at the end of a game keep their
words, since Quit, Quit to Home and Home differ in what they keep. The buttons of the touch
controls keep the short labels of Gameplay Football, as GRF players know them.

The lists of Source and Result on Recordings and of Kind, Score and Source in the search of
moments keep the words of their names, since no symbol names a source, a kind of moment or a
result in one reading. Restart transitions, 2D view, Motion and the levels of sound keep their
words alone in the settings for the same reason. The words stay where a button names its own
choice, as Use the 2D view and Keep 3D, Use low quality and Keep this quality, Map by names, the
offers of the tour and the lessons, Show more on Matches and No more tips. Install on the card keeps its words
as the action of the card, and Import a language file keeps them beside its symbol, since it
stands alone while English is the only language.

Commands, or Ctrl K on any page, opens the **command palette**, a search field over a list of
everything the page does. The list holds every page, the live sources and the eight newest
recordings, a game on Play in each listed scenario, a request for a match, the settings of sound,
theme, broadcast mode, player labels, motion and the presets of the presentation, the choices of
the View menu, which are the cameras, the arenas, the four times of day, the weather, photo mode
and fullscreen, every player of the open match to follow with the Follow player camera, the
challenges of Play, Surprise me for a team, and the topics of the Help page. Typing narrows the
list, with the letters of each word in order anywhere in a name, so `gotea` finds Go to Teams
and `follow 10` finds the player with that number. Words that belong to an action also find it,
such as `volume` for Mute and `photo` for Photo mode. The arrows move through the list,
Page Up and Page Down move further, Enter runs the chosen action, a click runs any action and Esc
closes the palette. Focus then returns to the control that held it before. Ctrl K reaches the
palette from everywhere except a text field, which keeps its own keys, and an open palette
releases a captured pointer as any dialog does.

A first visit finds help along the way. Each page but Help shows a short tip in a corner of the
window after a moment, which points to the next thing to try, such as the command palette on Home
or the camera keys on Watch once a match is open. The tip takes the lower left corner, or else the
first other corner where it covers no control of the page and no notice, and it waits while a
dialog, a menu, the palette, photo mode, broadcast mode or a game is open. The tip comes right after
the top bar in the order of the Tab key. Got it puts that tip away for good, the button
No more tips turns every tip off, and the setting Tips for new visitors turns them on again with
every tip back. Take the tour, beside Got it, starts the guided tour of
[Learning the renderer](#learning-the-renderer). The browser keeps each dismissal. The main controls
carry a short line of help, which shows beside a control when keyboard focus reaches it, and under
the pointer for a control without a tooltip of its own. Esc, a click or leaving the control hides
it.

A page with nothing to show says what to do next. Watch without a match names the command
`cuju render demo` and opens a sample match in one click. Recordings without a recording names
`cuju render sample`, which brings the samples back, and `cuju.render.Recorder`, which records
the matches of a script, beside Play a match and How to record. Teams with the built in AI alone
points to the topic Making a team of the Help page, and Matches before its first request says
that the built in AI plays every scenario.

The address follows each page change and names what it shows, so a page or a moment reopens as a
link on the same machine. The address `#page=teams` opens the Teams page, `#match=` with the
identifier of a recording and `&t=` with a number of seconds opens that recording at that moment,
and `#live=` with the identifier of a live source opens the source. An address that names nothing
opens Home. A local file uses `#page=watch` and must be opened again after a reload.

**Home** opens with the cuju title, with a
tagline, a short description and the actions beneath it. Watch and Play a game open their pages,
alongside
Request a match, Teams and Field, and a line under the actions counts the live sources and the
recordings. The page continues in sections. The first holds Live now and Latest recordings
side by side, the sources that stream at the moment, each opening with one click, and the five
newest recordings, each with a control that plays it. While there are no sources and no
recordings, a guide of three steps takes their place, with the commands that run the page, stream a
running batch and make a recording. A montage of the viewer follows, muted at first and
started from its controls. Next come six short notes on what the viewer does and the main
keys of the Watch page in four groups, with a control for every shortcut. The page closes with an
about section and its credits beside the links to the repository, the documentation, this guide,
the issues, the changelog and PyPI, and a line with the license and the installed version. A server
that does not answer is shown as such, and a recording file still opens from the computer. On a
narrow screen the sections use one column.

**Watch** fills the page with the match. Its bar holds the Match and View menus and camera controls.
The Match menu carries a list as its symbol, the View menu an eye and Export video a strip of film,
each beside its name, and on a phone the three show their symbols alone. The address field opens
its source with the arrow beside it.
The Match menu opens a recording file from the computer, takes an address, leads to the Recordings
and Matches pages, lists the goals of the open match, each of which jumps to six seconds before it,
and lists the live sources and the six newest recordings, with a count of the live sources on the
menu's button. The address field takes the identifier of a live source or of a recording, such as
`m-20261106-105640-3a3f`. On a phone the address field takes a row of its own below the menus, so
it keeps its room in every language. The View menu chooses the camera, turns broadcast mode,
fullscreen and the 2D view on and off, sets the hour, the weather and the arena, and sets the
quality and the theme. Copy feed address in the View menu writes the address of a clean feed for
OBS, of the open match or of a source to follow, each live source and tournament of the server among
them, with its size, graphics scale, background, frame rate, camera and sound, and the graphics
alone without the picture when asked, as described under Streaming with OBS. Export video turns a
range of the open recording into a video file, as described under Exporting video. Under This match,
the Match menu also holds Save captions and Moments of this match, as [Moments and
captions](#moments-and-captions) describes. A recording also opens when its file is dropped anywhere
on the page. The view shows a spinner while it waits for a live source to send its first step, and a
bar of progress while a recording downloads.

The controls along the bottom of the view hold a timeline, the time and the length of the match,
buttons that restart, jump to the previous and next goal, skip 30 and 5 seconds either way, step
one frame either way, play backwards, pause and play, a speed of a quarter to four times real time,
and the mute button and the volume. The timeline seeks on a click or a drag, and marks each goal,
which a click on its mark reaches six seconds early. While the match plays, the controls and the
bar fade after a few seconds without input, together with the pointer, and return when the pointer
moves. On a touch screen the buttons take the size of a finger and the timeline a taller strip. A
swipe along the timeline moves through the match from where the view stands, its whole width being
the whole match, and a tap on it seeks to the place tapped.

**Recordings** lists the library like a file explorer. A pane of folders holds every recording
under All recordings and the folders in a tree with their counts, where folders are made, renamed
and deleted, and recordings are dragged onto them. A folder is a label in the summary of each
recording, so deleting a folder moves its recordings to the folder above. A search field finds
recordings by title, teams, scenario and folder across every folder, filters narrow the list by
folder, scenario, team and date, and the list sorts by date, title, goals, teams, length or size.
The columns show the title, the teams, the score, the scenario, the steps, the date and the size,
and a click on a header sorts by it. Recordings are selected one at a time, several at once with
Ctrl or a range with Shift, and opened, renamed, moved or deleted, with the arrows, Enter, Delete
and F2 at hand. The toolbar above the list shows these actions as symbols, Open as a triangle,
Rename as a pencil, Details as the letter i, Move to as a folder with an arrow, Restore as an arrow
turning back, Move to Trash as a waste bin and Refresh as two arrows in a circle, and the Trash
view names Delete permanently in words beside its waste bin. The count above the list gives the total size of the recordings of the library,
or of the Trash in the Trash view.

The search also reads the tags and notes of each recording. Three more filters narrow the list,
Favorites to the recordings marked as favorites, Source to requested matches, played games,
challenges, recorders, live sources or recordings of unknown source, and Result to the matches
the left team won, those the right team won, draws and recordings whose score is unknown. Details
opens a panel
above the list for the selected recording, with a Favorite mark, tags separated by commas, up to
twenty of at most forty characters each, and notes of up to ten thousand characters, which Save
details keeps and Close or Esc leaves. The panel also lists the provenance of the recording, the
source, the version of cuju and, where they are known, the seed, scenario, teams, controls, agent
counts, action set, ability and environment, as described under Recording format. A field that the
panel leaves out is unknown. Favorites show a star beside their title, and the first three tags
follow it. Search moments beside the search field opens the search of the moments of every
recording, as [Searching moments](#searching-moments) describes.

Delete moves the selected recordings to the Trash at once, and a message says where they went. The
View filter switches between the library and the Trash, which lists the recordings deleted from the
library with the same search, filters and sorting. In the Trash, Restore returns the selected
recordings to the library with their folder, details and frames as they were, and Delete
permanently removes their files from the disk after a question, which cannot be undone. Only a
recording already in the Trash can be deleted for good. A recording of the Trash opens in Watch
once it is restored, and the Trash keeps using disk space until its recordings are deleted.

The recordings of one run of a challenge show as one group, a row that names the challenge and the
competitor, such as One on one, GRF's built-in AI, with the run's result, such as goal difference
+3, silver medal, the count of its recordings and their total steps and size. The title of the row
is a disclosure button, which a click, Enter or the right arrow opens to the rows of the attempts
in their order, and a click, Enter or the left arrow closes again. The left arrow on the row of an
attempt goes back to its group, and a screen reader hears the button as expanded or collapsed. The
group's row selects all its recordings, so Delete moves the whole group to the Trash in one step,
and in the Trash the group's row restores the group in one step too. A run under way shows how
many of its attempts it has played, a run that a person left says after how many attempts, and a
run that ended on a failure says that it stopped.

**Matches** requests a match between two teams of the registry. Two cards pick the left team,
which plays at home, and the right team, which plays away. Each card shows the count, assignment,
fixed selection, goalkeeper and action set, and has an Ability control. The scenario list offers
full matches of the team format and academy scenarios, and a short text under it gives the chosen
scenario's players a side, length, difficulties, the events that end an episode and, for an
academy, its drill. Random team, the first entry of each side's list, leaves the side to the draw
of the seed, and the box Pool of the draw then lists every team of the registry with a box to tick,
so the draw takes only the teams ticked there, and Let a team meet itself below them. The
scenario list starts with Random scenario whenever two or more scenarios fit, and holds the
scenarios that some team of the pool can play on each side. A seed field takes a whole number or
stays empty for a random one. Each
requested match checks the actual controllable players and roles on both sides before entering the
queue. Teams of different formats can meet in academy scenarios when both settings fit.
Below, the list of requested matches shows each match with its teams, state, scenario, seed and
progress, filtered by state, team, scenario and date, with controls to cancel a waiting or playing
match and watch a finished one. A message announces each match that is ready.

The list is the history of requested matches, kept across restarts of the server. It holds the
newest 200 requests that have ended and every waiting or playing one, and the server deletes the
files of older ones. The page shows 50 entries at first, and Show more at the end of the list adds
50 more each time. Each entry shows the seed that the match plays with, which the server draws when
the seed field is empty, the time the request was made and how many seconds the match played. Retry
on a failed, canceled or interrupted match and Repeat on a finished one queue a new request with the
same teams, scenario, seed and ability. The new request plays the teams as the registry holds them
at that moment, so a team whose files changed since the first match plays its new files. A seed
above `2**53 - 1` keeps its exact value on the page and in a retry.

A request with a part drawn at random shows Random team or Random scenario in its place while
the match waits, and the team or scenario drawn once the match starts, each followed by two dice
that a screen reader reads as drawn at random. Retry on such a request sends the same random
parts, pool and seed again, so it draws the same match, and Repeat sends them without the seed,
so the server draws a new seed and with it a new draw. The tooltips of the two buttons say which
one keeps the seed.

**Tournaments** makes and follows tournaments of registered teams, the built in AI and people, as
described under Tournaments.

**Teams** lists the registry on its left, with a form that adds a team from a submission folder or
a single file, and opens the editor of the chosen team on its right, as described under
Customization.

**Field** configures the ground, as described under Environment. Its settings stay in the
browser, and a file of JSON exports and imports them, so they move between machines and browsers.
An import with any value out of place changes nothing and says which value, and a reset returns
the default afternoon in the stadium.

**Help** opens from its tab or with H or the question mark key. Escape returns to the previous page.
It opens with Learn by doing, which holds the guided tour, the lessons to do by hand, the samples,
the diagnostic report and the installable page, as [Learning the renderer](#learning-the-renderer)
describes. Below that it lists the pages, getting started steps, Watch shortcuts, Play controls and
keyboard navigation. Its links open the full guide and repository.

## Watching a match

The keys work on the Watch page, outside the text fields, and the Help page, opened with H, lists
them all. The keys of the players follow the physical keys, so they work on every keyboard layout.

| Key | Action |
| --- | ------ |
| Space | play or pause |
| L and J | play forwards or backwards, faster on each further press |
| K | pause |
| Left and Right | one frame while paused, 5 seconds while playing, 30 seconds with Shift |
| Comma and period | the previous or next frame |
| Up and Down | a faster or slower speed |
| Home and End | the start, and the last frame or the present of a live source |
| N | the next goal, the previous one with Shift |
| R | a replay of the last goal, with more angles on Shift with R |
| Enter | skips the current sequence or the current part of a show |
| Esc | leaves the current sequence, show or player camera |
| V | the next camera in the cycle |
| B and P | follows the ball, or the player on the ball |
| 1 to 9 and 0 | the left team's outfield players, the right team's with Shift |
| G | the left team's goalkeeper, the right team's with Shift |
| Brackets | the previous or next player of the chase camera |
| W, A, S and D | fly the free camera along the pitch, faster with Shift |
| Q and E | lower and raise the free camera, C lowers it too |
| T | broadcast mode |
| O | photo mode |
| F, M and H | fullscreen, mute and the help |

Menus accept the arrow keys to move between entries, Home and End to reach either end, and
Enter or Space to choose. Typing a letter finds the next entry that starts with it. Esc closes
the menu and returns focus to its button, and a click outside closes it too.

A drag of the mouse turns the free camera and orbits the cameras that follow the ball or its owner,
and the wheel sets the flying speed or the distance of those cameras. A click on the view skips the
current sequence. The setting for capturing the mouse lets a right click in the free camera capture
the pointer for looking around, and Esc releases it. The setting is off by default, and the page
releases the pointer whenever a dialog, a menu, a panel, a details section or a card opens, focus
moves to a control, the window loses focus or the page hides.

The setting Player labels puts the number and the name of each player above that player on the
Watch page, together with the name of the team. A label shows only while the player is in sight,
so a player behind the stands, a goal post or the roof loses the label until the view finds the
player again. Where two labels would meet, the player nearer the camera keeps the label, and the
labels leave the top edge of the view and the controls clear. They give way to replays, shows and
transitions and return after them. The setting Click a player to follow lets a short click on a
player who is in sight put the Follow player camera behind that player, and the name of the
player shows for a moment. A drag still turns the camera, and the brackets choose the followed
player from the keyboard.

A live source plays like a digital video recorder, three seconds behind the newest step, and keeps
up to 30 minutes within an 80 MiB memory budget, about 15 minutes for eleven a side. The budget
holds for any header, so a stream of very many players or steps keeps fewer frames.
The view pauses, rewinds and scrubs while the stream continues. The controls show how far the view
lies behind, and a button returns to the present. A viewer who joins
late starts with the history that the source holds, up to 10 seconds, and a speed other than real
time leaves the present until the button returns to it.

The controls name the state of the connection. They read Reconnecting while the page reconnects,
Disconnected once the attempts of an outage have failed, and Stream ended when the source closed,
and they add the number of frames lost while the stream reconnected. The view joins the frames on
either side of a loss with a cut. The frames already received stay in the view in every case, and
the view pauses, rewinds and scrubs through them as before. A stream that ends before its first
frame closes the waiting view and says so. A stream on another server that the page cannot reach
reports that such a stream must allow the page through CORS.

A live source of this server whose batch has several environments shows an Environment field
beside these controls, with the index that the source shows. Typing another index and pressing
Enter, or choosing Switch, asks the source to show that environment after the next step of the
batch. The stream of the old environment then ends and the page opens the new one in its place,
and every page that watches the source follows it the same way, on whichever page it shows. The
frames of the old environment leave the view with it.

### The grid of environments

The Grid button beside these controls, a symbol of four squares, and the Grid of environments entry of the View menu, open
a panel over the view with many environments of the same batch at once. Each tile is a small 2D
view of one environment, from above as in the 2D view, with its index, its score and its clock
along the top, and the tile of the environment that the main view shows carries a border. The
tiles refresh at the modest pace that the grid of environments under Live sources describes, and
a tile that the source has not read yet says it is waiting. A tile whose environment the source
answers without a new picture keeps its last picture and says that it is refreshing, along its top
and to screen readers, until a later answer brings the environment again. The panel keeps the last
picture of each environment while it shows the same source, so a page of tiles seen before shows
them at once and refreshes them. The Tiles field sets 4, 9, 16, 25, 36, 49 or 64 tiles, up to the
first size that holds the whole batch, and the choice stays in the browser. Previous and Next, or
Page Up and Page Down on a tile, move to the neighboring page of environments, and the panel names
the range it shows.

A click on a tile, or Enter or Space on a focused tile, closes the panel and shows that
environment in the main view, through the switch of environments above, in 3D or in the 2D view
as the View menu sets it. The panel opens with the focus on the tile of the environment that the
main view shows, the arrow keys move the focus between tiles by rows and columns, Home and End
reach the first and the last tile, and Esc or Close closes the panel and returns the focus to the
button that opened it. The grid needs a source of this server with several environments, and it
closes when the main view opens another source.

### Cameras

The cameras follow the conventions of football broadcasts and video games. The key V cycles five
of them.

1. **Broadcast**, from a gantry high on the main stand, which pans with the ball, leads the play,
    widens when the play is fast and tightens near the goals.
2. **Tactical**, from high above, with the whole pitch in the window.
3. **Behind the goal**, behind whichever goal the ball is nearer.
4. **Follow player**, a chase view behind one player, looking towards the ball, whose player the
    brackets change.
5. **Free camera**, which flies from wherever the view stands.

The key B follows the ball, and P follows the player on the ball, the last owner for a moment after
the ball runs loose, and then the nearest player. Both keep the angle and the distance of the view
at the moment they start, so the drag and the wheel set them. The keys of the players put the view
on one player, over the shoulder at first. Pressing the same key again cycles the view through the
player's eyes, from the side and from the front, and the chosen view stays when the key of another
player is pressed. A name and number at the bottom of the picture say who the view follows.

Every change of camera glides, and every steered camera stays within the ground, above the grass,
under the roof line, off the seats and clear of the players' bodies.

The cameras that follow play by themselves frame the match at every shape of picture. A picture as
wide as 16 by 9 or wider shows each shot as tuned, and a narrower one, square or tall, widens the
view upwards so the shot keeps its area, with its width shrinking gently rather than in proportion.
The broadcast camera then leads the ball by less and follows it faster, so the ball keeps the same
place in the picture, and the tactical camera fits the whole pitch at every shape. The high replay
angle and the restart of a goal kick turn towards the goal and the taker in a narrow picture, so
both stay in sight. After 20 seconds without
input, the free camera returns to the broadcast view, which a setting turns off or lengthens.

### The 2D view

The 2D view draws the match from above on a plain 2D canvas, without WebGL, for a slow or older
computer. The 2D view entry of the View menu and the 2D view setting turn it on and off, and the
choice stays in the browser. It draws the same moment of the same timeline as the 3D view, so
playing, pausing, seeking, the speeds, the keys and live sources work as they do in 3D, and the
scoreboard keeps the score, the clock and the goal graphic above the drawing.

The pitch lies as the broadcast camera sees it, with the left team's goal at the left edge. Each
player is a disc in the shirt color of the team, the goalkeepers in their own color, with the
player's number on the disc when the disc is large enough to hold it. A ring marks the player on
the ball, and a second ring marks each player that an agent or a person controls. The ball rises
up the picture with its height and grows a little, over a shadow that stays on the ground where
the ball would land, and a thin line joins the two while the ball is in the air.

The parts of the presentation that need the 3D view wait while the 2D view draws. Replays,
celebrations, the lineups before kick-off, the restart transitions, the decision replays and the
show after the match are skipped, and the goal graphic, the banners of restarts and the card of
full time still show. Their settings keep their values and apply again once the 3D view returns.
Turning the 2D view on ends a replay or a show that is running.

A browser without WebGL opens the page in the 2D view, which then stays on, and Watch says so once.
The Play and Field pages draw their pictures with WebGL alone. When the 3D picture of a playing
match draws fewer than 12 frames a second over 5 seconds, a card at the top right offers the 2D
view once in each visit. Use the 2D view turns it on, and Keep 3D keeps the 3D view and stops the
offer for good in that browser. A clean feed and a video export draw at a pace of their own, which
says nothing of the computer, so they never show the offer.

### Photo mode

Photo mode holds a moment of the match and frames it with a free camera, for a picture worth
keeping. The key O or Photo mode in the View menu opens it on the Watch page and pauses playback.
The players, the ball, the crowd and the weather stand still, and the bars and controls of the
page give way to the panel of photo mode, at the right of the view, or along its bottom on a
narrow screen. O, Esc or Leave returns to the match as it was, with the camera, its mode and
playback restored, playing again if it played. The settings of photo mode stay for the visit, so
the next photo starts from the last one's look.

The camera flies as the free camera does. W, A, S and D move it, Q and E lower and raise it, C
lowers it too, the arrows turn it, Shift speeds each of them up, a drag of the mouse turns it and
the wheel sets the flying speed. Z and X roll the picture, minus and plus zoom it, and the panel
sets the same roll and field of view, from 90 degrees either way and from 10 to 100 degrees.

Depth of field blurs whatever lies nearer or farther than the focus distance. By default the
focus follows the point at the center of the picture, and the brackets or the Focus distance
slider set it by hand, from half a meter to 300 meters. Blur strength sets how quickly the blur
grows away from the focus, and Shift with the brackets changes it from the keyboard. At zero the
whole picture stays sharp. R resets the roll, the field of view and the focus.

The looks grade the colors of the whole picture. Natural leaves them as drawn, and Warm, Cold,
Noir in black and white, Vintage, Vivid and Matchday each grade them in their own way. L cycles
the looks, and Shift with L goes back. Vignette darkens the edges of the picture and Grain lays
film grain over it, each from 0 to 100 percent. The grain moves as on film and holds still under
reduced motion.

Guides help to frame the picture, and G cycles them, back with Shift. Rule of thirds and Golden
ratio divide the picture with two lines each way, Center cross marks its middle, and the two crop
frames shade all but a part of the view in the shape of 16 by 9 or 4 by 5. The guides lie over the
picture and stay out of every saved photo.

Save photo or P saves the picture as a PNG file named after the recording and the frame, such as
`cuju-photo-m-20261106-105640-3a3f-412.png`. Resolution chooses Window size, the size of the
view on the screen, a size of [Picture sizes](#picture-sizes) such as 1920 by 1080, 3840 by 2160
or 1080 by 1350 for a portrait, or Custom size, whose width and height take any size from 16 to
8192 pixels. A size of another shape than the view keeps the part of the view that the guides leave
unshaded, and every size draws with the same camera, look, blur, vignette and grain.

Hide interface or U hides the panel for a clear view, and U or Esc brings it back. With the
setting Capture the mouse on, a right click on the picture captures the pointer while the panel is
hidden, as in the free camera, and the page releases it whenever the panel shows, a menu or dialog
opens, focus leaves the window or the page hides.

Every control of the panel works by Tab and the keys of its kind, and the keys of photo mode work
everywhere outside its lists. A controller with the standard mapping flies the camera as well.

| Button | Action |
| ------ | ------ |
| <kbd>Left stick</kbd> | move along the pitch |
| <kbd>Right stick</kbd> | turn |
| the triggers | lower and raise |
| the vertical and horizontal pad | zoom and roll |
| the shoulder buttons | the previous or next look |
| the lower face button | save the photo |
| the right face button | leave photo mode |
| the left face button | hide or show the panel |
| the upper face button | the next guide |

Scripts and agents use photo mode through `window.cuju.photo`, without a mouse.

| Call | Effect |
| ---- | ------ |
| `open()` and `close()` | open or leave photo mode, each returning the state |
| `set(settings)` | change any of the settings and return the state |
| `camera({ position, target, fov, roll })` | place the camera at once and return it |
| `await capture({ width, height })` | the photo as a PNG data URL |
| `await capture({ as: 'blob' })` | the photo as a PNG Blob |
| `await save()` | save the photo as a file, as P does |
| `hideInterface(true)` | hide the panel, and false shows it again |
| `state()` | the settings, the camera, the window's size and the last photo |

The settings are `look`, `vignette`, `grain`, `focus`, `aperture`, `fov`, `roll`, `guide` and
`resolution`. A capture without a size takes the chosen resolution, and the camera takes positions
in meters as `[x, y, z]`, with y up. The looks are `natural`, `warm`, `cold`, `noir`, `vintage`,
`vivid` and `matchday`, and the guides are `off`, `thirds`, `golden`, `center`, `crop-16-9` and
`crop-4-5`. A focus of `'auto'` follows the center of the picture, and a number sets the distance in
meters. Vignette, grain and aperture run from 0 to 1, and a resolution is `'window'`, a size such
as `'3840x2160'`, a name of [Picture sizes](#picture-sizes) such as `'vertical'`, or an object with
width and height up to 8192 pixels each. An unknown name or a value
out of place, a number out of its range among them, throws an error that says what fits, and the
settings stay as they were. The keys and the controller stop a setting at the end of its range.

```js
const photo = window.cuju.photo;
photo.open();
photo.set({ look: 'noir', vignette: 0.4, grain: 0.2, aperture: 0.5, guide: 'thirds' });
photo.camera({ position: [0, 3, 20], target: [0, 1, 0], fov: 35 });
const png = await photo.capture({ width: 1920, height: 1080 });
photo.close();
```

## Exporting video

A range of a recording becomes a video in two ways. The Export video dialog of Watch, described
under [From the Watch page](#from-the-watch-page), draws and encodes the video in the browser that
shows the page, so `pip install 'cuju[render]'` and a recent browser are all it takes. The command
`cuju render video` serves the terminal and scripts, and needs an installed Chrome, Edge or
Chromium and nothing else.

The command turns a range of a recording into an MP4 or WebM video. It opens the same page that
Watch shows in a copy of the browser that runs without a window, and the browser draws and encodes
the video itself, exactly as the dialog of Watch does, then hands the finished file back to the
command in pieces. Between two frames the page's clocks, timers and animations move by exactly one
frame, so the video plays evenly at its frame rate however slowly the machine draws. A browser without a graphics card draws in software,
about one frame a second at 1280 by 720 on a laptop, and a graphics card draws faster.

```sh
cuju render video sample-5v5 -o kickoff.mp4 --end 20
cuju render video match.cjr -o goal.mp4 --goal 2 --size 1080p --fps 60
cuju render video match.cjr -o night.mp4 --start 1:30 --end 2:00 --arena neon --time night
cuju render video match.cjr -o short.mp4 --goal 1 --size vertical --scale 1.25 --safe social
```

The source is a `.cjr` file or the identifier of a recording of the library, as the Recordings page
lists them. The video goes to the file of `-o`, by default the name of the source in the current
folder, and a file that already exists stays as it is unless `--overwrite` is given.

### Formats

The command writes MP4 with H.264, which plays everywhere, or WebM with VP9, or VP8 where the
browser lacks VP9, which every recent browser and most players open. The browser decides what it
can write. Google Chrome and Microsoft Edge encode H.264, so they write either format. Chromium as
many Linux distributions build it encodes no H.264 and writes WebM.

| Format | Codec | Browsers that write it |
| --- | --- | --- |
| `mp4` | H.264 | Google Chrome, Microsoft Edge |
| `webm` | VP9 or VP8 | Google Chrome, Microsoft Edge, Chromium |

The option `--format` asks for `mp4`, `webm` or `auto`. Without it, an output named with `-o` asks
for the format of its suffix, `.mp4` or `.webm`, and an export without `-o` takes `auto`, which
writes MP4 where the browser encodes H.264 and WebM otherwise, and names the file with the suffix
of what it wrote. A format that the browser cannot write stops the command before it draws, with a
message that names the browser and what would write the format.

ffmpeg stays optional and adds one thing, an MP4 from a browser without H.264. When an MP4 is asked
for, or `auto` finds no H.264, and ffmpeg is on the path, named by `--ffmpeg` or by the variable
`CUJU_FFMPEG`, the command takes a picture of each frame instead and ffmpeg encodes the pictures
with its own H.264 encoder, as the command did before browsers could encode. The picture is the
same either way.

```sh
cuju render video sample-5v5 --end 20                   # MP4 or WebM, whichever the browser writes
cuju render video sample-5v5 --end 20 --format webm     # sample-5v5.webm
cuju render video sample-5v5 -o kickoff.webm --end 20   # the suffix asks for WebM
```

### Range

The options `--start` and `--end` take a moment as seconds, such as `75`, or as minutes and seconds,
such as `1:15`, counted from the first frame of the recording as the timeline of Watch counts them.
A moment also names a goal, as `goal:2` for the first frame that shows the score of the second goal,
with seconds before or after it, as in `goal:2-8` or `goal:2+4`. The option `--goal 2` picks the
range from 8 seconds before the second goal to 4 seconds after it, and a `--start` or `--end` beside
it replaces that end of the range. The range is the whole recording when no moment and no goal is
given. A range is kept within the recording, and a goal beyond the last one stops the command with
the number of goals that the recording holds. The command checks the range before it looks for
Chrome and ffmpeg, so a mistake in the range shows at once.

### Presentation

The video follows the match clock, one second of video for each second of play. The page shows the
picture alone, as broadcast mode does, with the scoreboard and clock, the banner of a goal and the
graphics of the referee's decisions. The team sheets, the presentation of restarts, celebrations,
replays and the show after the match each hold or stop play, so they stay off. The option
`--broadcast` keeps them all, and the video then shows the match as Watch presents it and runs
until play reaches the end of the range, longer than the range itself and at most the maximum
length.

A video shows the picture of the match alone, as a page of a recording without annotations shows
it. The labels under the players and the box of the whole match that [annotations](#annotations)
add serve the study of a match on Watch, and a video shows them only with `--annotations`, each
with its numbers, its actions and its text.

The option `--no-score` hides the scoreboard and clock. The option `--camera` picks one of the
cameras that follow play by themselves, `broadcast`, `tactical`, `goal`, `ball` or `owner`, as
described under Cameras. The option `--arena` picks the arena, and `--time` the time of day as
`dawn`, `day`, `dusk`, `night` or an hour from 0 to 24. The export runs in a browser profile of its
own, so the other settings of the Field page keep their defaults. Kits, models, boards and
celebrations come from the registry of the renderer's folder, as Watch shows them.

An exported video is silent. The page mixes its sound live, in step with real time, while the
export draws far slower than real time, so the sound of the page stays out of the file.

### Options

| Option | Meaning |
| ------ | ------- |
| `-o`, `--output` | the MP4 or WebM file to write |
| `--format` | `mp4`, `webm` or `auto`, by default the suffix of `-o`, or `auto` without it |
| `--overwrite` | replace the output file when it exists |
| `--start`, `--end` | the moments where the video starts and ends |
| `--goal` | the range around one goal |
| `--camera` | the camera, `broadcast` by default |
| `--size` | a size of [Picture sizes](#picture-sizes), such as `1080p` or `vertical`, or a width by height such as `1920x1080`, `1280x720` by default |
| `--scale` | the scale of the graphics, from 0.5 to 2, 1 by default |
| `--safe` | the safe area of the graphics, `auto`, `social`, `none` or a percentage, `auto` by default |
| `--fps` | frames a second from 1 to 60, 30 by default |
| `--quality` | `draft`, `standard` or `high`, `standard` by default |
| `--no-score` | hide the scoreboard and clock |
| `--annotations` | show the labels and the box of the recording's annotations |
| `--arena`, `--time` | the arena and the time of day |
| `--broadcast` | keep the team sheets, restarts, celebrations and replays |
| `--max-seconds` | the longest video, 600 seconds by default and 3600 at most |
| `--max-size` | the largest file in MB, 2048 by default and 16384 at most |
| `--chrome` | the Chrome, Edge or Chromium that draws and encodes, found by itself by default |
| `--ffmpeg` | ffmpeg, optional, which encodes an MP4 where the browser has no H.264 |
| `--software` | draw in software, without the graphics card |
| `--no-sandbox` | run Chrome without its sandbox |

A picture takes any size of [Picture sizes](#picture-sizes) with even sides, which the encoder
needs, wide, square or tall. The page lays out with the shorter side at 720 pixels and scales up
for a larger picture, so the scoreboard and banners keep their proportion at every size, and they
keep inside the safe area of `--safe`. The quality `draft` encodes fast and small,
`standard` suits sharing, and `high` keeps fine detail in larger files. A range longer than the
maximum length stops before anything is drawn, and a file that reaches the maximum size stops the
export.

### Requirements and progress

The command needs one program beside cuju, a browser that draws the page and encodes the video,
and the export of the Watch page needs none, since it runs in the browser that shows the page.
Chrome, Chromium and Edge all serve the command, as does any browser built on Chromium of version
94 or later, which brought the video encoder. The command looks for `google-chrome`, `chromium`,
`chromium-browser` and `chrome` on the path and then in the usual places of each system, Edge
among them, and `--chrome` or the variable `CUJU_CHROME` names another program. The browser stays
outside cuju's dependencies, and the command says when it finds none and how to install one, for
example from https://www.google.com/chrome/, or with `apt install chromium` on Debian and Ubuntu,
which writes WebM. ffmpeg, from the path, `--ffmpeg` or `CUJU_FFMPEG`, serves only an MP4 that
the browser cannot write, as [Formats](#formats) describes, and installs with
`apt install ffmpeg`, `brew install ffmpeg` or `winget install ffmpeg`. Chrome running as root, as in many containers, runs without
its sandbox, which Chrome refuses to the root user, and `--no-sandbox` turns the sandbox off
elsewhere, for the containers that need it. A machine whose graphics card the headless browser
cannot use draws in software by itself, and `--software` asks for that from the start.
Software drawing is slow, as in WSL, where Chrome finds no graphics card. There a laptop processor
takes about half a minute to load the page and about two seconds for each frame of 1280 by 720, so
a range of three seconds at ten frames a second takes about two minutes, and a smaller `--size`
or a shorter range takes less.

The command prints the range and the number of frames, then one line of progress with the frame,
the share done and an estimate of the time left, and once the video is ready the file, its frames,
its length and its size. The browser keeps the finished file until the command has read it, piece
by piece, and the file is written beside the output under a hidden name, such as `.NAME.part.mp4`,
which takes the output's name once the video is complete. Through ffmpeg the pictures pass from the
browser to ffmpeg through a pipe into the same hidden file. Ctrl+C cancels the export, closes the
browser and ffmpeg, removes the partial file and the temporary browser profile and ends with exit
status 130, so a failed or cancelled export leaves nothing behind.

### From the Watch page

Export video in the bar of Watch opens a dialog for the open recording of the library and pauses
play. The dialog asks for the start and end, by default the moment that the timeline shows and 15
seconds after it. From here and To here take the timeline's position, and the Goal list sets the
range around one goal of the match, from 8 seconds before it to 4 seconds after. The dialog offers
the sizes of [Picture sizes](#picture-sizes) and Custom size, which takes any even width and
height, the scale and safe area of the graphics, frame rates of 24, 25, 30, 50 and 60 a second,
the three qualities, the five cameras and the scoreboard, and for a recording with annotations a
check box for them, off at first, and it uses the arena and the time of day of the page's own
field settings. A range is at most 10 minutes.

#### In the browser

Export draws and encodes the video in the browser itself, with the video encoder that the browser
offers through WebCodecs. Recent versions of Chrome, Edge and Firefox have one, and the dialog
says so in a line under the settings. The browser opens the recording a second time, in a frame of
its own that stays out of sight, laid out at the size of the picture as the command lays out its
headless Chrome. It holds the first frame for a second while the players take their kits and the
camera settles, plays one second before the range so the graphics have settled too, and then moves
the frame's clocks, timers and animations by exactly one frame at a time. After each step it
copies the drawn view into a picture of the chosen size and draws the page's graphics over it, the
scoreboard and clock, the banners and the captions, from the page's own styles. A slow computer
therefore still draws every frame, and only takes longer. The picture is the one that the command
draws, with the same layout, safe area, scale of the graphics, camera, arena and time of day, and
with the team sheets, replays and the offer of the 2D view kept out and the annotations shown only
when their check box is on.

The file is an MP4 with H.264, the format that plays everywhere, and a browser without an H.264
encoder writes a WebM with VP9 or VP8 instead, which every recent browser and most players open.
A key frame starts every two seconds, so a player seeks the file quickly, and the qualities set
the bit rate, from about 2.8 megabits a second for `standard` at 1280 by 720 and 30
frames a second to twice that for `high` and half for `draft`. A video is silent, as one of the
command is.

The dialog shows a bar and a line of progress with the frame drawn and the share done. Once the
video is ready, the line names its range and size, as in `The video of 0:30 to 0:45 is ready,
56 KB`, since the latest export may cover another range than the fields show, and Download video
saves it under the title of the recording and its range, with the extension of its format. Export
again starts another. Cancel export stops a running export and drops what it has drawn. Closing
the dialog leaves the export running, and opening it again shows its progress, but the file lives
in the page until it is saved, so the page stays open until then. A file grows to at most 2048
MB, and a range of 10 minutes at 1080p fits well within it.

#### Through the server

A browser without a video encoder, or one that refuses to let a page read back its own graphics,
asks the server to run the same export as the command, in a process of its own on the machine of
the server, and a line under the settings says so. The server's export runs in a headless Chrome,
Edge or Chromium of that machine and writes the format `auto` of [Formats](#formats), MP4 where
that browser encodes H.264 and WebM otherwise. The dialog then shows the server's progress in the
same way, and the file waits on the server until Download video saves it, with the suffix of its
format. The server runs one
export at a time, and a second request waits for the first to finish or be cancelled. Cancel
export stops a running export, which removes its partial file, and opening the dialog again shows
the latest export of that recording.

The server looks for its browser as the command does, on the path, in the usual places and in the
variable `CUJU_CHROME` of its environment, and for ffmpeg, which it uses only as the command does,
in `CUJU_FFMPEG`. A server that finds no browser needs a restart once one is installed. When
neither the browser nor the server can export, the dialog says so in two short lines, that a
recent Chrome, Edge or Firefox exports from the page with nothing else installed, and that the
server exports once Chrome, Edge or Chromium is installed where `cuju render` runs, with what the
server lacks behind a disclosure.

A file dropped on the page and a live source carry no recording of the library, and for them the
dialog explains that the export draws recordings of the library. The size of a finished video
reads in KB below a megabyte and in MB from there, here and on the command line.

### Over HTTP

The dialog asks the server for an export through these routes when the browser cannot encode, and
a script or an agent can use them the same way. The
server checks the host of every request, and a request that starts or cancels an export comes from
the page of the same server or carries no origin, as for every request that changes data.

| Route | Answer |
| --- | --- |
| `GET /api/video` | `available`, whether the server finds a Chrome, Edge or Chromium, and `missing`, a message when it finds none |
| `POST /api/matches/ID/video` | starts an export of the recording `ID` of the library and answers 201 with its entry |
| `GET /api/videos` | the entries of the exports, the one that runs and the three newest that ended |
| `GET /api/videos/VIDEO` | the entry of the export `VIDEO`, asked for again while it runs |
| `GET /api/videos/VIDEO/file` | the finished MP4 or WebM file, as a download under the entry's `filename` |
| `DELETE /api/videos/VIDEO` | cancels a running export or removes an ended one with its file, and answers 204 |

The body of `POST /api/matches/ID/video` is a JSON object, and every field but `end` may stay out.

| Field | Meaning |
| --- | --- |
| `start`, `end` | the range in seconds from the first frame, `start` 0 by default |
| `width`, `height` | the size in pixels with even sides, 1280 by 720 by default |
| `fps` | a whole number of frames a second from 1 to 60, as for the command line, 30 by default |
| `quality` | `draft`, `standard` or `high`, `standard` by default |
| `camera` | `broadcast`, `tactical`, `goal`, `ball` or `owner`, `broadcast` by default |
| `scale`, `safe` | the scale and the safe area of the graphics, as `--scale` and `--safe` take them |
| `score` | false hides the scoreboard and clock |
| `annotations` | true shows the labels and the box of the recording's annotations |
| `arena`, `time` | the arena and the hour of the day from 0 to 24 |

An entry holds the `id` of the export, the `match` it draws, its `title`, the `start` and `end` of
its range, its `state`, which is `running`, `done`, `failed` or `cancelled`, the `frame` drawn and
the `frames` in all, the `progress` from 0 to 1, the `bytes` of the finished file, the `error` of
a failed export and the `filename` that the download suggests. A field out of place answers 400
with an `error` that says what fits, a recording outside the library answers 400 as well, and a
second export while one runs answers 409.

```sh
curl -X POST http://127.0.0.1:8780/api/matches/sample-5v5/video \
    -H 'Content-Type: application/json' -d '{"start": 8, "end": 20, "fps": 30}'
curl http://127.0.0.1:8780/api/videos/v-20261110-101500-3fa9
```

## Picture sizes

The clean feed, video export and photo mode share one list of picture sizes, so a size means the
same picture in an address, in a dialog of the page and on the command line. Each size has a name,
and any other size is a width and a height such as `1000x1000`.

| Name | Width by height | Shape |
| --- | --- | --- |
| `480p` | 854 by 480 | wide |
| `720p` | 1280 by 720 | wide |
| `1080p` | 1920 by 1080 | wide |
| `1440p` | 2560 by 1440 | wide |
| `4k` | 3840 by 2160 | wide |
| `square` | 1080 by 1080 | square |
| `portrait` | 1080 by 1350 | tall |
| `vertical` | 1080 by 1920 | tall |

The names `2160p` and `uhd` stand for `4k`, `hd` for `720p`, `fhd` for `1080p`, `tall` for
`vertical` and `360p` for 640 by 360. A side runs from 90 to 3840 pixels and a picture holds at
most the pixels of 4K, so 2160 by 3840 is the tallest picture. A video needs even sides, which its
encoder asks for, and a photo takes sides up to 8192 pixels.

The page lays out with the shorter side of the picture at 720 CSS pixels and scales up from there,
so the scoreboard, the banners and the cards keep their proportion at every size. A picture of
1920 by 1080 shows the graphics as the page shows them at 1280 by 720, a vertical picture lays out
720 pixels wide and 1280 high, and a picture smaller than 720 on its shorter side lays out at its
own size. The scale of the graphics, from 0.5 to 2, makes them larger or smaller than that, so a
scale of 1.25 suits a picture that viewers watch on a phone. The Export video dialog, the Copy feed
address dialog and photo mode each offer the list with Custom size, which takes any width and
height, and the dialogs also offer the scale and the safe area.

The safe area keeps the score, the banners and the captions inside the picture at every shape. A
wide or square picture keeps a margin of a twentieth of the picture on every side, the title safe
area of television, and a tall picture keeps a little more at its top and bottom, where a phone
lays its own bars. The safe area `social` keeps clear of the buttons that apps of short videos lay
along the right of a tall picture and of the captions they lay along its bottom. A number such as
`3` keeps that percentage on every side, up to 25, and `none` lets the graphics reach the edges.
A square or tall picture moves the badge of a replay and the banners of restarts under the
scoreboard, which takes most of its width, and gives the lower thirds the whole width of the safe
area.

## Streaming with OBS

The page at `/feed` is a **clean feed**, the match at a fixed size with its broadcast graphics
alone, for a browser source of OBS Studio or another streaming program. It shows the picture, the
scoreboard and clock, the banners of goals and restarts, the decisions, the team sheets, the
replays and the show after the match, and nothing else. The pointer, the controls, the bars, the
menus, the messages, the tips and the dialogs stay out of it, and keys and the mouse reach
nothing. A feed starts silent, keeps its settings for itself, so it changes nothing that the
browser keeps for the page, and looks the same wherever its address opens.

```text
http://127.0.0.1:8780/feed?source=live&size=1080p
http://127.0.0.1:8780/feed?source=latest&size=vertical&scale=1.25&safe=social
http://127.0.0.1:8780/feed?source=tournament&size=720p&bg=transparent&audio=1
```

The feed lays the Watch page out as [Picture sizes](#picture-sizes) describes and draws the picture
at the pixels of the size it names. A window of another size shows the whole picture inside it,
centered, so a feed also opens in a browser tab for a look before it goes on air.

### Adding the feed to OBS

1. Start the server with `cuju render serve`, or any command that starts it, on the machine that
    runs OBS, or reach a server on another machine through a tunnel as [Remote use](#remote-use)
    describes.
2. Copy the address of the feed, from Copy feed address in the View menu of Watch, from
    `cuju render feed`, or by writing it by hand.
3. In OBS, add a source of the kind Browser to the scene, paste the address into URL, and set
    Width and Height to the size of the feed, such as 1920 and 1080 for `1080p` or 1080 and 1920
    for `vertical`. A canvas of the same size in the video settings of OBS holds the feed
    pixel for pixel.
4. Turn on Use custom frame rate and choose the frame rate of the stream, such as 30 or 60, so
    the page draws at the pace of the stream.
5. Leave Shutdown source when not visible off, so the feed keeps following its source while the
    scene is hidden, and turn on Refresh browser when scene becomes active if the server may start
    after OBS does.

The feed is silent unless its address carries `audio=1`. With sound, Control audio via OBS in the
properties of the source routes the sound of the match through the audio mixer of OBS, where it
has a fader of its own, and the feed plays at most at the levels of the page, at the volume of
`volume`, half by default. The sound plays only while the match plays, as on Watch. OBS lets the
feed start its sound by itself, and a browser tab plays it once the browser allows the page to
play sound without a click.

A feed with `bg=transparent` keeps the page's background transparent, so OBS shows the sources
beneath it wherever the feed shows no picture, while it waits and around a picture of another shape.
The frame of `/feed` takes the color scheme of the theme, so Chrome and the browser source of OBS,
which is Chromium, draw no backdrop behind it. With `layer=graphics` the feed shows the graphics
alone over that background, the score, the banners and the cards of the match without the picture,
for laying over a picture of another source, and draws nothing in three dimensions. A named
background such as `green` or a hex color such as `1a1a1a` gives a solid color in place of the
transparency, and `black` is the default.

### What a feed follows

The option `source` names what the feed shows. A feed asks the server every four seconds what its
source names, opens it, and moves on once the match it shows has finished, after the show at its
end, so a feed runs unattended for a whole evening.

| Source | The feed shows |
| --- | --- |
| `auto` | the newest live source while one streams, and the newest recording otherwise |
| `live` | the newest live source |
| `live:NAME` | the live source of that identifier, or the newest live source with that title |
| `latest` | the newest recording of the library |
| `tournament` | the newest finished match of the newest tournament |
| `tournament:NAME` | the newest finished match of the tournament of that identifier or name |
| `queue` | the newest finished match of the requested matches |
| `ID` or `recording:ID` | the recording of that identifier |

A feed that follows a source plays each match to its end before it opens the next, so a newer
match waits for the one on air to finish, and a feed that falls behind skips to the newest match.
Between matches it holds the last picture for six seconds and then shows its slate, the cuju logo
and a line that says what the feed waits for, until the next match arrives. The option `slate=0`
shows the background alone instead. A feed of one recording holds its last picture at the end, and
`loop=1` plays it again from the start, with its team sheets.

A live stream that drops reconnects as on Watch, and a feed whose stream ended or failed asks the
server again until a source answers. A training script that starts again announces a new live source
under the same title, so a feed of `live:TITLE` follows it through every restart, and a feed of
`live` takes the newest source. A stream that has lost its connection gives way at once to a newer
live source that the server names, and a question to the server without an answer within 10 seconds
counts as failed and goes again. A server that stops leaves the feed on its last picture, or on the
slate when nothing showed, and the feed picks up again once the server answers. A page of the feed
that fails to start, stops answering or loses its drawing context loads again by itself.

### Options

| Option | Meaning |
| --- | --- |
| `source` | what the feed follows, `auto` by default |
| `size` | a size of [Picture sizes](#picture-sizes) or a width and height, `1080p` by default |
| `w`, `h` | the width and height in pixels, in place of `size` |
| `scale` | the scale of the graphics, from 0.5 to 2, 1 by default |
| `safe` | the safe area, `auto`, `social`, `none` or a percentage, `auto` by default |
| `bg` | `black`, `transparent`, `green`, `blue`, `magenta`, `white` or a hex color, `black` by default |
| `layer` | `full` for the picture and its graphics, `graphics` for the graphics alone |
| `audio`, `volume` | `audio=1` for the sound of the match, at `volume` from 0 to 1, 0.5 by default |
| `fps` | a frame rate from 1 to 60 that the page keeps, the display's own pace by default |
| `camera` | `broadcast`, `tactical`, `goal`, `ball` or `owner`, `broadcast` by default |
| `loop` | `loop=1` plays a recording again at its end |
| `broadcast` | `broadcast=0` leaves out the team sheets, celebrations, replays, restarts and the show |
| `show` | `show=0` leaves out the show after the match alone |
| `score` | `score=0` hides the scoreboard and clock |
| `captions` | `captions=1` shows captions of the events inside the safe area, as [Captions](#captions) describes |
| `slate` | `slate=0` shows the background alone while nothing plays |
| `quality` | `low`, `medium` or `high`, `high` by default |
| `theme` | `dark` or `light` for the colors of the graphics, `dark` by default |
| `arena`, `time` | the arena and the time of day, as for `cuju render video` |
| `t` | the second where the first recording starts |

A flag such as `audio` reads `1`, `true`, `yes` or `on` as on, and alone, as in `&audio`, it is on
as well. A value out of place falls back to its default and the page logs it to the console, so a
feed always shows something, and `cuju render feed` checks every option before it prints an
address. With `fps`, the page draws every frame of the display that keeps an even pace at that
rate, and a stall resets the pace rather than drawing twice in a row. The frame rate of the browser
source in OBS sets the pace of the display, and a feed at the same rate draws every frame.

### Addresses for scripts and agents

`cuju render feed` prints the address of a feed for the server of the renderer's folder, which
suits a script that sets up OBS or an agent that hands the address on. Run with no source, it lists
every source that a feed may follow, the five kinds and each live source and tournament of the
running server, with the address of each. A live source shows as `live:TITLE`, which follows it
through its restarts, and a source without a title by its identifier. A recording that the library
lacks, or a tournament that the running server lacks, stops the command with an error that names
it, while a live source may start later and its name passes.

```sh
cuju render feed live:Evaluation --size vertical --scale 1.25
cuju render feed --json
```

| Option | Meaning |
| --- | --- |
| `--size`, `--width`, `--height` | the size of the feed |
| `--scale`, `--safe` | the scale and the safe area of the graphics |
| `--background` | the background, `bg` of the address |
| `--graphics-only` | the graphics alone, `layer=graphics` |
| `--audio`, `--volume` | the sound and its volume |
| `--fps`, `--camera`, `--quality`, `--theme` | the frame rate, the camera, the quality and the theme |
| `--loop`, `--start` | play a recording again, and the second it starts |
| `--plain`, `--no-show`, `--no-score`, `--no-slate` | `broadcast=0`, `show=0`, `score=0` and `slate=0` |
| `--captions` | captions of the events, `captions=1` |
| `--arena`, `--time` | the arena and the time of day |
| `--json` | print JSON with the server, whether it runs and every feed |
| `--port` | the port of the address while no server of the folder runs, 8780 by default |

A command that finds no server of the folder still prints the address for the port of `--port`
and says on its error output that the server must run before the feed shows anything. In Python,
`cuju.render.feed_url(source='auto', port=None, **options)` returns the same address, with the
options of the table above under their names in the address, such as `size='vertical'` or
`bg='transparent'`.

The server answers `GET /api/feed/resolve?source=SOURCE` with what a source names at the moment,
an object with `kind`, which is `match`, `live` or `none`, the `id` and `title` of the match or
source, and for `none` a `message` that says what the feed waits for. The title and the message
come with `title_id` and `message_id` and their values, and each source of `GET /api/feed` with
`label_id`, as [Languages](#agents-and-scripts) describes. `GET /api/feed` lists the
sources with their addresses, as `cuju render feed --json` does. A page that holds a feed reads
its state through `cuju.feed.state()` inside the frame, or `cujuFeedFrame.state()` from the frame
of `/feed` itself, with the source, the match it shows, whether that match finished, whether the
server answers, whether the slate shows, the size, the layout, the safe area in CSS pixels and any
problem of the address.

## Playing a game

The **Play** page, opened from its tab or the Play a game action on Home, lets a person play a match
against the built in AI of GRF or a team of the registry. A setup card picks the scenario, with the
same short text under it as on Matches, the side to play, left, right or both for two people, the
team of each side, the ability of the built in AI on each side, as on the Matches page, and whether
the game goes to Recordings, which it does by default. The person controls one player of the side,
and the built in AI plays the teammates and the other team unless the setup names a team for them.
The side is an agent of the scenario, as a submission that controls the active player is, so the
engine hands control to the designated player as play moves, the player nearest the ball among
them, as GRF does for its own human players. An arrow floats over the controlled player, above the
ring of control.

The server plays the game in a process of its own at real time, ten steps a second, and streams
each frame to the page as soon as it exists, and the page shows the picture about a tenth of a
second behind the newest frame. The page sends the held keys and buttons on every change and twice
a second while it waits, and the server turns them into GRF's 19 default actions with GRF's own
controller logic, so a person's actions are actions like any agent's and the game is the match that
the engine plays for them. A change of direction comes first in a step, then the first button whose
state changed. The arrows and the stick stay held as GRF's sticky directions, sprint and dribble
stay pressed while held, and the passes, the shot and the slide act on the step they are pressed.
The controlled player switches automatically, by the engine's choice.

Each game plays in a process of its own, which plays that one game and ends. Once a game's picture
opens, the server readies the process of the next game, which loads PyTorch and cuju and then
waits, so Play again, the next attempt of a challenge and every later game start at once, where
loading took several seconds. The process kept ready reads the setup of its game only when the
game starts, so it plays the game exactly as a process started for it would, with the same seed,
frames and recording. A kept process that has stopped, or whose environment no longer matches the
server's, gives way to a new process, and the game starts as it would without one. The kept
process ends after ten minutes without a game and when the server ends, so a server where nobody
plays holds no memory for it. The first game after the server starts loads in a new process. While
a game starts, the scoreboard of the game before leaves the picture at once, and the new game's
scoreboard takes its place with the first frame.

The high pass key and button send both high pass and slide inputs. GRF handles high pass first,
then slide on a later step if the input stays held, so the result also depends on possession and
the action that the player can perform. Direction changes take priority over either input.
Movement follows the screen directions of the broadcast view, including when playing on the
right side.

The keys and buttons follow the layout of Gameplay Football, the game that GRF grew from, and the
keys of the players follow the physical keys, so they work on every keyboard layout.

| Key | Action |
| --- | ------ |
| Arrow keys | move, held as a sticky direction |
| S | short pass |
| W | long pass |
| A | high pass, or a sliding tackle when defending |
| D | shot |
| E | sprint, while held |
| C | dribble, while held |
| Esc | the pause menu |
| H | the Help page |
| M and F | mute and fullscreen |

A controller plays with GRF's own Xbox layout, the layout of FIFA. Each action belongs to the
position of a button, so an Xbox, Nintendo or PlayStation controller plays the same with the same
hands, and the page names the buttons in the labels of the controller's style. A stick pushed past
the dead zone along an axis counts as that direction. The dead zone is half way by default, as
GRF's own gamepad player reads it, and the input settings move it.

| Button, Xbox, Nintendo, PlayStation | Action |
| ------ | ------ |
| <kbd>Left stick</kbd> or <kbd>D-pad</kbd> | move, held as a sticky direction |
| the lower face button, <kbd>A</kbd>, <kbd>B</kbd>, cross | short pass |
| the right face button, <kbd>B</kbd>, <kbd>A</kbd>, circle | shot |
| the left face button, <kbd>X</kbd>, <kbd>Y</kbd>, square | high pass, or a slide when defending |
| the upper face button, <kbd>Y</kbd>, <kbd>X</kbd>, triangle | long pass |
| the right trigger, <kbd>RT</kbd>, <kbd>ZR</kbd>, <kbd>R2</kbd> | sprint, while held |
| the right bumper, <kbd>RB</kbd>, <kbd>R</kbd>, <kbd>R1</kbd> | dribble, while held |
| <kbd>Menu</kbd>, plus, Options, also called Start | the pause menu |
| <kbd>View</kbd>, minus, Create or Share, also called Back | the card of the controls |

A controller that the browser reports in the standard mapping of the Gamepad API plays at once.
Any other controller reports its own layout, and a notice offers to set up that controller. The
setup, also on the controls card and in the pause menu, first asks the style of the controller,
Xbox, Nintendo or PlayStation, preselected from the id the browser reports. It then asks for each
button in turn, the four face buttons, the bumpers, the triggers, the two system buttons, the left
stick and the D-pad, drawing each on a small sketch of the controller, and takes the next press,
whether the controller reports it as a button or as an axis. A trigger or button read as an axis
counts as pressed past half its travel. Skip keeps what a position had, Back returns a step, and
Cancel or Esc leaves the layout as it was, and the notice of a controller without the standard
mapping comes back after Cancel until that controller has a layout. The page keeps the style and the
layout in the browser's storage for each controller id, so two people each set up their own
controller, and before the style is chosen a press on another controller moves the setup to that
one. The controls card also shows the id the browser reports and whether its mapping is standard or
custom.

On a tablet or a phone, **touch controls** show over the game once a touch screen is used. A stick
in the lower left corner moves the player and holds a direction on each axis pushed past a third
of its reach, so a push towards a corner holds the diagonal, as the stick of a controller does.
The buttons in the lower right follow GRF's layout of the face buttons, long pass at the top, high
pass on the left, shot on the right and short pass at the bottom, with dribble and sprint above
them, and each holds for as long as its finger stays on it. Every finger acts on its own, so a
person moves, sprints and shoots at once. The buttons press the same inputs as the keys and the
buttons of a controller, through a device of their own, which the status line names Touch
screen, and when two people play the touch screen goes with the keyboard. The button Pause at the
top opens the pause menu, and the controls hide while it shows. The setting Touch controls on
Play shows them once a touch screen is used, which is the default, always or never.

The page reads the keyboard and every controller at once, and whichever device was used last drives
the player. A notice announces each controller that connects or disconnects, and a card in a
corner shows the controls of the device in use at the start of the game and whenever the device
changes. For two people, the keyboard and the first controller play the left side and the second
controller the right, or with one controller, the keyboard plays the left and the controller the
right. The input settings can name the device of each side instead, as described below.

The setup card holds **Input settings and tester**, a section that opens under the tables of the
controls. The browser keeps its settings for the next visit, and a browser that keeps no site data
uses them for the current visit only.

- **Keys.** Each action of the keyboard has a button with its key. Choosing the button and
    pressing a key gives the action that key, and Esc keeps the old one. A key is an arrow, a
    letter or a digit. H, M and F stay with Help, mute and fullscreen, and a key that already has
    another action is refused with the reason, so every key has at most one action. The tables
    of the controls, the card in a game and the keys of play follow the new keys at once.
- **Stick dead zone.** A slider from 0.1 to 0.8 sets how far the stick moves along an axis before
    it counts as a direction, for every controller.
- **Devices for two people.** A list for each side names its device, the keyboard or the
    controller in one of the four slots of the browser, or leaves the choice to the page. A side
    with a named device plays with that device alone, a side left to the page takes the devices
    that the other side leaves, and the page refuses the same device for both sides.
- **Tester.** A box that shows what each device holds at that moment. With the box focused, the
    keys of the keyboard show the actions they press, and every connected controller shows the
    position of its stick and the actions of its buttons and of its stick past the dead zone.
- **Reset input settings** brings back the default keys, dead zone and devices.

A controller works the whole section, as it works the rest of the setup card, apart from the
choice of a key, which takes a key of the keyboard.

During a game, the status line under the picture names the device in use and the action that the
engine took for each person, as GRF's controller logic turned the keys and buttons into it. The
game reports that action about once a second and whenever the score changes, so the line shows a
sample of play, enough to see whether a key or button reaches the engine as the action it should.
GRF keeps a held direction, sprint and dribble as sticky actions, so the engine takes no new action
on the steps after one of them starts. The line then says so and names what the person holds, as
in `no new engine action, direction top left held, sprint held`, and with a person on each side
each part names its side.

Esc or Start opens the pause menu, which pauses the game on the server and offers Resume,
Controls, Set up controller, Quit, Quit to Home and Home. Controls opens the card of the controls
above the menu and moves the focus into it, and Esc or the right face button closes the card
before the menu and returns the focus to Controls. The paused picture and the end of a
game fall silent. Home pauses the game and opens Home. Return to Play to Resume or Quit. Quit to
Home ends the game and opens Home. A page that hides pauses its game, a game that hears nothing from
its page for eight seconds waits for it and carries on by itself as soon as the page is heard again,
and after two minutes of silence the game ends, with an end card that names the silence. A game that
ends, at full time or on Quit, lands in Recordings when the setup asked for it, up to where it
stopped, and the card at the end offers to watch it on the Watch page with every feature of the
viewer. Restart transitions, replays and celebrations stay off during a game, so play never waits
for the page, while the scoreboard, the clock, the goal graphic and the sound remain. The server
plays one game at a time, independently of its queue of requested matches. Leaving Play for another
page pauses the game, and returning lets it resume. Losing window focus releases the keyboard
inputs. The end card offers Play again with the same setup, New game to return to setup and Home.
The Play page calls a natural ending Full time when the scenario is a full match, the final frame
marks an episode end and both the step and the clock reach the configured duration. Other natural
endings show End of episode. A saved game needs at least one played step. Its stream stays separate
from the list of live training sources.

A game whose picture draws fewer than 12 frames a second over five seconds of play offers Low
graphics quality once a visit, as Watch offers the 2D view. Use low quality sets it, the View menu
sets it back, and Keep this quality keeps the offer away in that browser. The offer shows only
above Low quality, and a clean feed or a video export never shows it.

A controller also works the setup card, the pause menu, the controls card, the end card and the
controller setup by the positions of its buttons. The D-pad or the left stick moves the focus and
repeats while held, the lower face button picks, steps a list or toggles a box, left and right
change a list or a slider, and the right face button goes back, closing a card or the setup or
resuming the game, while the steps of the setup that record a button take every press as theirs.

### Registered teams in a game

Each side of the setup card has a team list. On a side without a person it names the opponents,
the built in AI or any team of the registry, which plays the whole side as it would in a requested
match, with the same control settings, checks and errors. On a person's side it names the
teammates. The built in AI plays them by default, and a team with dynamic assignment may play
beside the person instead. The person's agent then comes first on the side and the team's agents
follow it, so the side needs one controllable player more than the team asks for, and GRF shares
the designated player among all the agents of the side as it does for any team of several agents.
The list of a person's side shows only teams with dynamic assignment, and the server refuses a team
of fixed assignment there, or a team that asks for more players than the side has left. The
recording names the team of each side in its provenance, together with the agents of each side,
and the end card names a team that stopped the game.

A team loads and plays in the game's own process, from its own folder, as a requested match runs
it, so its modules import and its weights load the same way, with weights only enabled. A game
with a team plays GRF's v2 action set, whose action 19 hands a player to the built in AI for one
step, while a team of the default set keeps its own checks of the 19 actions. The game never
waits for a team beyond its time.

- **Each step.** A team answers each observation on a thread of its own, and has nine tenths of
    a step, 90 milliseconds at ten steps a second, counted from the moment it sees the step. A
    team that misses that budget leaves its players to the built in AI for the step, as action 19,
    and its late answer is discarded. While a late answer is still on its way, the steps that
    follow go to the built in AI as well, and the team sees the next step once it is free. The
    status line counts the steps that the built in AI played in its place, and a notice says so
    when a team misses ten steps in a row. The recording keeps the count in its provenance.
- **The first call.** Kaggle agents often load their model on their first call, so the first
    observation has an allowance of its own, 45 seconds, after loading the team, which has 45
    seconds as well. The game shows its first frame once the team has answered, well within the
    two minutes that the page waits for a game to start.
- **Failures.** A team that raises an error or answers with anything but actions of its set ends
    the game, and a team that has not answered for ten seconds ends it too. The game ends cleanly
    in both cases, saves its recording up to the last step when the setup asked for it, and the
    end card shows the error. A team that fails to load or misses its first allowance stops the
    game before it starts, and the page shows the error.

### Games over HTTP

The Play page drives a game through routes that a script or an agent may use as well, with the
same checks of host and origin as every other route.

| Route | Body | Answer |
| ----- | ---- | ------ |
| `GET /api/game` | none | the game of the server, with its `state`, `step`, `score`, `ending` and `match`, or `null` |
| `POST /api/game` | `{"scenario": "5_vs_5", "humans": [true, false], "teams": ["builtin", "builtin"], "ability": [null, null], "seed": 7, "record": true}` | the new game, with 201, or 409 while another game plays |
| `GET /api/game/ID/stream` | none | the frames of the game, as the stream of a live source |
| `POST /api/game/ID/pause` | `{"paused": false}` | the game |
| `POST /api/game/ID/input` | `{"side": 0, "held": ["left", "sprint"], "pressed": ["shot"]}` | the game |
| `DELETE /api/game/ID` | none | the game, which ends |

`humans` says which sides a person plays, and the other side plays its team of `teams`. A game
waits at the kick off until a pause of `false` starts it. An input names the side of a person,
`held` lists what the side holds now, among the directions `left`, `right`, `up` and `down` and the
buttons `long_pass`, `high_pass`, `short_pass`, `shot`, `sliding`, `sprint` and `dribble`, and
`pressed` lists the buttons pressed since the last input. A game that hears no input or pause for
eight seconds waits, and after two minutes it ends with the ending `timeout`, so a script sends an
input at least every few seconds while it plays. An input for a side that no person plays is
refused, with an error that names the sides a person plays in that game.

## Tournaments

A **tournament** plays many matches between many entrants and crowns a champion. Its entrants are
registered teams, the built in AI at chosen abilities, each a named entrant of its own, and people,
so agents and people take part in the same tournament on equal terms. The matches of agents play
headless in processes of their own, as requested matches do, and faster than real time. A match
with a person waits for that person, who plays it on the Play page when its turn comes. Every match
becomes a recording of the library, which opens from the tournament.

A tournament is a chain of one to eight **stages**. The first stage takes every entrant, and each
later stage takes those who advance from the stage before it, seeded by their standing there, at
random from the seed, or by rating. The tournament keeps going while results come in, so a stage
schedules each match as soon as both its sides are known, and the next stage starts once the
stage before it has ended. Tournaments take from 2 to 256 entrants.

### Entrants and their names

Every entrant carries a name of its own, which the brackets, tables, fixtures, recordings and the
trophy ceremony show. A registered team may enter the same tournament more than once, as a club
enters its first team and its reserves, or as a policy plays against an earlier copy of itself.
Each such entrant plays the same team of the registry under its own name, keeps its own place in
the draw, its own row in every table and its own path through a bracket, and two of them may meet
like any other pair of entrants.

Names are unique within a tournament. Two names that differ only in letter case or in the spaces
around and between their words count as one, so Rex FC, rex fc and REX FC with a space before
it all name the same entrant. A name typed for an entrant, on the page, with the option `--as` of
the command line or in a configuration file, that another typed name already holds is refused
with a message that names both entrants, in the language of the page, and in English on the
command line. An entrant without a typed name takes the name of its
team, of the built in AI at its ability or of its kind, and when another entrant already holds that
name it takes the first free number from 2, so a team entered three times plays as Rex, Rex 2 and
Rex 3. Such a numbered name steps around every typed name, wherever the typed one stands in the
list, so beside a person named Rex 2 the team's second entrant becomes Rex 3.

A match between two entrants of one team is a match of that team against itself, as two different
teams that share a policy play. Each side loads its own copy of the submission, the recording names
the two sides by their entrants, and the right side wears its away kit, the colors of its shirt and
shorts swapped with its trim, so the two sides look apart on the pitch, in the fixture and in Watch.
Its goalkeeper takes a contrasting color too. A policy that fails in such a match is named by the
entrant whose side failed.

### Abilities

The **ability** of a side, a number from 0 to 1, is how well the built in AI plays the players it
controls on that side, GRF's team difficulty. It steers every player of a built in AI entrant, and
it steers the players that a registered team or a person leaves to the built in AI, such as the
goalkeeper of a team whose agents control the outfield, the players beyond those its agents
control, or the teammates of a person. So the ability matters for every kind of entrant, and every
entrant may carry one of its own, which its side plays with in each of its matches.

A tournament may set a **standard ability**, which every entrant and every stage without an ability
of their own play with. A match gives each side its ability in this order, the strongest first.

1. The entrant's own ability.
2. The ability of the stage, or of the tournament's `defaults`, which reach every stage.
3. The tournament's standard ability.
4. The scenario's own ability, when none of the above is set.

So a league whose standard is 0.8 plays every side at 0.8, a final whose stage sets 1.0 plays its
sides at 1.0, and an entrant set to 0.3 plays at 0.3 in every stage. Two entrants of one team may
carry different abilities, as a first team and a weaker reserve side, and they stay two entrants
with names of their own. The built in AI at an ability keeps its name, such as Built-in AI 0.50,
and its rating, so a tournament of an earlier version loads and plays as it did. The provenance
of every match keeps the ability that the tournament gave each side, home first, beside the
ability that each side played with.

### Formats

Each stage plays one of eight formats.

- **Knockout.** Single elimination, each tie between two entrants, the winner going on. A bracket
    whose entrant count is no power of two is filled in one of two ways, chosen in the stage.
    Byes for the top seeds fill the bracket up to the next power of two, so the best seeds start
    in the second round. A **play-in round** brings the count down to the power of two below it,
    the lowest seeds playing each other for the last places of the bracket. The bracket size may
    also be set by hand within the range that either way allows. A knockout may stop when a set
    number of entrants remain, a power of two, which makes it a qualifying stage of a chain, and
    may add a third place match between the losers of the semi-finals. Seed one meets the lowest
    seed in the first round, and the best seeds meet as late as the bracket allows.
- **Double elimination.** A winners bracket and a losers bracket. An entrant that loses in the
    winners bracket drops into the losers bracket, and leaves the tournament after a second
    defeat. The winners of both brackets meet in the grand final. When the winner of the losers
    bracket wins it, both have lost once, and a deciding match follows unless the stage turns it
    off. Byes fill the bracket.
- **League.** A round robin, every entrant meeting every other. The number of cycles sets how
    many times each pair meets, once for a single round robin, twice for home and away, three
    times or more beyond that, with the home side alternating from cycle to cycle. The legs of a
    league set how many matches each meeting holds, played back to back with the venue in turn,
    and each counts in the table on its own. An odd count of entrants gives one entrant a rest on
    each matchday.
- **Groups.** The entrants are drawn into groups, and each group plays a league. The stage sets
    the number of groups, or a group size from which the number follows, or the size of each group
    by hand, so groups of different sizes are allowed. The draw puts the seeded entrants into
    **pots**, any number of them, as even as the count allows, the best seeds in the first pot,
    shuffles each pot by the tournament seed and deals its entrants one at a time to the next group
    with room. One pot for each place of a group gives the classic draw of one seed in each group,
    and a single pot gives a draw at random. The **qualifiers** of each group go on, a count for
    every group or one count for each group, and the stage may add the best entrants of one place
    across the groups, such as the four best third places, or as many as fill a bracket of the
    next power of two. Entrants of the same place compare across groups by points, goal difference,
    goals and wins for each match played, which keeps groups of different sizes fair, and then by
    lots. The qualifiers go on group winners first, then runners up and so on, so a knockout seeded
    by standing pairs winners with runners up.
- **Swiss system.** A set number of rounds, by default the rounds that a knockout of the same
    entrants would take. The first round pairs the seeds in order. Each later round orders the
    entrants by the table so far and pairs each with the best placed entrant it has not met. An
    odd count gives a bye to the lowest entrant without one, worth a win, a draw or nothing as the
    stage sets. A bye adds its points and counts in the table's Byes column, apart from the
    matches played, won and drawn. Every pair meets at most once. Such a pairing always exists
    while each entrant has met fewer than half the field, so a Swiss stage plays at most half as
    many rounds as it has entrants, rounded up.
- **Ladder.** The entrants stand on a ladder in seed order. In each round, neighbours meet, the
    first and second, the third and fourth and so on, and in the next round the second and third,
    the fourth and fifth, in turn. A challenger who wins takes the higher place, and on a draw the
    holder keeps it unless the stage settles draws as ties. After as many rounds as entrants, the
    default, the ladder sorts any order of strength.
- **King of the hill.** The top seed starts as king, and every other entrant in turn challenges
    the king. A challenger who wins becomes king, and on a draw the king stays unless the stage
    settles draws as ties. Laps set how many times the challengers come round, and from the second
    lap a dethroned king challenges too. The last king wins, and the others rank by the ties they
    won.
- **Gauntlet.** The two lowest seeds meet first, and the winner climbs to meet the next higher
    seed, step by step up to the top seed, who plays only the last match. Drawn steps settle as
    ties, or go to the higher seed when the stage says so.

The final ranking of a tournament lists the last stage in its order, then those who left in
earlier stages, later stages first. A knockout ranks the champion, the runner up, the third place
match and then the round in which each entrant went out. A double elimination ranks by the round of
the second defeat.

### Settings

Every setting below may be set for the whole tournament, as a default of every stage, and again
for one stage, which overrides the default. The standard ability, described under Abilities, is a
setting of the tournament itself.

| Setting | What it sets |
| ------- | ------------ |
| Scenario | Any scenario that every entrant can play, by default the Kaggle match, or five against five when every registered team is five a side. Stages may use different scenarios and formats, such as groups of five against five and a final of eleven against eleven, when every entrant who could reach a stage can play its scenario. |
| Match length | The steps a match lasts, from 50 to 5000, ten steps a second, or the scenario's own. |
| Ability | The ability of the stage, which every side of the stage whose entrant has no ability of its own plays with, in place of the standard ability. |
| Legs | The matches of a tie, from 1 to 10, the higher seed playing the last leg at home, and goals adding up across them. The final may have its own count. |
| Drawn ties | An ordered list of ways to settle a tie that ends level. Away goals count when the legs are even. A replay, up to five, is one more match. A deciding match plays a chosen scenario twice, such as an academy drill, each side attacking from the left once, and adds the goals of both. Lots drawn from the tournament seed always come last and always decide. |
| Points | The points for a win, a draw and a loss, any whole numbers from minus 100 to 100. |
| Tiebreakers | An ordered list of what separates entrants level on points, goal difference, goals scored, fewer goals conceded, the matches between them, wins, away goals, fair play from cards, Buchholz, the points of the opponents met, and lots from the seed, which always come last. |
| Seeding | For the first stage, at random from the seed, the default, by hand in the order of the entrants, or by rating, where equal ratings keep the order of the entrants. For a later stage, by the standing of the stage before it, at random or by rating. |
| Matches at once | How many matches of agents play at the same time, from 1, the default, to 8. |
| Forfeit score | The goals by which a match awarded by hand is won, 3 by default. |

The settings of each format, the bracket, the stop of a knockout, the third place match, the reset
of a grand final, cycles, groups, pots, qualifiers, best places, rounds, the points of a bye, laps,
what a draw does and how many advance, are described with their formats above. A setting that
cannot work, such as more Swiss rounds than allow a pairing without rematches, groups of one, a
bracket too small for its entrants, a stage that receives fewer than two entrants or a team in a
scenario of another format, is refused with a message that names the setting, the stage and why.

Ratings come from earlier tournaments. Every match that a tournament plays moves the rating of both
entrants by the Elo formula, 20 points for an upset at most, and a new entrant starts at 1500.
A match awarded by forfeit was never played, so it leaves the ratings as they are.
A registered team, the built in AI at each ability and each person by name keep their own rating.
Every entrant of one team shares the team's rating, and a match between two of them leaves it as it
is, since the team both wins and loses it. An entrant's rating may also be set by hand, and seeding
by rating uses the ratings as they stand when the tournament is made.

### The draw

Once the entrants are set, the **draw** places them, the seeds of a knockout's bracket, the pots
and groups of a group stage and the order of a Swiss, a ladder or a gauntlet. By default the draw
is random, from the tournament seed, so every entrant has the same chance of any place, and the
same seed gives the same draw again. Every preset that ships draws this way. A person who wants to
set the bracket themselves seeds by hand, with Set the bracket by hand on the Entrants step, the
seeding Manual in Settings, `--seeding manual` on the command line or `"seeding": "manual"` in a
configuration, and the order of the entrants is then the order of the seeds, the first entrant
seed 1, who meets the lowest seed in a knockout's first round. Seeding by rating stays a choice
too, for entrants with ratings from earlier tournaments. A tournament of an earlier version, whose
preset seeded by rating, keeps the draw it was made with and resumes as it was drawn.

### Determinism

The same configuration and **tournament seed** give the same draw and the same seed for every
match, whatever order the matches finish in. Each match has a key, such as `0/w4-1/2` for the second
leg of the first semi-final of the first stage, and its seed comes from the tournament seed and that
key. The draw of groups, pots, random seeding and lots each draw from the tournament seed and their
own purpose. So a tournament repeats with the same seed, and a match that a stop cut short plays
again from the start with the same seed and gives the same result.

### Presets

A preset holds a tournament's format, its stages, defaults, seeding and standard ability, without
its entrants. Every preset that ships draws its first stage at random from the seed. Those
that ship fit any number of entrants from 2 to 256. While its stages stay as the preset ships them,
a group size, a best place, a number of Swiss rounds or of entrants that advance comes down to the
most that the entrants allow, so the Swiss of 16 plays two rounds with three entrants and the
league phase sends four of five entrants on. Stages changed on the page or in a configuration are
the user's own, and a setting that the entrants cannot play is refused with the reason.

| Preset | Format |
| ------ | ------ |
| World Cup | Groups of four, the best two of each in a knockout of single matches with a third place match. |
| European Championship | Groups of four, the best two and enough of the best third places to fill a bracket. |
| Champions League | Groups of four home and away, then two legged ties settled by away goals, and a single final. |
| League phase and playoffs | A Swiss league phase of everyone, then the best eight in two legged ties. |
| Classic league | A double round robin for three points a win. |
| Round robin | A single round robin. |
| Quick 8 team cup | A knockout of short matches of 600 steps, drawn ties settled by lots. |
| Swiss of 16 | Five Swiss rounds ranked by points and Buchholz. |
| Double elimination | Winners and losers brackets with a deciding grand final. |
| League and playoffs | A round robin, then semi-finals and a final among the best four. |
| Cup with a play-in | A knockout whose lowest seeds play in, with a third place match. |
| Ladder | Neighbours meet each round, and winners climb. |
| King of the hill | Challengers try the king one after another. |
| Gauntlet | The lowest seeds climb toward the top seed. |

The page saves any format as a preset of the user, which the setup lists beside those that ship.

### The Tournaments page

The **Tournaments** page lists every tournament on its left, with its state, entrants, formats,
progress, the champion of a finished one and the matches waiting for a person. **New tournament**
opens the setup on the right, in five steps that are tabs of their own, so any step opens at any
time, and the arrow keys move between them.

1. **Format** offers the presets, those that ship and those of the user.
2. **Entrants** has Set the bracket by hand above its list, which turns the random draw into a
    draw in the order of the list and says which of the two applies, and it adds registered teams
    one at a time or every one at once, the built in AI at an ability, or four of them at rising
    abilities, and people by name, with the built in AI or a
    team of dynamic assignment as their teammates. Each entrant may be renamed, given an ability
    of its own, given a rating and moved up or down, which is the seeding when it is manual, or
    removed. A team added again, or any team whose name an entrant already shows, enters under the
    first free name, such as Rex 2, with its name field focused so the proposal can be changed at
    once. A name that repeats
    another entrant's is marked beside its field with the entrant it repeats, a person is added
    only under a name of their own, and Review lists every repeated name until each entrant has
    its own. The Ability field of each row stays empty to follow the standard, which its
    placeholder names, such as Standard, 0.80.
3. **Settings** names the tournament, takes its seed or draws one, and sets the seeding, the
    scenario and match length of every stage, the standard ability, the matches at once and the
    forfeit score. The standard ability is a slider with its value beside it, set by its Set box,
    and with the box clear the value reads as the scenario's own.
4. **Stages** is the advanced editor. It holds the standard ability too, and each stage is a card
    with every setting that its format reads, the ordered lists of tiebreakers and ways to settle
    a tie, and buttons to add, move and remove stages. A stage without an ability of its own reads
    as following the standard. Edit as JSON shows the standard ability, the stages and defaults as
    JSON to change as text.
5. **Review** checks the tournament on the server and shows the standard ability, the entrants
    with an ability of their own, each stage with its entrants, those who advance, its scenario,
    its ability and the draw of its first round or its groups, or the reason it cannot be made. It
    also saves the format as a preset. Start tournament begins it.

An open tournament shows its state, seed and progress, the matches playing now, and buttons to
cancel it, resume it after a failed match, hold its trophy ceremony, run it again with the same
settings and a new seed, or delete it, which leaves its recordings in Recordings. Its stages are
tabs. A knockout or a double elimination shows its **bracket**, one column a round, each tie between
the two that feed it, with the play-in round, the losers bracket, the grand final and the third
place match in sections of their own, and a bracket wider than the page scrolls sideways. Leagues,
groups, Swiss rounds, ladders and the challenges of a king show **tables**, with the places that
qualify marked, a caption that names the order of the tiebreakers, and a line for each entrant that
stands above another on equal points that names the tiebreaker that placed it there. **Fixtures and
results** list every round with its matches, their scores, or their state while none of their
matches has played, how a tie was decided, the progress of a match that plays, and Watch, which
opens the recording of each match. An entrant whose own ability differs from the standard shows
it beside its name in the bracket, the tables and the fixtures, such as Ability 0.30 after the
symbol of the built in AI, and the head of the tournament names its standard ability. A built in AI
whose name the rules made already holds its ability in its name. The page follows a running
tournament as it plays and announces a match that waits for a person and the end of a tournament.

A match with a person shows **Play now**, which starts it as a game of the Play page with the
tournament's scenario, length, abilities and match seed. The person's name stands on the
scoreboard, and two people in one match play the game for two. A game that reaches its end gives
the result, and the end card leads back to the tournament. A game that ends early, by Quit or a
lost page, leaves the match to be played again, and a game that the other side's policy ends
names that failure on the match, beside Play now and Award. **Award** gives a match to either side
by the forfeit score, for a person who cannot play or a team that keeps failing. It asks first in
place of the button, naming the match, the winner and the score, and Award confirms it while Cancel
or Escape leaves the match as it was. An award is final once confirmed, since the matches after it
may already have played with its winner.

A match of agents that fails shows its error and Award for either side, and waits for an award or
a retry while the matches that do not depend on it play on. Once only failed matches hold the
tournament up, it stops with the first failure as its error, which names the team whose policy
failed by the name it entered under. The notice of a stopped tournament lists each failed match
with Award for either side, and Play now waits until the tournament runs again. An award that
leaves a match to play runs it on, and Resume plays every failed match again. A failure stays a
choice of the organizer, since a team that failed under a busy machine may well play on a retry,
so the tournament awards no match by itself.

The names that the rules give show in the language of the page, the rounds and ties such as
Semi-final 1, Matchday 2 and Group A, the sides still to come such as Winner of Semi-final 1, the
built in AI at an ability such as Built-in AI 0.50 with the decimal sign of the language, the stage
names of the presets and formats, a tournament left without a name, the notes of a match and the
titles of its recordings. A name that a person typed, of a tournament, a stage or an entrant, shows
as typed, and so does the name of a registered team. The tournament files keep the English text of
each name with its message beside it, the command line prints the English text, and a tournament
of an earlier version shows its names as it saved them.

An open tournament lists **Up next** above its stages, the next matches as kickoff cards, each
with its stage and label, the two sides with their kits and the state of the match. The matches
that wait to be watched come first, in the order to watch them, and then those still to play. A
final, a grand final and its deciding match have a card of their own, marked with the trophy. Each
card takes a prediction of its result, a win for either side or a draw, which the browser keeps
and which counts once the match's result shows, so the tournament shows how many predictions came
right, such as Predictions, 2 of 3 right.

The **trophy ceremony** of a finished tournament opens the last match that the champion played on
the Watch page at its end, and holds the podium and confetti of the show after a match, with the
champion's players on the steps in the champion's colors, the champion's name, and the tournament
won with the runner up beneath it. Close ends it.

### The Brackets view

**Brackets** on an open tournament, or Brackets of a tournament in the command palette, opens its
brackets, groups and tables in a view of their own, which takes the whole width of the page with
the list of tournaments set aside and larger type. The stages are tabs as in the tournament, and
the view follows a running tournament as it plays. Zoom in and Zoom out scale the view from half
to twice its size, and Actual size returns it, so a bracket reads across a room or fits a small
window. A bracket or a table wider than the screen scrolls sideways, so the view works on a phone
too. Back to the tournament returns to the tournament where it was. A tournament without spoilers
shows in the Brackets view as it does elsewhere, with Watch next beside the zoom.

### Watching without spoilers

A tournament may be watched without spoilers, game by game, as a person follows a competition
that played while they were away. **Watch without spoilers** on an open tournament turns it on for
that tournament, and the browser remembers it, with the matches the person has watched, so it
stays on after a reload and in later visits. While it is on, nothing that tells the outcome of a
played match that the person has not watched shows. The brackets, tables, fixtures and ranking
read as if only the watched matches had played, so a side that an unwatched match decides reads
as where it comes from, such as Winner of Semi-final 1, a table counts the watched matches alone,
and the champion, the ceremony and the toast of a finished tournament wait. A played match that
waits shows Played, not watched yet, with Watch and Reveal.

**Watch next** plays the next match to watch on the Watch page, in the order of the schedule, and
the match counts as watched when its recording plays to its end, and only then does its result show
in the bracket and the tables. While it plays, the timeline leaves its goals unmarked. At its end a
card names the next match, who plays it and nothing more, with Play now and Cancel, and a final has
a card of its own. With **Play the next match by itself** on, the card counts down ten seconds and
plays the next match, and Cancel, Escape or leaving Watch stops it. **Reveal** shows the result of
one match without watching it, and **Reveal all** shows every result, after a question in place of
the button that Escape or the close button answers with no. A match awarded without a recording
reveals at once. Once every played match is watched, a summary lists the results of the matches
watched in that visit, what the person missed, with the predictions they got right.

The lists of the page keep the secret too. Home, Recordings, the Trash, the details of a recording,
the command palette and the search of moments show a recording of an unwatched match without its
score and teams, under a title that names only its tournament, such as Spring cup, a match not
watched yet, and the search of moments leaves its moments out. A match that a person plays shows
when its turn comes, as it must. Turning the switch off shows everything again, and the matches
watched stay remembered. The page asks the server for the tournament as the person sees it with
`POST /api/tournaments/ID/spoilers`, whose body names the watched matches by their keys.

### The command line and the server

```sh
cuju render tournament new --preset world_cup --name "Office cup" --seed 7 \
    --team t-20261106-101500-3fa9 --builtin 0.3 --builtin 0.8 --person Ana --run
cuju render tournament new --preset round_robin --team t-20261106-101500-3fa9 \
    --team t-20261106-101500-3fa9 --as "Reds reserves" --builtin 0.5
cuju render tournament new --preset classic_league --ability 0.8 \
    --team t-20261106-101500-3fa9 --ability 0.3 --person Ana --builtin any
cuju render tournament check --config spring.json
cuju render tournament list --json
cuju render tournament show cup-20261110-090000-1a2b
cuju render tournament run cup-20261110-090000-1a2b
cuju render tournament forfeit cup-20261110-090000-1a2b --match 0/w4-1/1 --winner away
cuju render tournament resume cup-20261110-090000-1a2b
cuju render tournament cancel cup-20261110-090000-1a2b
cuju render tournament delete cup-20261110-090000-1a2b
cuju render tournament ratings
cuju render tournament presets
```

The new command makes a tournament from a preset, `quick_cup` by default, or from a JSON file of a
whole configuration given to `--config`, with the entrants in the order of the options `--team`,
`--builtin`, with an ability or `any`, and `--person`. A team may be named more than once, and
`--as` after an entrant gives it a name of its own, so the second example enters the team Reds
as Reds and as Reds reserves. A team named again without `--as` takes the first free number, Reds
2, which `check` shows before anything is made. `--ability` before every entrant sets the standard
ability, from 0 to 1, or `scenario` to leave it to the scenario, and `--ability` after an entrant
gives that entrant its own, or `standard` to follow the standard, so the third example plays a
league at 0.8 where Reds play at 0.3. `check` and `show` print the standard ability in their first
line, a stage's ability beside its scenario and an entrant's own ability after its name, such as
Reds at 0.30. The options `--seeding`, `--scenario`,
`--length`, `--concurrency` and `--rounds`, the rounds of every Swiss or ladder stage, change the
preset, and rounds beyond what the entrants allow are refused with the most they allow. A
tournament's identifier starts with `cup-`. A running server plays a new tournament, and `run`
plays it in the terminal until it ends, stops on failed matches or waits for people, who play
their matches on the page. One process at a time runs a tournament, and a lock file beside it
names the process, so the server leaves alone a tournament that `run` plays, and the page follows
it. A cancel from either reaches the process that runs it. An award or a resume from the command
line, or from the page while `run` holds the tournament, goes to the process that runs it, which
applies it within a moment and answers. The key of a match is checked first, so a wrong one reads
as such at once. A process that gives no answer within ten seconds leaves the change undone, and
the refusal names the route of its server to send it to, such as
`POST /api/tournaments/ID/forfeit`. A tournament that stopped leaves its lock, so the command line
awards or resumes it while a server runs, and the server plays it on.

Each tournament file that the renderer writes carries a seal, a keyed digest of the file under a
key that the home folder keeps in `tournaments.key`. A running tournament whose file has no valid
seal, a file copied in from elsewhere or edited by hand, loads stopped with a note that says so, and
it plays once a person resumes it on the page or runs it from the command line, which seals its
file again. Every tournament file plays at most eight matches at once, the most that a new
tournament may ask for.

The show command prints each stage with its tables and results, a tie that has played none of its
matches as not played, and then every match still to play with its key, label, sides and state,
with the error of a failed one. `forfeit`, also named `award`, gives the match of `--match` to the
side of `--winner`, `home` or `away`, by the forfeit score, as Award does on the page, and
`resume` plays the failed matches again, as `run` also does. The check command takes the options
of new and prints each stage with its entrants, those who advance, its scenario and its first draw
or groups, and makes nothing, or the reason the configuration cannot make a tournament. A cancel
of a tournament that has ended is refused, and `delete` removes a tournament that has ended, which
leaves its recordings in the library. The ratings command lists the rating of every entrant that
has played, the highest first, with its matches and key. Every action takes `--json`, which prints
what the server returns for it, the summary of a new tournament, the summaries of `list`, the whole
tournament of `show`, `forfeit` and `cancel`, the resolved configuration and draw of `check`, the
ratings, the presets, and for `run` the `outcome`, `done`, `stopped`, `people` or `cancelled`,
beside the whole `tournament`.

The server answers `GET /api/tournaments`, `GET /api/tournaments/ID`, `GET
/api/tournaments/presets`, `GET /api/tournaments/ratings`, `POST /api/tournaments` with a
configuration, `POST /api/tournaments/check`, which resolves a configuration and returns its draw,
`POST /api/tournaments/ID/cancel`, `resume`, `play`, `forfeit` and `spoilers`, `POST
/api/tournaments/presets/NAME`, and `DELETE` of a tournament or a preset, with the same Host and
Origin checks as every other route.

| Route | Body | Answer |
| ----- | ---- | ------ |
| `POST /api/tournaments/ID/forfeit` | `{"key": "0/w4-1/1", "winner": "away"}`, the winner `home` or `away` | the whole tournament, with the match awarded by the forfeit score |
| `POST /api/tournaments/ID/resume` | `{}` | the summary of the tournament, which plays its failed matches again |
| `POST /api/tournaments/ID/play` | `{"key": "0/w4-1/1"}`, a match with a person | the game of the Play page that plays it |
| `POST /api/tournaments/ID/cancel` | `{}` | the whole tournament, cancelled |
| `POST /api/tournaments/ID/spoilers` | `{"watched": ["0/w4-1/1"]}`, the keys of the watched matches | the whole tournament as evaluated from the watched results alone, each played match that waits with `state` `unseen` and its recording in `unseen`, and `spoilers` with the keys that can be watched now in order as `unseen`, every played key as `played` and the counts `hidden` and `watched` |

A match key comes from the `matches` of `GET /api/tournaments/ID`, each with its `key`, `label`,
`home` and `away` entrants and `state`, and the summary of a tournament counts its `failed`
matches. A refused change answers 400 with the reason, and an unknown tournament 404.

### Configuration files

The option `--config` of `cuju render tournament new` and `check`, `POST /api/tournaments` and
`POST /api/tournaments/check` take a whole configuration as JSON. The page's Edit as JSON shows the
stages and defaults of the same form. A configuration that names a `preset` and has no `stages`
takes the preset's settings for those it leaves out, and the options of `new` change it as they
change a preset. Each stage starts from the defaults below, then takes the configuration's
`defaults`, then its own settings, so a setting of `defaults` reaches every stage that leaves it
out.

```json
{
  "name": "Spring league",
  "seed": 7,
  "seeding": "rating",
  "concurrency": 2,
  "ability": 0.6,
  "entrants": [
    {"kind": "team", "team": "t-20261106-101500-3fa9", "name": "Reds", "ability": 0.9},
    {"kind": "builtin", "ability": 0.3},
    {"kind": "builtin", "ability": 0.8, "rating": 1600},
    {"kind": "person", "name": "Ana"}
  ],
  "defaults": {"scenario": "5_vs_5", "length": 600},
  "stages": [
    {"format": "swiss", "name": "Swiss", "rounds": 2, "bye_points": "draw", "advance": 2,
     "tiebreakers": ["buchholz", "goal_difference", "head_to_head", "lots"]},
    {"format": "knockout", "name": "Final", "legs": 2, "final_legs": 1,
     "settle": ["away_goals", "decider", "lots"]}
  ]
}
```

This makes a Swiss stage of two rounds among four entrants, a bye worth a draw, whose best two
meet in a final of one match, settled by away goals, a deciding match and lots in turn. The players
that Reds leave to the built in AI play at 0.9, the two built in AI entrants at 0.3 and 0.8, and
the teammates of Ana at the standard of 0.6.

| Key of the tournament | Value | Default |
| --------------------- | ----- | ------- |
| `name` | text of 1 to 80 characters | `Tournament` |
| `seed` | a whole number from 0 | drawn at random |
| `entrants` | a list of 2 to 256 entrants, as the next table describes | |
| `seeding` | `random`, `manual` in the order of the entrants, or `rating` | `random` |
| `concurrency` | the matches of agents at once, 1 to 8 | `1` |
| `forfeit_score` | the goals of an awarded match, 1 to 10 | `3` |
| `ability` | the standard ability from 0 to 1 of every entrant and stage that sets none | null, the scenario's own |
| `defaults` | stage settings for every stage | `{}` |
| `stages` | a list of 1 to 8 stages, as the last table describes | |
| `preset` | the name of a preset, which fills what the configuration leaves out | none |

| Key of an entrant | Value |
| ----------------- | ----- |
| `kind` | `team`, `builtin` or `person`, `team` when absent |
| `team` | the identifier of a registered team, for a team |
| `ability` | from 0 to 1, the ability of the built in AI players of the entrant's side, for every kind of entrant, or null to follow the stage and the standard |
| `name` | the name the tournament shows, up to 40 characters and unique within the tournament without regard to case or spaces, by default the team's name or Built-in AI with its ability, numbered from 2 when another entrant holds it, and required for a person |
| `teammates` | `builtin` or a registered team of dynamic assignment, for a person |
| `rating` | a rating from 0 to 10000 that replaces the one of earlier tournaments |

| Key of a stage | Formats | Default | Value |
| -------------- | ------- | ------- | ----- |
| `format` | all | `knockout` | `knockout`, `double_elimination`, `league`, `groups`, `swiss`, `ladder`, `king_of_the_hill` or `gauntlet` |
| `name` | all | the format's name | text of up to 60 characters |
| `scenario` | all | the Kaggle match, or `5_vs_5` for teams of five a side | a scenario of the scenario list |
| `length` | all | null, the scenario's own | steps from 50 to 5000 |
| `ability` | all | null, the standard | the ability from 0 to 1 of every side whose entrant sets none |
| `legs` | all | `1` | the matches of a tie or meeting, 1 to 10 |
| `final_legs` | `knockout`, `double_elimination` | null, as `legs` | the matches of the final, 1 to 10 |
| `settle` | `knockout`, `double_elimination`, `ladder`, `king_of_the_hill`, `gauntlet` | `["replay", "lots"]` | an ordered list of `away_goals`, `replay`, `decider` and `lots`, which always comes last |
| `replays` | as `settle` | `1` | replays at most, 1 to 5 |
| `decider_scenario` | as `settle` | `academy_run_to_score_with_keeper` | the scenario of a deciding match |
| `decider_length` | as `settle` | null, the scenario's own | steps from 50 to 5000 |
| `points` | `league`, `groups`, `swiss`, `ladder`, `king_of_the_hill` | `{"win": 3, "draw": 1, "loss": 0}` | whole numbers from minus 100 to 100 |
| `tiebreakers` | `league`, `groups`, `swiss` | `["goal_difference", "goals_for", "head_to_head", "wins", "fair_play", "lots"]` | an ordered list of `goal_difference`, `goals_for`, `goals_against`, `head_to_head`, `wins`, `away_goals`, `fair_play`, `buchholz` and `lots`, which always comes last |
| `seeding` | a later stage | `standing` | `standing`, `random` or `rating` |
| `bracket` | `knockout` | `byes` | `byes` or `play_in` |
| `bracket_size` | `knockout`, `double_elimination` | null, from the entrants | a power of two |
| `until` | `knockout` | `1` | a power of two below the bracket size, the entrants that remain |
| `third_place` | `knockout` | `false` | `true` or `false` |
| `grand_final_reset` | `double_elimination` | `true` | `true` or `false` |
| `cycles` | `league`, `groups` | `1` | the times each pair meets, 1 to 10 |
| `groups` | `groups` | null, from `group_size` | the number of groups |
| `group_size` | `groups` | `4` | entrants of a group, from 2 |
| `group_sizes` | `groups` | null | a list of sizes that add up to the entrants |
| `pots` | `groups` | null, the largest group size | the pots of the draw |
| `qualifiers` | `groups` | `2` | a count for every group, or a list of one count a group |
| `best_position` | `groups` | null | a place whose best entrants across the groups also qualify |
| `best_count` | `groups` | `0` | how many of them, or `"fill"` for enough to fill a bracket |
| `rounds` | `swiss`, `ladder` | null, from the entrants | Swiss rounds up to half the entrants rounded up, ladder rounds up to 1000 |
| `laps` | `king_of_the_hill` | `1` | the times the challengers come round, 1 to 10 |
| `bye_points` | `swiss` | `win` | `win`, `draw` or `none` |
| `draws` | `ladder`, `king_of_the_hill`, `gauntlet` | `holder`, or `settle` for a gauntlet | `holder` or `settle` |
| `advance` | every stage but the last | from the format | the entrants that go on to the next stage |

### Files

Each tournament lives in a JSON file of the folder `tournaments`, with its resolved configuration,
the result of every match and its state, written through a temporary file. A file that cannot be
read is skipped with a warning, and the server starts with the rest. A restart of the server
resumes every running tournament where it stopped, and a match that was playing plays again from
its start with the same seed. The ratings and the presets of the user live in `ratings.json` and
`presets.json` of the same folder. A match length writes a small scenario file into the folder
`scenarios`, which plays the shipped scenario for that many steps, with the second half starting at
the same share of the match.

The file of a tournament keeps the names that its rules gave each entrant, so a tournament made
by an earlier version, sealed or not, loads, resumes and plays to its end as it did, even where the
rules of now would number or refuse a name of its entrants.

## Challenges

A **challenge** is a short drill with a clear goal and three targets, bronze, silver and gold, that
a person plays on the Play page and an agent plays headless, faster than real time, by the same
rules. Every academy scenario of GRF is a challenge, and the scenario `1_vs_1_easy` makes two more,
One on one at the scenario's ability and One on one, hard, against a right side at ability 1.0.

Each challenge plays a fixed number of attempts, and each attempt plays a seed of its own from a
fixed sequence, the same for every person and every agent, so all results are comparable. Attempt
`i`, counted from zero, plays the seed `(crc32(id) + 7919 * i) % 2**31`, where `id` is the
identifier of the challenge in UTF 8 and `crc32` is the checksum of Python's `zlib.crc32`. The
catalog lists the seeds of every challenge. The controlled side is always the left one, and the
built in AI plays everyone else. A person's attempt is the game `{scenario}_l1_r0` with that seed,
so a team of one dynamic agent faces the very episode that a person faces.

The measure of a challenge reads its attempts in one of three ways, and a higher value is always
better.

- **Scored** counts the attempts in which the left side scored.
- **Within** counts the attempts in which the left side scored within a limit of seconds of play.
- **Margin** adds up the goals for minus the goals against over all attempts.

Seconds of play run from the first frame of an attempt to the frame of its goal, at ten steps a
second, whatever the game clock shows. Two runs of the same value rank by their total seconds to
score, the lower first, adding the attempts that count, and then by the time of the run, the
earlier first. An attempt that ends before its episode does, when a person quits it, counts its
goals against and no goals for, so quitting never helps. An attempt that a person leaves before its
first step has no recording and counts as missed.

| Challenge | Kind | Difficulty | Scenario | Attempts | Measure | Bronze | Silver | Gold |
| --------- | ---- | ---------- | -------- | -------- | ------- | ------ | ------ | ---- |
| Empty goal from close range | Finishing | Easy | `academy_empty_goal_close` | 5 | Within 3 seconds | 3 | 4 | 5 |
| Empty goal | Finishing | Easy | `academy_empty_goal` | 5 | Within 8 seconds | 3 | 4 | 5 |
| Run to score | Dribbling | Medium | `academy_run_to_score` | 5 | Within 6.5 seconds | 1 | 3 | 5 |
| Run to score past a keeper | Dribbling | Medium | `academy_run_to_score_with_keeper` | 5 | Scored | 1 | 3 | 5 |
| Pass and shoot past a keeper | Combination play | Medium | `academy_pass_and_shoot_with_keeper` | 5 | Scored | 1 | 3 | 5 |
| Run, pass and shoot past a keeper | Combination play | Hard | `academy_run_pass_and_shoot_with_keeper` | 5 | Scored | 1 | 3 | 5 |
| Three against one | Combination play | Medium | `academy_3_vs_1_with_keeper` | 5 | Scored | 1 | 3 | 5 |
| Corner | Set piece | Hard | `academy_corner` | 5 | Scored | 1 | 2 | 4 |
| Counterattack | Counterattack | Medium | `academy_counterattack_easy` | 5 | Scored | 1 | 3 | 5 |
| Counterattack, hard | Counterattack | Hard | `academy_counterattack_hard` | 5 | Scored | 1 | 2 | 4 |
| Single goal against a lazy team | Breaking through | Easy | `academy_single_goal_versus_lazy` | 5 | Within 30 seconds | 2 | 4 | 5 |
| One on one | Duel | Medium | `1_vs_1_easy` | 3 | Margin | 1 | 3 | 6 |
| One on one, hard | Duel | Hard | `1_vs_1_easy` | 3 | Margin | 1 | 2 | 4 |

The targets come from runs of the built in AI on the whole left side and of simple agents that run
at the goal and shoot, so bronze asks for a little better than standing still and gold for a clean
run.

Every challenge lists its medals as three items, Gold, Silver and Bronze in that order, and each
item names its medal and its target in plain words and numbers, such as Gold, 6 goals or more
ahead for One on one, Silver, a goal in 2 attempts or more for Corner, or Gold, a goal within 3
seconds in all 5 attempts for Empty goal from close range. A target that asks for a goal in every
attempt says all, and any other says or more, since a value at or above a target wins its medal.
A run or a competitor's best marks the item of the best medal it won, and no item when it won
none. The catalog holds the items as `medals`, each with its `medal`, its `target`, `every` for a
target of every attempt and `reached`, and a run's result holds them with the item it reached
marked. `cuju render challenge list` prints them under each goal.

Each challenge has a kind, which says what the drill trains, and a difficulty, easy, medium or
hard, which weighs its targets and the defenders it faces. Finishing asks for a clean shot at an
empty goal, Dribbling for a run past chasing defenders, Combination play for a pass that frees a
teammate, Set piece for a goal from a corner, Counterattack for a quick attack against few
defenders, Breaking through for a way past a defense that stands still, and Duel for a short match
of one player against one. The catalog names them as `category` and `difficulty`, with the
identifiers `finishing`, `dribbling`, `combination`, `set_piece`, `counterattack`, `breakthrough`
and `duel` and the levels `easy`, `medium` and `hard`, and `cuju render challenge list --json`
prints them with the rest of each challenge.

### On the Play page

The setup card of Play holds a Challenges section under the Play button. A field takes the person's
name for the leaderboards, which the browser keeps once the person types one. A person who types
none plays under the default name of the page's language, Player in English, and the page shows
that default in its own language wherever the name shows, on the leaderboards, in the titles of the
grouped recordings and on the cards, even for runs saved while the page spoke another language. A
run keeps the name it was saved with, and a new run under the default says so in `default_name`,
while an older one counts as the default when its name is the default of a language that the
server knows. Every person under a default name is one competitor. Each challenge shows its goal, its
scenario, its medals as items, the ability of the built in AI on each side, the person's best run
with its medal and rank, and the leader of its board. Start challenge plays the first attempt as a game of
the challenge's scenario, seed and ability, with Save to Recordings on and the person on the left
alone. The end card of each attempt shows the attempt's result, which the server scores from the
saved recording, and offers Next attempt, Watch it and Leave challenge. After the last attempt the
page sends the run to the server, the person's name and the recordings in order, and the end card
shows the value with the seconds that its counting attempts took to score in all, the medal, the
medal items with the one this run reached marked This run, the personal best or, for the person's
first run, its place on the board, the rank and any achievements, with Try again. A run in which no attempt counted shows its value alone. An
achievement earned again in a run shows on the first end card that earns it. Leave challenge and
the Challenges button of the last end card return to the setup with the focus on the challenge
just played, and each button of a challenge names its challenge for screen readers. A
setup card that opens while a run is under way, after Esc on an end card for example, names the run
and offers Next attempt and Leave challenge.

Keep attempts as recordings, a setting of the section that the browser keeps, is on by default,
and the attempts of each run then gather in one group of the Recordings page. With the setting
off, a run scores, ranks and earns exactly as with it on, and leaves the library as it was. The
attempts of a person's run still save their recordings while the run plays, since the server
scores each attempt from its recording, and the server removes them for good once it has scored
the whole run, so the end card of such a run offers no Watch it. A run that a person leaves before
its end hands its attempts to the server as well, which keeps them as the group of a left run, or
removes them when the setting is off. The setting applies to the headless runs that the section
starts too.

The server scores every recording of the run again and checks that each one fits its attempt, a
game of the Play page with the challenge's scenario and abilities, the seed of the attempt, a
person on the left alone and the built in AI on both teams, and that each recording counts once.
A run that fails a check stays off the board, and the end card names the reason.

Leaderboard opens the board of a challenge below it, with the rank, the competitor marked as a
person by the symbol of a person or as a model by the symbol of a robot, with its kind, a team or
a Python policy, the value, the seconds to score, the medal by its symbol in its metal's color and
its name, and the date of each best run, and the seeds of the attempts. The keyboard and a controller work every control of the section, as they
work the rest of the setup card.

### The cards

The Challenges section lists every challenge as a card, and each card shows what its challenge is
before a run starts. The card opens with a picture of the drill, a still of its first moments that
shows where the players and the ball stand, and over the picture sit the kind of the challenge, in
its own color with its own symbol, the difficulty as a badge of one, two or three bars with its
word, and the medal of the person's best run, when there is one. The kinds share one design and
differ in their color, their symbol and the pattern drawn behind a card whose picture cannot load,
and the colors keep the contrast that the Web Content Accessibility Guidelines ask of text at
level AA in the light and the dark theme. A hard challenge carries a dashed line of its color
along the foot of its picture.

Under the goal, each card lists its medals as items, each with the symbol of a medal and the
medal's name in the color of its metal, gold, silver or bronze, and its target. Each metal has a
color for the dark theme and one for the light theme, and both keep a contrast of 4.5 to 1 or
more on every surface of their theme, the level AA that the guidelines ask of text, so the color
adds to the words and never stands for them. The item of the person's best medal carries a check
and Your best, and a screen reader reads the list by the challenge's name, as Medals of the
challenge, with each item as its words.

A short teaser of the challenge, three to five seconds of the built in AI or of a simple scripted
player meeting its goal, plays over the still while the pointer rests on the card or while the
keyboard focus is on one of its buttons, and stops and returns to the still once the pointer and
the focus have left. Only one teaser plays at a time, so a teaser that starts stops any other. The
play button at the foot of the picture starts and stops the teaser by hand, by mouse, touch or
keyboard, and says whether it plays. Under reduced motion, from the system or from Motion in the
settings, no teaser starts by itself, the card keeps its still, and the play button alone starts
one. A teaser never makes a sound, since its video is silent and the page plays it muted, and it
stays out of the way of screen readers, which read each card by its title, the challenge's name.
A card whose teaser is missing keeps its still, and a card without a still draws the pattern and
symbol of its kind, so every card stays whole.

The stills load as they come into view, and each teaser loads when it first plays. The teasers are
H.264 videos in MP4, 480 by 270 pixels at 24 frames a second and silent, and the stills are WebP
pictures of the same size, all of them made ahead of time and shipped with the page in
`web/assets/challenges/`, about 2.5 MB in all. The manifest of the folder, `manifest.json`, maps
each challenge to its files with the SHA-256 and the size of each, and records how each teaser was
made, the policy, the seed and its place in the seeds tried, the goal and the range of each attempt
shown.

The script `ci/make_challenge_teasers.py` of the repository makes them again, by hand, with
Chrome or Edge and ffmpeg. It plays each challenge on the challenge's own seeds with the built in
AI, or with a simple scripted player where the built in AI never meets the goal, records the first
attempts that meet it with `cuju.render.Recorder`, and exports each teaser with `cuju render video`.

### Agents

Agents play challenges headless, through the same runner that plays a team in a game, which waits
for each answer, so a run goes as fast as the policy answers. A policy has 120 seconds to load and
to give its first answer, and 60 seconds for every later answer. A headless run of the page, of
the command line or of a benchmark, which the next section describes, treats a policy that fails,
stops answering or answers with anything but actions as the end of that attempt alone. The attempt
ends at the step where the policy failed and counts as an attempt that ended early, its goals
against and no goals for, so a failure never helps. Its result says `failed` with the policy's
error in `error`, `error_id` and `error_values`, its recording keeps the frames played so far with
`failed` in its provenance, and the next attempt loads the policy again, so the run goes on to its
end and reaches the leaderboard. A policy that cannot load at all fails every attempt of the run.
The result counts its failed attempts in `failed_attempts`. Each attempt plays in a batch
of one environment with the challenge's seed and abilities and the action set that a requested
match would choose for the team, and becomes a recording of the library whose provenance names the
source `challenge`, as described under Recording format. The recordings of a run form one group,
as [Recordings](#recordings) describes, and the result names it in `group`.

`keep_recordings=False` in Python and `--no-recordings` on the command line play a run without
recordings. Such a run scores, ranks and earns from the same frames as one that keeps them, and
adds nothing to the library. Its attempts then name no recording, `match` is `None` in each of
them, and `group` is `None`.

A run with fewer attempts than the challenge's count is practice. It is scored and saved as
recordings, wins no medal and stays off the leaderboard. A full run reaches the board, which keeps
the best run of each competitor as its personal best, a person by name, a team of the registry by
its identifier and a Python policy by its name, and holds the best 100 competitors. A registered
team may be `builtin`, GRF's built in AI on the whole side without any agent.

A Python policy goes by the name that `name` gives, by default its function's name, and a function
without a name of its own, such as a lambda, plays as Python policy. The board marks each
competitor as a person, a team or a Python policy, so a policy that shares a team's name ranks
apart from the team. A search by `team:` reads the names in the recordings, so it finds both, and
a name of its own keeps the policy apart there too.

From the Play page, the team list and Attempts of the Challenges section and Run headless on a
challenge start a run on the server, in a process of its own, one at a time. The line above the
list follows the run attempt by attempt with a bar of the attempts played, Cancel run ends it, and
the result shows its value, medal and rank when it is done, with the medal items and the one the
run reached marked Reached, and the count of failed attempts when there are any. The run reaches
the leaderboard under the team's name, marked as a model.

From the command line, `cuju render challenge list` prints the catalog, and
`cuju render challenge run` with a challenge's identifier and a team plays it, as does the
identifier alone after `challenge`, printing each attempt with its seed, its goal and its
recording, and a failed attempt with the policy's error, then the value, the medal, the medal
items, the rank and the personal best. An attempt that scored after the time
limit of its challenge says so, and a run whose attempts all fall short says that no attempt
counts in place of the seconds to score. `--json` prints the catalog, or the whole result of a run
as `cuju.render.challenge` returns it, once the run has ended.

```sh
cuju render challenge list
cuju render challenge run empty_goal_close --team t-20261106-101500-3fa9
cuju render challenge one_on_one --team builtin --attempts 1 --device cpu
cuju render challenge run empty_goal_close --team builtin --attempts 1 --json
cuju render challenge run corner --team builtin --no-recordings
```

From Python, `cuju.render.challenge` plays a challenge with a team of the registry or with any
Kaggle style agent function, and returns a plain dictionary of the run. A function plays one player
of dynamic assignment by default, and `control` takes the control settings of a team in its place.
`cuju.render.challenges` returns the catalog. A policy that fails, answers with anything but actions
or stops answering raises `cuju.render.PolicyError`, an `Error` of cuju and a `RuntimeError`, whose
message names the policy and the reason in one line, with the policy's own error as its cause.
`fail_attempts=True` plays as the page and the command line do, so such a policy fails its attempt
alone and the run goes on. The
result's `achievements` lists what a team of the registry keeps from the run, and stays empty for
the built in AI and for a Python policy, which keep none.

```python
import cuju.render


def agent(obs):
    return [12]


result = cuju.render.challenge('empty_goal_close', policy=agent, name='Always shoot')
print(result['value'], result['medal'], result['rank'])
for attempt in result['attempts']:
    print(attempt['seed'], attempt['seconds'], attempt['match'])
```

### Benchmarks of models

A **benchmark** plays one or several models, the registered teams that requested matches and
tournaments play, on several or all challenges as one job, and compares them in one table. Each
pair of a model and a challenge plays as a full headless run, exactly as Run headless plays it,
in a process of its own, with the challenge's scenario, abilities, fixed seeds and scoring. A
model's value on a challenge therefore compares with a person's value on it, and the same model
on the same seeds gives the same value, seconds and medal on every machine, as long as its policy
answers within its time limits and plays the same way on the same observations. Since every run
has a process of its own, no model's run sees the state of another, such as a module or a global
variable that a submission leaves behind. A policy that fails ends its attempt alone, as described
under Agents, and a run that ends without a result, such as one whose process stops, leaves its
cell failed with the reason, so the job always goes on to the next pair. A model that cannot play
a challenge, such as a team of several players on the one on one, skips that challenge with the
reason. Each run of a benchmark reaches the leaderboard of its challenge as any full run does,
under the team's name and marked as a model, apart from people.

The Challenges section of Play holds Benchmark models under the cards. Its Models list takes one
or several teams of the registry, GRF's built in AI among them, and its Challenges list takes
several or all challenges, with All challenges to choose or clear them at once. Keep the attempts
of the benchmark as recordings, off by default, keeps every attempt in the library as the group of
its run. Run benchmark starts the job on the server, which plays one benchmark at a time, and a
bar and a line follow the runs done and the share of the attempts played, while Cancel benchmark
ends it, so the runs that were left never start. The table of models by challenges fills in as
each run ends, each cell with the run's value and its medal by symbol and name, the count of failed
attempts when there are any, or its state and reason, and each row ends with the model's gold,
silver and bronze medals, its score and its place. Export JSON saves the benchmark as the server
answers it, and Export CSV saves the table.

The **score** of a model is the mean, over the challenges of the benchmark, of the share of each
gold target that its value reached, from 0 to 1, times 100 and rounded to one decimal. A value at
or above the gold target counts 1, a value of 3 on a gold target of 6 counts 0.5, a value at or
below zero counts 0, and so does a cell that skipped, failed or was cancelled, so a score of 100
means gold on every challenge. Models place by score, then by their gold, silver and bronze medals
in that order, and models level on all four share a place. The CSV has one row for each model, in
the order chosen, with the columns `model`, the team's name, `team`, its identifier, then
`<challenge> value` and `<challenge> medal` for each challenge, empty for a cell without a result,
and `gold`, `silver`, `bronze`, `score` with one decimal and `place`. Python's `csv` module and
the page write it alike, in UTF 8 with a comma between fields and quotes around a field that holds
a comma, a quote or a line break.

The server plays several runs of a benchmark at once, one for every four logical processors of the
machine by default, from 1 to 4, which `workers` sets from 1 to 8. Each run waits for its policy's
answers and plays no faster than they come, so a benchmark goes as fast as the models and the
processors allow. The server keeps its benchmarks in memory, every waiting or running one and the
newest 20 that ended.

`cuju render challenge bench` plays a benchmark from the command line, with `--team` once for each
model and `--challenge` once for each challenge, every challenge when none is named, and
`--workers`, `--device`, `--keep-recordings` and `--json` or `--csv`. Each run still plays in a
process of its own, and its end prints a line on standard error. The table goes to standard output,
each model with its place, score and medals and each of its challenges with its value and medal,
or the whole benchmark as JSON under `--json`, or the CSV under `--csv`. Ctrl+C ends the runs and
exits with 130.

```sh
cuju render challenge bench --team t-20261106-101500-3fa9 --team builtin
cuju render challenge bench --team t-20261106-101500-3fa9 --challenge corner --challenge one_on_one --json
cuju render challenge bench --team builtin --challenge empty_goal_close --csv > table.csv
```

A benchmark of the server or the command line holds `teams`, `challenges` in the order of the
catalog, `models` with each model's `team` and `name`, `cells` with one entry for each pair,
`rows` with each model's `gold`, `silver`, `bronze`, `score`, `done` and `place`, `progress` from
0 to 1, `keep_recordings`, `workers` and `device`, and on the server its `id`, `state`, `created`,
`ended` and error fields. A cell holds its `team`, `challenge`, `state`, one of `queued`,
`running`, `done`, `failed`, `skipped` and `cancelled`, its `attempts` and the attempts `played`,
its `value`, `seconds`, `medal`, `rank`, `failed_attempts` and `group`, the `results` of its
attempts as a run returns them, and `error`, `error_id` and `error_values` for a cell that failed
or skipped.

### Scripts

Scripts and agents that drive the page reach challenges through `window.cuju.challenges`, which
exists once the Play page has opened, as `cuju.showPage('play')` does for a script.

| Call | Effect |
| ---- | ------ |
| `await list()` | the catalog, with each board's size, leaders and the person's best run |
| `await board(id)` | the leaderboard of a challenge |
| `await start(id, { name })` | start a person's run and play its first attempt |
| `await next()` | play the next attempt once the last one has ended |
| `leave()` | leave the person's run |
| `await run(id, { team, attempts, keepRecordings })` | start a headless run of a team on the server, which keeps its recordings as the setting of the section says unless `keepRecordings` says otherwise |
| `await jobs()` and `await cancel(job)` | the headless runs, and the end of one |
| `await score(id, match, attempt)` | the result of a recording as an attempt |
| `await achievements()` | the catalog of achievements, the person's and every team's |
| `state()` | the person's run so far and the headless runs |
| `await bench(teams, { challenges, keepRecordings, workers })` | start a benchmark of the teams on the challenges, every one by default, and follow it in Benchmark models |
| `benchJob()`, `benchTable()` and `benchCsv()` | the benchmark that the section follows, its table of rows and cells, and its CSV |
| `await benches()` and `await cancelBench()` | the benchmarks of the server, and the end of the one the section follows |

The server's routes are `GET /api/challenges`, with `?person=` for a person's best runs,
`GET /api/challenges/<id>` for a board, `GET /api/challenges/<id>/score?match=&attempt=` for one
attempt, `POST /api/challenges/<id>/runs` with `person` and `matches` for a person's run or `team`
and `attempts` for a headless one, each with `keep_recordings` false for a run without recordings,
`POST /api/challenges/<id>/leave` with `person`, `matches` and `keep_recordings` for the attempts
of a run that a person left, both with `default_name` true for a person who typed no name,
`GET /api/challenges/names` for the default names of every language that the server knows,
`GET /api/challenges/jobs`, `GET /api/challenges/jobs/<job>` and `DELETE /api/challenges/jobs/<job>`. The benchmarks have `POST /api/challenges/benches` with
`teams`, a list of team identifiers, and the optional `challenges`, a list of challenge
identifiers, `keep_recordings`, false by default, and `workers`, which answers the new benchmark
with 201, `GET /api/challenges/benches` for every benchmark, newest first,
`GET /api/challenges/benches/<bench>` for one, `GET /api/challenges/benches/<bench>/table.csv` for
its table as CSV and `DELETE /api/challenges/benches/<bench>` to cancel it. They pass the same
checks of host and origin as every other route, and an agent benchmarks its own models with them
as follows.

```sh
curl -s -X POST http://127.0.0.1:8780/api/challenges/benches \
    -H 'Content-Type: application/json' \
    -d '{"teams": ["t-20261106-101500-3fa9", "builtin"], "challenges": ["corner", "one_on_one"]}'
curl -s http://127.0.0.1:8780/api/challenges/benches/b-20261111-120000-3fa9
curl -s http://127.0.0.1:8780/api/challenges/benches/b-20261111-120000-3fa9/table.csv
```

## Achievements

**Achievements** mark moments of a game, and people on the Play page and teams of the registry
earn them by exactly the same rules, which read the frames of a recording. A person earns them in
every game on Play, saved or not, and in challenges. A team earns them in requested matches, in
challenges and in anything else that plays it, such as a tournament, and the built in AI earns
none.

| Achievement | Rule |
| ----------- | ---- |
| Off the mark | the side scores a goal |
| Hat trick | one player of the side scores three goals or more |
| Straight from the corner | a goal within ten seconds of the side's own corner, with play running on and no other restart in between |
| From the spot | a goal within ten seconds of the side's own penalty, in the same way |
| Goalkeeper goal | the side's goalkeeper scores |
| Screamer | the scorer's last touch before the goal came 25 meters or more from the goal |
| Giant slayer | a win against the built in AI playing at ability 1.0 |
| Comeback | a win after trailing |
| Clean sheet | a finished full match without a goal conceded |
| Rout | a win by five goals or more |
| Last gasp | a win whose decisive goal falls in the last tenth of a match of a minute or more |
| On the podium | a medal in a challenge |
| Gold standard | a gold medal in a challenge |
| Academy graduate | a gold medal as the best run of every challenge |

The scorer of each goal comes from the engine's scorer bits of the frame flags, and a scorer of the
other team scored an own goal, which counts as a goal of the side but for none of its players, as
in the statistics of the post-match show. A corner or a penalty belongs to the side whose attacking
end holds the ball during the restart. A win counts only in a finished episode, one whose last
frame has the episode end flag, of a scenario outside the academy. The decisive goal is the goal
that takes the winner one goal past the loser's final total, as for Late winner of the show, and
Hat trick and Clean sheet keep the meanings that they have there, over the whole recording.

The end card of a game on Play names the achievements of the game, the new ones first, and the end
card of a challenge adds those of its medal. The Challenges section closes with an Achievements
list of every achievement, earned or not, with the count and the date of the first time, for the
person or for any team of the registry. The person's achievements stay in the browser, and a
team's stay with the server in a JSON file of its own, which holds for each achievement the first
time, the count and the recording of the first time. `GET /api/achievements` returns the catalog
and every team's achievements.

Requested matches, challenges and tournaments award their teams as each recording is saved, and
`cuju.render.challenge` returns what a team of the registry keeps from a run.

## Learning the renderer

The Help page opens with a part for learning by doing, Learn by doing, above the keys and the
guides. It holds the guided tour, the lessons to do by hand with their progress, the samples that
cuju ships, the diagnostic report and the installable page. People and AI agents learn the same
lessons in the same order, a person on the page and an agent from the command line, from Python or
from a script that drives the page, and every lesson ends by the same rule for both.

### The guided tour

The **guided tour** walks through the pages one step at a time and points at the real control of
each step with a ring around it. It visits Home and the command palette, the Match menu, the
timeline and the View menu of Watch, the Play button and the Challenges section of Play, the team
list of Teams, New tournament of Tournaments, the Settings button and the Learn by doing part of
Help, eleven steps in all. Each step opens its page, names the step and its number, and says in a
sentence what the control does and the key that reaches it.

The tour shows as a card beside its control, below it when there is room, above it near the
bottom of the window, and at its side when the control is taller than the room left. A part of
the page larger than the window has its ring around the part in view. The card keeps clear of its
control and of whatever opens over the page, a menu, a popover, the command palette, a panel or a
dialog. When the side it would take is covered, it moves to the next side that is clear, and when
none is, it waits in the corner of the window farthest from them, a little smaller when the room
there asks for it. It moves as soon as a menu opens or closes, at once under reduced motion. The
card is a dialog that leaves the page usable, so the control it points at works while the card
shows, and the focus and the Tab key move freely between the card and the page. A control outside
the window scrolls to its middle, and scrolls back while the page settles for a moment after the
step shows. The focus moves to the title of the card at each step, so a screen reader hears the
title, and then hears the number and the text of the step once. Next and Back move through the
steps, and so do the Right and Left arrows while the card has the focus. Finish on the last step
ends the tour. Esc, or Leave the tour, closes it from the card, and from the page whenever no menu,
palette or dialog is open over it, and the page then says at which step it stopped.

**Try it** shows on the steps whose control has something to try in place. On the command palette,
the Match and View menus of Watch, New tournament and Settings, it opens what the control opens,
just as a click on it would, and the focus moves into the palette, the menu or the panel, so the
arrows, Enter and Esc work there as usual. Esc then closes the menu first, and a second Esc leaves
the tour. On the timeline, Try it moves the focus to the timeline and says that Left and Right seek
five seconds, and thirty with Shift. The other steps point at the logo, which leads to the Home
page the step already shows, at Play, which starts a match, at the team list, whose additions
upload a folder, and at the headings of Challenges and Help, so their cards leave Try it out.

A step that needs a recording, such as the timeline, offers Open the sample match when nothing
plays, which adds the five a side sample to the library when it is missing, restores it from the
Trash when it lies there, and opens it on Watch. The step of Teams offers Add the starter team
while the registry holds the built in AI alone. A step whose control has not appeared says that
the control shows once its page has it, and the tour goes on.

The tour starts from Take the guided tour on Help, from the button Take the tour of the tip of a
first visit, and from the command palette, whose entry reads Take the guided tour. The browser keeps
the step reached, so a tour left midway resumes there, and Help then offers Resume the tour at step
with its number, beside Start the tour again. Under reduced motion the ring and the card move to
each step at once.

### Lessons

The **lessons** ask the person to do one thing each and notice from the page's own state when it
is done. There are eight, in this order.

| Lesson | Asks the person to | Done when |
| --- | --- | --- |
| Open a recording | open a recording on Watch | a recording plays on Watch |
| Jump to a goal | jump to a goal with N, the Match menu or the timeline | a jump of the timeline lands from eight seconds before a goal to four seconds after it |
| Switch the camera | choose another camera with V or the View menu | a camera that a person chooses replaces the first one of the lesson |
| Follow a player | follow one player with a number key, P or the View menu | the camera follows a player, as Follow player, the player on the ball or first person |
| Play for 30 seconds | play a game on Play | the game has played 300 steps, 30 seconds of match time |
| Register a team | upload a submission or add the starter team | the registry holds a team besides the built in AI |
| Start a challenge | start a challenge on Play, by hand or headless | a run of a challenge is under way |
| Make a photo | make a photo in photo mode | photo mode captures or saves a new photo |

Start the lessons on Help begins the first lesson not done, and Start on each lesson of the list
begins that one. A lesson opens its page and shows a small panel in the lower right corner, with
the lesson's number, its title and what to do. A lesson that needs a recording offers Open the
sample match, Register a team offers Add the starter team, and a lesson on another page than the
one in view offers to go there. The panel looks at the page a few times a second, and once the
thing is done it says so with a line about what to try next, and Next lesson goes on. Skip leaves
a lesson for later. During a game on Play the panel keeps only its status line, which counts the
seconds played. Esc closes the panel while it has the focus, and Close does the same.

A lesson counts only what a person does. A jump counts when the timeline moves more than playing
explains, so playing up to a goal leaves the lesson open, and the shows of the page, the lineups
and replays among them, move the camera through modes of their own that no lesson counts.

The browser keeps the lessons done, with the time of each, and Help shows how many are done and
marks each one. Reset the lessons forgets them all, and the page then starts again from the first.
Every lesson done is also reported to the server, which keeps the lessons that only a page can
check, so the command line sees them as well. Those four lessons, Jump to a goal, Switch the
camera, Follow a player and Make a photo, are watched even while no lesson is under way, so a
person or a script that does one of them on the page completes it, and a replay or the show after
the match leaves Jump to a goal open there. On loading, the page takes in every lesson the server
knows done, so a new browser shows the same progress as the command line.

### The tutorial for agents

`cuju render tutorial` gives an agent the same eight lessons as steps of the command line, of
Python, of the HTTP routes and of the page's scripts, and checks each lesson from the state of the
renderer's home folder. It prints every lesson with whether it is done, its goal and its steps,
then the next lesson to do. A lesson's identifier prints that lesson alone, `--json` prints the
same as JSON, and `--check` makes the command end with status 2 while the lessons shown are not
all done, so a script loops until they are. `--reset` forgets the lessons that pages reported.

```sh
cuju render tutorial
cuju render tutorial register_team --check
cuju render tutorial --json
```

Each lesson has one check, which reads the home folder.

| Check | Holds when |
| --- | --- |
| recording | the library holds a recording outside the Trash |
| match_played | the library holds a game of the Play page or a requested match of at least 300 steps |
| team | the registry holds a team besides the built in AI |
| challenge | the library holds an attempt of a headless challenge, or a leaderboard holds a run |
| page | a page reported the lesson done |

Open a recording, Play for 30 seconds, Register a team and Start a challenge have checks of the
library and the registry, so an agent does them from the command line, with
`cuju render sample 5v5`, `cuju render play --scenario 5_vs_5 --seed 1`,
`cuju render sample starter-team` and
`cuju render challenge empty_goal_close --team builtin --attempts 1`. Jump to a goal, Switch the
camera, Follow a player and Make a photo are lessons of the page, and their steps are the calls of
`window.cuju` that do them, such as `cuju.act('next-goal')`, `cuju.setCamera('tactical')` and
`await cuju.photo.capture({ width: 640, height: 360 })`. An agent that drives the page in a
browser, through the Chrome DevTools Protocol for example, runs those calls, the page notices the
lesson done and reports it, and the command then counts it. The lesson needs no start on the page
first.

The server answers `GET /api/help/tutorial` with every lesson and its state, and
`GET /api/help/tutorial/<lesson>` with one. `POST /api/help/tutorial` with `done`, a list of
lessons, reports lessons done, and with `reset` set to true forgets them. The reports live in
`tutorial.json` of the home folder.

A script that drives the page reaches the lessons and the tour through `window.cuju`.

| Call | Effect |
| ---- | ------ |
| `tutorial.lessons()` | the lessons, each with its identifier, title, page, what it asks and whether it is done |
| `tutorial.start(id)` | begin a lesson, by default the next one not done |
| `tutorial.next()` and `tutorial.stop()` | go on to the next lesson, or close the panel |
| `tutorial.check()` | look at the page at once and return the state |
| `await tutorial.reset()` | forget every lesson done, in the browser and on the server |
| `tutorial.state()` | the lesson under way, the lessons done and the next one |
| `tutorial.snapshot()` | what the lessons read of the page, its recording, timeline, camera, game, teams, challenge and photo |
| `tour.start(step)` | open the tour, at a step counted from zero or where it stopped |
| `tour.next()`, `tour.back()` and `tour.leave()` | move through the tour or leave it |
| `tour.state()` and `tour.steps()` | the step in view and the steps of the tour |

### Samples

cuju ships three samples, a whole match of five a side and one of eleven a side between built in
AIs, and the **starter team**, a small Kaggle submission whose player runs at the ball, carries it
toward the goal and shoots from close range. The Samples part of Help lists each one with what the
library holds of it, In the library, In the Trash or Not in the library for a recording, and In
the registry or Not in the registry for the starter team. Open plays a recording on
Watch and shows the Teams page for the team, Restore brings a recording back from the Trash with
its details, and Add copies a missing recording into the library or registers the starter team as
a new team. Add or restore every sample does all of it at once. The folder of the starter team,
`cuju/render/samples/teams/starter` of the package, is a good start for a team of one's own.

`cuju render sample` adds or restores every sample, and a name does one, `5v5`, `11v11` or
`starter-team`, and the identifiers `sample-5v5` and `sample-11v11` name the recordings as well.
`cuju render sample list` prints each sample with its kind and state. The server answers
`GET /api/help/samples` with the same list, and `POST /api/help/samples` with `names`, a list, adds
or restores those samples, or every one without it. Scripts call `await cuju.samples.list()` and
`await cuju.samples.add(names)`. The file `sample-teams.json` of the home folder names the team that
the starter team became, so the list knows it again, and a team removed from the registry shows as
missing and comes back as a new team.

## Diagnostic report

The **diagnostic report** gathers what it takes to understand a problem in one text, ready to copy
into an issue. Make the report on the Help page, or Make the diagnostic report in the command
palette, gathers it, and the report then shows as text with Copy and Save as a file, which saves
`cuju-report-` with the date and `.txt`. The command `cuju render doctor` prints the server's side
of the same report.

The page's side holds the version of the page, its address on this machine, the page in view, the
drawing in 3D or the 2D view, reduced motion, the theme and whether the page runs as an installed
app with its service worker. It names the browser and its platform, the language, the size of the
screen and of the window, the pixel ratio, the number of cores and the storage that the page uses.
It says whether WebGL and WebGL 2 work, with the name of the graphics renderer and the largest
texture, and whether WebGPU is offered and finds an adapter. It starts the decode worker and sends
it three bytes, which the worker answers as a broken recording, so the report shows that recordings
decode in the worker without reading one, and names the reader of the last recording opened. It
gives the sound's state, muted, the volume and the state of the audio context, without starting or
playing any sound.

The server's side, which `GET /api/help/doctor` returns, holds the versions of cuju, Python,
PyTorch and NumPy and the system, the home folder with whether it exists and can be written and its
free space, the files and bytes of each of its folders, the counts of recordings, the Trash, teams,
tournaments, leaderboards with runs and live sources, the server of the folder, and the recent
warnings and errors of the server, the 50 newest, which include every request that failed inside
the server. The checks then name what is wrong, a home folder that is missing, a file, or cannot be
written, less than 500 MB of free space, a missing sample or page file, a stale `server.json` and
whether video export through the server finds a browser to draw and encode in. That export serves
browsers without a video encoder, so a missing browser marks its check `warn`, with `warning` true
in the JSON, and the check still passes. The page's side names where Export video makes its
videos, in this browser with the format of its best encoder, such as MP4 with H.264, or through
the server. The line under the
button names each check that fails and each check that warns, and says that every check passes only
when none does either.

The report names no path beyond the renderer's home folder, and writes the user's home directory
as `~` there and in every message, a home folder of the renderer outside it as `$CUJU_RENDER_HOME`
and the user's name as `<user>`, on Windows whatever the case in which a message writes them. It
holds no key, no value of an environment variable, only whether `CUJU_RENDER_HOME` moved the
folder, and in its own fields no name of a recording or a team, only their counts. The recent
errors keep their messages, which may name a team or a recording, so a look over them before
pasting the report into a public issue keeps those names private.

`cuju render doctor` builds the server's side in the command itself, asks a running server of the
folder for its own report, whose recent errors join the command's, and adds the lines of
`server.log` near its end that name an error or a traceback. It prints the report as text,
`--json` prints it as JSON, and `--out` also writes it to a file. The command ends with status 0
when every check passes and 1 otherwise, and a server that runs another version of cuju than the
command fails a check of its own.

```sh
cuju render doctor
cuju render doctor --json --out report.json
```

| Call | Effect |
| ---- | ------ |
| `await doctor.gather()` | make the report and return it as an object, the page's side and the server's |
| `await doctor.text()` | the report as text, made first when there is none |
| `await doctor.copy()` | copy the text to the clipboard, true when it worked, and select the text when not |
| `await doctor.save()` | save the text as a file and return its name |

## Installing the page as an app

cuju becomes an app of the computer by two routes. Chrome, Edge and Safari install the page itself
as an app from the browser, and the command `cuju render app` opens the page in a window of its
own with any browser and, with `--install`, adds a launcher to the computer's apps, as
[The app window](#the-app-window) describes.

Chrome and Edge install the page as an app, with a window and an icon of its own and a place
among the computer's apps. The installed page keeps a copy of its own files, so it starts fast and
opens even when the server is stopped, and its Home page then says that the server is not
answering, with the command that starts it. Recordings, teams and live matches always come from the
server, and a recording file still opens from the computer.

The page installs from the address that the server prints, `http://127.0.0.1:8780/` by default,
opened in a tab of its own. In **Chrome**, the install icon at the right end of the address bar,
or the menu of the three dots, then Cast, save and share, then Install page as app, asks to
install cuju, and Install opens it in its own window. In **Edge**, the App available icon of the
address bar, or the menu of the three dots, then Apps, then Install this site as an app, does the
same. Each port and host name is a separate app, so `localhost` and `127.0.0.1` install apart, and
the app opens on the port that it was installed from.

The page brings the offer to the person as well. Once the browser is ready to install the page,
Home shows a small card, Install cuju as an app, from the second visit on, below its opening band.
Install on the card opens the browser's own question, and Not now puts the card away for good in
that browser, as does a No in the browser's question. The card stays away while the page runs as
an installed app, during the tour or a lesson, under a dialog and in broadcast mode, and it never
takes the focus, so the keyboard reaches its two buttons in the order of the page. The browser
keeps the visits and the dismissal in its storage, under `cuju.installOffer`. The Install the app
part of Help keeps the same offer within reach afterwards, shows Install the app while the browser
offers it, and says whether the page runs installed.

**Safari** on a Mac installs the page from its own menu, File, then Add to Dock, and Help names
that menu there. Firefox and the other browsers that install no pages reach the same app through
`cuju render app --install`, which Help names for them, and every browser's Help names the
command.

A service worker, `sw.js`, keeps the page's own static files, the HTML, styles, scripts, models,
pictures and sounds, in a cache named after the build of the page. The build is a digest of cuju's
version and of the name, size and time of every file of the page, which `GET /api/help/app`
returns with the version. Each time the page opens, the worker asks the server for its build. While
the build is the worker's own, files come from the cache first. Once the server holds a new
version, or a file of the page changes, files come from the server at once and the page registers
the worker of the new build, which replaces the old one and its cache. With no server answering,
the cache answers. The server writes the SHA-256 of every file of the page into the worker as it
serves it, and the worker keeps and answers only copies with the digest of their file, so it drops
any other entry of its cache and asks the server again.

The worker keeps only files of the page itself. Every answer of the API stays out of it, so
recordings, teams, live streams, games and reports always come fresh from the server, and so do the
sandbox of team workers, a request with a query such as the page of a notebook, a request for a
range, and the montage video. The page registers the worker only at its top on http at a loopback
host, `127.0.0.1`, `localhost` or `[::1]`, so a notebook's frame, Google Colab's proxy and any
other address keep no copy, and a worker that finds itself elsewhere removes itself.

The page points its manifest at `manifest.webmanifest?lang=CODE` for any language but English, and
the server then fills the manifest's description and the names of its shortcuts, Watch, Play and
Help, from that language file, so an install made from a Portuguese page names them in
Portuguese.

Update on Help shows a newer build at once, and Remove the offline copy unregisters the worker and
deletes its cache until the page keeps them again on its next start. The browser's own list of
apps, `chrome://apps` in Chrome and `edge://apps` in Edge, or the menu of the app's window,
uninstalls the app.

| Call | Effect |
| ---- | ------ |
| `install.state()` | whether the worker is supported, registered and in control, its build and the server's, an update, an offer to install and whether the page runs installed |
| `await install.install()` | show the browser's offer to install, which needs a click of the person |
| `await install.check()` | ask the server for its build |
| `await install.update()` | register the worker of the server's newer build |
| `await install.unregister()` | remove the worker and its cache |
| `await install.ready()` | the state once the worker is registered |

`install.state().route` names how this browser installs the page, `browser` for its own offer,
`safari` for the Dock and `command` for `cuju render app --install`. The card of Home is
`cuju.installOffer`.

| Call | Effect |
| ---- | ------ |
| `installOffer.state()` | the visits, whether the card was dismissed and shows, whether the browser offers to install and whether the page runs installed |
| `await installOffer.install()` | show the browser's offer, as Install on the card does |
| `installOffer.dismiss()` | put the card away for good, as Not now does |

### The app window

`cuju render app` opens the page in a window of its own, with no tabs and no address bar, in any
browser and on Windows, macOS and Linux. It reuses the server of the home folder when one runs,
and otherwise starts one that ends when the window closes, on port 8780 when that port is free or
on the port of `--port`. The command takes the first route that the computer has.

1. **The system's web view**, through [pywebview](https://pywebview.flowrl.com/), which draws the
   page with WebView2 on Windows, WKWebView on macOS and WebKitGTK or Qt on Linux. pywebview comes
   with the optional extra `app`, `pip install 'cuju-render[app]'`, which a person who installed
   `cuju[render]` adds the same way. pywebview is under the BSD 3-Clause License. On Linux it also
   needs the GTK or Qt bindings of the system, and a web view that does not open there leaves the
   next route with a note.
2. **A Chromium browser in app mode**, the first of Edge, Chrome, Chromium and Brave that the
   computer has, Edge first on Windows, where every computer has it. The window has a profile of
   its own in the folder `app` of the home folder, apart from the person's browsing, its sign in,
   its extensions and its tabs, and the command follows that profile to tell when the window
   closes. `--browser PROGRAM` names the browser.
3. **The default browser**, with a one line note on the two routes above, as a bare `cuju render`
   opens it.

`--route webview`, `--route chromium` and `--route browser` ask for one route, and the command
then says so when the computer lacks it. Every route opens the page from the loopback address of
the server, and nothing is downloaded.

The page works in each window as it does in a browser. WebGL draws the 3D view, sound plays after
the first click or key, as browsers require, and the page starts muted as always. The offline copy
of the page is kept where the engine has service workers, as Edge, Chrome and WebView2 do, and the
Install the app part of Help says when it is off. Video export in the page needs WebCodecs, which
Chromium and WebView2 have, as does the WebKit of Safari 16.4 and later. The window counts as an
installed app, so Home shows no offer to install inside it.

`cuju render app --install` adds a launcher that opens the app window the same way, with the cuju
icon of the page.

| System | Launcher |
| --- | --- |
| Windows | a shortcut `cuju` in the Start menu and on the desktop, which runs `pythonw`, so no console opens |
| Linux | an entry `cuju.desktop` of the applications menu in `~/.local/share/applications`, or in `applications` of `$XDG_DATA_HOME` |
| macOS | an app `cuju.app` in `~/Applications` |

A launcher runs the Python of the install that made it, with `--home` when the home folder is not
the default one and with the `--route` and `--browser` given to `--install`. The launchers go only
into the person's own folders, and only on this command. The folder `app` of the home folder keeps
the icon files and `launchers.json`, the list of what the install made, so
`cuju render app --uninstall` removes exactly that. A file of the same name that the install did
not make stays where it is, and `--install` then stops and names it.

## Broadcast presentation

The page presents a match as a broadcast does, and covers the seams of the engine, the jumps of
players to their places at a restart, with the transitions of television. Settings turn each part
off.

**Lineups.** A recording opened at its start pauses for a pan across the ground under the team
sheets, with each team's goalkeeper, its lines from the back and its formation at kick off, such as
2-2 or 4-3-3. Players close in depth share a line, by a gap that shrinks with the depth the team
spans, so the lines of five a side, a few meters apart at kick off, part as those of eleven a side
do. Enter or a click starts the match.

**Goals.** Playing forwards at up to two and a half times real time, the page holds play on the step
before a goal, so the kick off that follows stays unseen. The crowd roars, a graphic names the
scorer, the minute and the assist, and the camera covers the celebration in four shots, the live
view, a close tracking shot of the scorer, a slow orbit of the scorer and teammates, and a low
angle. The scorer runs towards the corner and celebrates with a move of the team's choosing, the
teammates run in to join or copy it, the scorer's goalkeeper claps, the beaten goalkeeper looks down
and the other team walks back. A replay follows under a wipe, from one angle that suits the
goal, high for a move of three passes or more and for an own goal, reversed for a shot from 18
meters or more and from inside the net otherwise, and in slow motion from just before the shot.
Shift with R queues further angles, and R replays the last goal at any time. A ball that reaches
the net during open play makes it bulge at the point of impact and spring back.

**Restarts.** Before each restart, the page holds the last step of play for a moment. The players
slow, turn towards the ball and walk towards their new places, and the ball runs on with gravity,
bounces and rolls, strikes the posts, bulges the net and stops at the boards, so a ball that leaves
the pitch keeps going in the picture. A wipe across the picture then hides the jump to the new
places, and the camera cuts to a view that suits the restart, behind the flag for a corner, beyond
the touch line for a throw in, behind the goal for a goal kick and behind the ball for a free kick
or a penalty. A pre roll of one and a half to three seconds follows, in which the players shift
their weight and glance about. The taker of a throw in picks the ball up and holds it overhead, and
the taker of another set piece bounces the ball, places it and stands behind it. Every movement of
the pre roll fades out before the whistle, so play resumes exactly on the restart's own step. The
first kick off of a match has the pre roll alone. A scenario with a second half, such as
`11_vs_11_kaggle`, stops play when the clock reaches 45 minutes and restarts with a kick off, which
brings a card for half time and the referee's double whistle. The timing follows the scenario's
second half step, so an interval configured at another step occurs at its own clock threshold.
Scenarios with continuous play carry on through 45 minutes.

**Decisions.** A foul, a card or an offside brings a replay of the decision. Play stops on the
whistle, the replay runs up to the contact, slowing at the end, and freezes on it, with a ring under
the offender, a ring under the victim and an arrow along the offender's path. A banner names the
decision and the offender. An offside draws the line of the second last defender and the line of
the attacker on the grass, with the space beyond the defence shaded. A yellow or red card adds a
scene in which the referee runs to the offender and raises the card, the offender clasps both hands
to the head, and a graphic names the card, the player and the minute. Enter or a click skips the
replay.

**The referee** runs the diagonal of the pitch through the match, keeping a distance from the ball
and the players, points at each restart, raises the whistle before it, and blows it.

**The end of a recording.** The last frame brings End of recording when the file stops during
play. An episode end flag brings Full time when `full_match` is `true`, and End of episode
otherwise, as in an academy exercise. Older files without timing therefore bring End of episode
when the last frame has an episode end flag, and End of recording otherwise. The show at the end
of the match then opens under Full time for a full match and under Episode complete otherwise.

**Full time.** At the final whistle, play winds down instead of stopping. Each player slows from a
run
to a stand over two to four seconds, the ball rolls to rest, the referee blows and lowers the
whistle, and a card for full time names the winner or the draw. A recording then plays the show at
the end of the match, in five parts joined by wipes.

1. **Reactions**, in which the winners jump, dance, huddle and run to their fans, the losers slump,
    sit or lie on the grass and get up, the players of a draw shake hands, and everyone walks
    towards the stand applauding, covered by a wide shot, the winners' hero, the beaten goalkeeper
    and the stands.
2. **Facts**, a card of the score, the scorers and the share of each team in possession, shots,
    shots on target, passes, pass accuracy, tackles, saves and cards.
3. **Reel**, every goal again with its replay.
4. **Spotlight** on the player of the match, a slow loop of the player's best moment beside the
    player dancing beside an MVP medal on a ribbon in the team's two kit colors. An entrance moves
    the camera closer, flashes once and plays a fanfare, then reveals the player name and shirt
    number. Under reduced motion the camera holds its distance, the medal and the name appear in
    place, and the player still dances, while the flash and the shine on the medal stay out.
5. **Podium**, with a fanfare, the best three of the winners on the steps, the rest of the team
    celebrating behind them, confetti in the team's colors and the card of the player of the match,
    or for a draw, the best four of each team on two low stages.

The player of the match is the winners' best, or the best of both teams after a draw, by a score of
five points per goal, three per assist, two per save, one per tackle and a small share for passes
and touches, less five per own goal. The facts come from the actions and touches that every frame
holds. A shot is an intentional touch during the GRF shot animation, or an intentional header
from within 30 metres of the opposing goal that sends the ball towards it along the pitch at more
than three metres a second. A save is a goalkeeper touch that stops a shot on target. Enter or a
click moves to the next part, Esc ends the show, and the page then fades to Home. A seek during the
reactions ends the show where it stands.

The statistics screen opens on demand. The Match statistics button sits on the podium panel at
the end of the show and on the card at the end of a recording, and the Match menu offers it for
the open recording under This match. It opens over whatever is on screen, the show waits beneath
it, and Close or Esc returns to the same place. It reads from top to bottom. The
result comes first, then the awards, the player of the match and the rarest achievements and team
awards, then the comparison of the two teams. Team tabs list every player of the team with shirt
number, name, inferred role, grade medal, minutes, goals, assists, shots, passes, tackles and
saves, and the More columns button adds shots on target, key passes, pass and shot accuracy,
touches, clean sheets, own goals and cards. Column buttons sort either way. Opening a player shows
rating terms and achievement reasons. Last come three charts over twelve periods of the match,
possession, the running totals of shots and goals, and territory with possession, each with its
caption, time axis and key, and the guide to the grades opens below them. The whole screen scrolls
as one card. Focus starts on the outer dialog, where Esc or Enter closes the screen. Tab reaches
the controls, arrow keys switch team tabs, and Enter activates a focused control. Anywhere away
from a control, Enter closes the screen. For a live source the screen opens from the podium
panel of the show that Match summary offers. It takes a stable copy of the latest completed
episode that the page holds, or of the current episode while none has completed. An episode has
completed when an end flag closes it or the next episode starts after it, which is how sources
with automatic resets mark it, and a completed episode needs at least two frames.

Player grades describe contributions in the available frames. Minutes use increasing game clock
time while the player is on the pitch, excluding cuts. Goalkeeper is the header goalkeeper flag.
Other roles use the initial position along the attack direction. Positions below minus fifteen
metres are defenders, above ten metres are forwards, and the rest are midfielders. These roles
are estimates rather than formation assignments.

The rating starts at five and is limited to zero through ten. Event contribution adds one point
four per goal, one per assist, zero point two five per shot on target, zero point three five per
key pass, and zero point six per tackle or recovery for a defender or goalkeeper, otherwise zero
point three five. Goalkeepers also receive zero point six five per save. This sum is multiplied
by thirty divided by the greater of ten and minutes played, capped at three. Pass accuracy adds
one point five times its difference from zero point six five after at least three attempts.
A clean sheet adds one for a defender or goalkeeper and zero point three for other roles.
Own goals subtract two each, yellow cards zero point four each and red cards one point five each.
A second yellow followed by dismissal can therefore incur both card penalties.

Grades use these lower rating thresholds. F starts at zero, D minus at two, D at three, D plus at
four, C minus at four point five, C at five, C plus at five point five, B minus at six, B at six
point five, B plus at seven, A minus at seven point five, A at eight, A plus at eight point five
and S at nine point five. S additionally requires at least one minute and sixty percent of the
available duration, event contribution of at least four point five and zero penalties. Otherwise
the highest grade is A plus. A grade requires the greater of half a minute and twenty percent of
the duration capped at ten minutes. Shorter appearances show a dash. The grade medal identifies
the grade and exposes its numeric rating on demand.

Achievements include all tied leaders when a rule names a leader. Each achievement gives its
name, symbol and numerical reason, with reasons available when opening a player.

Hat trick awards three or more goals, and Brace awards exactly two. Playmaker awards the most
assists with at least one. Creator awards the most key passes with at least two for players outside
the Playmaker award. A key pass is a completed pass to the shooter within ten seconds before
a shot, with continuous
open play, possession staying clear of the opposition and zero intentional opposition touches
between pass and shot. Each shot credits at most the latest qualifying pass.
Wall awards the most saves with at least one. Engine awards the most touches with at least five.
Ball winner awards the most tackles and recoveries with at least two. These recoveries use the
same successful steals as the facts screen, rather than a separate interception estimate.
Sharpshooter requires at least three shots with at least seventy five percent on target.
Own goal identifies every player with an own goal. Sent off identifies every player receiving
a red card in the available frames.

Player Clean sheet requires an available duration of at least one minute, participation for at
least eighty percent of it and zero opposition goals while on the pitch. Team Clean sheet
requires at least one minute, an initial opposition score of zero and a final opposition score
of zero. Comeback requires a team to win after trailing at a visible goal. Late winner requires
a win with its decisive goal in the final tenth of an episode lasting at least one minute.
The decisive goal is the goal that puts the winning total above the final opposition total.
These rules use episode duration for academy exercises and smaller games.

Three charts divide the available frames into twelve equal periods. Possession is a line of the
first team's share of owned frames around an even split at 50 percent. Above the middle line the
line and its shading take the first team's kit color, below it the second team's, so the color
changes where the line crosses the middle. Every chart uses the two kit colors, and a second team
whose shirt looks close to the first team's takes its trim color. Cumulative shots use dashed
lines and goals use solid lines. Pressure averages half the ball position along the pitch and half
the possession direction across owned frames. Above the centre favours the first team. Pressure
describes territory and possession rather than expected goals. A shared event strip marks goals
and card changes for both teams along the time axis. The axis endpoints show the available game
clock range. Available frames supply the statistics for partial sources as well as completed
episodes.

**Live sources** skip the lineups, show the card for full time alone, or the card for the end of an
episode outside a full match, and offer the show at the end through a button rather than playing
it. A decision replay that falls far behind the present returns to it under a wipe.

**Broadcast mode**, turned on with T, from the View menu or in the settings, shows the picture and
its graphics alone, as on television, with the bars, the controls, the messages and the pointer
hidden. Moving the pointer to the bottom edge of the window, or pressing Esc, brings the controls
back for a few seconds, and they stay while the pointer rests on them. T, or Esc pressed again while
the controls show, leaves broadcast mode, which works in a window and in fullscreen and stays on
across reloads.

## Environment

The ground follows the Field page and the View menu, which share their settings.

**Time of day.** A slider sets the hour, from midnight to midnight in quarter hours, and four
presets choose dawn, day, dusk and night. The sun follows a summer path over the ground, rising
behind one end, crossing behind the far stand and setting behind the other end, and the moon and
the stars come out at night. Four floodlight towers light the pitch as the sun sets.

**Weather.** The weather is clear, overcast, rain, heavy rain, snow or fog, with a strength and a
wind, which drives the clouds and the rain. Rain wets the grass over a few seconds and dries
slowly, snow settles on the pitch and leaves the lines clear, and the floodlights also come up by
day in bad weather.

**Arenas.** Five arenas surround the same pitch, lines and goals, and each has fans along both touch
lines.

| Arena | Ground | Crowd |
| ----- | ------ | ----- |
| Classic stadium | two tiers of fans under a roof, with floodlights on four towers | the full bowl |
| Beach | sand, palms and umbrellas, with the sea behind the far touch line | three rows on the sand, in deck chairs and on their feet, under umbrellas |
| City rooftop | a pitch on top of a tower, with the skyline all around, lit at night | a small terraced stand on each touch line |
| Space station | a deck in orbit above the turning Earth, under a sky of stars | a gallery on each touch line behind a pane of glass, and a glass helmet on every player |
| Neon arcade | a grid to the horizon, with pylons, mountains and a sun | figures of light on glowing steps |

The crowds of the other arenas are the same painted people as the stadium's, so the fans of each
team wear its colors on its half of the ground and stand and jump after a goal. Each is a few
hundred people, so it costs little at the low quality. On the space station each player wears a
bubble of glass sized to the head and the hat of the model, which is clear in the middle and bright
at the rim, and a camera at a player's eyes leaves that player's bubble out.

**Crowd and boards.** The stands fill with the fans of each team by default, in the team's colors,
or with a painted crowd in colors of the viewer's choosing, or with GRF's own crowd, at a density of
choice. The painted crowd sways with the play and stands and jumps after a goal. The advertising
boards show the sponsors of the two teams in turn, the boards that ship with the renderer, with the
cuju logo and the team names, or up to eight boards of the viewer's own, uploaded or drawn.

**Field page.** The page groups its settings into presets, the arena, the grass, the time of day,
the weather, the boards and the crowd. The ten presets range from a summer afternoon to a rainy
night, snow, the beach at sunset and the space station. The grass takes colors for the grass, the
lines and the nets, and a mowing pattern of stripes, checkers or circles with the width of its
bands. The view on the page is a free camera, flown with the drag and W, A, S and D, and touching a
control flies the camera to the part it changes, the grass, the lines, the nets, the boards, the
crowd, the sky or the whole ground. The camera flies once to each part, so a view set by hand stays
for further changes to the same part.

## Sound

The page mixes its sound in the browser, placed in the ground and heard from the camera, and each
arena has a soundscape of its own that rises with the play near a goal and answers goals, near
misses and the final whistle in its own way.

| Arena | Soundscape | Crowd |
| ----- | ---------- | ----- |
| Classic stadium | the crowd itself, with a fanfare at full time | the full crowd under the roof of the stands |
| Beach | uneven waves, breeze and gulls | a smaller crowd in the open air |
| City rooftop | traffic, horns, sirens and wind, quieter at night | a smaller crowd whose voices come back off the towers |
| Space station | hum, airflow, beeps, radio chirps and a chime for goals | a smaller crowd in an enclosed gallery |
| Neon arcade | the buzz of the tubes, arcade blips and goal stings | a smaller crowd on the open grid |

The referee's whistle marks restarts, decisions, half time and full time in every arena, and a near
miss, a save or a shot off the woodwork draws a reaction. Rain and wind follow the weather, with
rain drumming on the stadium's roof and hissing on the sand, and the space station has no weather.
Real recordings in the public domain or under CC0 carry the crowd, its roar for a goal, its groan at
a near miss and its applause, which every arena plays through the band, the echo and the walls of
its place and quieter than the stadium, the referee's whistle, the waves and gulls of the beach,
the traffic, siren and horn of the city, the hum, beeps and radio of the space station, the arcade's
goal sting, the rain and the wind. The rest is synthesized in the browser, and the file
`sounds.json` beside the sounds names the author, source and license of each file. A change of arena
or weather fades from one soundscape to the next over about a second. The sounds of the play follow
forward play at up to two and a half times real time, and pausing silences the page. Each arena's
own sounds play under its crowd. The sound files load the first time the sound is turned on, so a
muted page fetches none, and unavailable files fall back to the synthesized sounds where available.

Each sound of the play, a whistle, a kick, a roar or a team's own sound, ends with the moment it
belongs to. A seek, a jump to a goal, a restart and a change of match fade every sound of the play
out within a tenth of a second, sounds that were due a moment later included, while the soundscape,
the crowd's murmur and the weather play on. At most twelve sounds of the play sound together, and a
new one fades out the oldest, so a quick run of kicks and tackles stays clear.

The page starts muted, since browsers start sound only after a click or a key, and M or the speaker
button turns the sound on, at half volume by default.

Three levels in the settings panel lower parts of the sound beneath the volume. The crowd level
sets the crowd with its roars, groans and applause and the songs of the supporters of each team.
The ambience level sets the soundscape of the arena and the weather, and the action sounds level
sets the whistle, the ball and the other sounds of the play. Each level runs from silent to full
and starts full, so a level can only make its part quieter. The volume, mute and the rule that
sound plays only while a match plays on Watch or Play still govern every part, and the levels stay
in the browser.

## Settings

The settings panel holds the parts of the presentation and the behavior of the page. Each setting
stays in the browser. The idle return interval accepts 5 to 300 seconds.

Three presets at the top of the panel set the parts of the presentation in one click. **Quick
look** turns off the lineups, the celebrations, the replays after goals, the decision replays, the
restart transitions and the post-match show, so a researcher who checks a match sees play and
nothing else. **Full broadcast** turns all six on, as they are by default. Any other mix of the six
is **Custom**, which the browser keeps as the person's own. Choosing a preset over a custom mix
keeps that mix, and Custom then brings it back as it was, so a person can try either preset and
return. The preset in force is marked, a change of any one of the six boxes makes a new custom
mix, and the arrow keys move between the presets as in any group of choices. The command palette
offers the same presets.

| Setting | Default | Effect |
| ------- | ------- | ------ |
| Return to broadcast when idle | on, after 20 seconds | return from the free camera |
| Ball trail | on | a line behind the ball |
| Player labels | off | the number and name over each player in sight |
| Captions of the events of the match | off | short lines of the events over the view, read by screen readers |
| Size of the captions | medium | small, medium or large captions |
| Motion | the system's | reduced or full motion |
| Crowd, ambience and action sounds levels | full | lower each part of the sound |
| Click a player to follow | off | the Follow player camera on the player clicked |
| Broadcast mode | off | the picture and its graphics alone |
| Lineups before kick-off | on | the team sheets at the start of a recording |
| Celebrations after goals | on | the celebration and its cameras |
| Replays after goals | on | a replay of each goal |
| Decision replays | on | replays of fouls, cards and offsides |
| Restart transitions | on | the wind-down, wipe and pre-roll of each restart |
| Slow motion in replays | half speed | off, half speed or quarter speed |
| Post-match show | on | the show at the end of a recording |
| 2D view | off | a flat drawing from above without WebGL, which skips replays and shows |
| GRF classic pitch | off | GRF's own pitch texture in place of the drawn pitch |
| Capture the mouse | off | a right click in the free camera captures the pointer |
| Use the kits saved in the match | off | saved kits instead of current team settings |
| Tips for new visitors | on | a short tip on each page until dismissed |
| Touch controls on Play | when a touch screen is used | the stick and buttons of a game |
| Theme | the system's | dark or light |
| Language | the browser's | the language of the page, as [Languages](#languages) describes |

The Motion setting follows the system's preference for reduced motion by default, and Reduced or
Full sets it for the page alone. Reduced motion keeps everything a match shows and replaces the
movement of the camera and of the graphics. The lineups, the celebrations, the replays after
goals, the decision replays, the restart transitions and the post-match show all play, each under
its own setting, and R plays the last goal again as a replay.

Under reduced motion every scripted shot holds one still framing and changes by a cut. The view
of the lineups holds the middle of the ground, and the close shot, the orbit and the low angle of
a celebration, the replay angles, the camera of a decision replay, the view of a restart, the
shots of the reactions after the match and the podium each hold still. A shot cuts to a new
framing when its subject nears the edge of the frame, so a running scorer or a flying ball stays
in sight. The circling camera of the spotlight loop holds one angle, the spotlight holds its
distance, and a change of camera and the flights of the free camera and of the Field page reach
their view at once. Each wipe between parts becomes a short fade through the logo. The flash on
the contact of a decision, the confetti of the podium, the flash and the shine of the medal and
the ball trail stay out, the rings of a decision hold their size, the preview of the team editor
stands still and the animations of the page end at once. The players move as in full motion, in
the celebrations, the reactions, the pre-roll of a restart and the dances of the podium, and slow
motion in replays follows its own setting.

Three quality levels in the View menu set the resolution of the shadows, the pixel ratio, the
glow of bright lights, the particles of rain and snow, the detail of the crowd and the shadows of
the floodlights, and the page picks one from the device.

## Languages

The page ships in English, and any other language joins it as one file that the language import
loads. The folder `translations` of the repository holds a draft in Brazilian Portuguese, which
loads the same way. Every text the page shows comes from a language file, the pages, menus, buttons, titles,
labels for screen readers, tips, the tour and the lessons, toasts and messages, the captions, the
names and texts of the scenarios, and the messages of the server that the page shows, such as the
reasons an upload or a request was refused. The command line and the answers of the API stay in
English, and an answer that the page shows also names its message, so the page shows it in its
own language. Names that come from the data, such as the names of teams and players, read as they
were given.

### Choosing a language

The Language list of the settings panel offers Follow the browser, then English, which ships
with cuju, then the languages of the person's own. The list shows once a second language exists,
and Import a language file stays beside it either way. Follow the browser, the default, picks the
first language of the browser that a file exists for, by its whole code such as `pt-br` and then
by its language alone such as `pt`, and English otherwise. A choice in the list stays in the
browser, and the page reloads at the same address in the new language, so the open page, the
open recording and its moment come back as they were. A file opened from the computer opens again
after the change. Numbers and dates follow the language too, so a Portuguese page writes `0,5`
and its own dates. The command palette lists each other language too, as Language with its name,
and Language follows the browser while a language is chosen, so the word language, or the name of
a language, finds them.

The parameter `lang` of the address, such as `?lang=pt`, picks a language for one visit without
storing it, which suits a clean feed for OBS and scripts. A choice stored in the browser comes
first, and the feed keeps its own storage, so `lang` decides there. A message that a language
lacks shows in English, so a language that covers only part of the page still works. The server
puts English into the page itself, so the page starts without asking for it.

### Adding a language

A language is one JSON file named after its code, such as `de.json` for German or `pt-br.json`
for a variant, with lowercase letters and digits in parts. The file is one object keyed by message
identifier, and the key `@language` holds the code, the name of the language in itself, its
English name, the locale of numbers and dates, the direction of the text and its plural
categories.

```json
{
    "@language": {
        "code": "de",
        "name": "Deutsch",
        "english": "German",
        "locale": "de-DE",
        "dir": "ltr",
        "plurals": ["one", "other"]
    },
    "html.nav.watch": "Ansehen",
    "recordings.count.trash": {
        "one": "{count} Aufnahme, {size} im Papierkorb",
        "other": "{count} Aufnahmen, {size} im Papierkorb"
    }
}
```

A message is a text whose placeholders in braces, such as `{count}` or `{team}`, the page fills
in, or an object of plural forms for a count, keyed by the plural categories of the language as
Unicode CLDR names them, `zero`, `one`, `two`, `few`, `many` and `other`. Portuguese has `one`,
`many` and `other`, Polish has `one`, `few`, `many` and `other`, and Japanese has `other` alone. A
form for an exact count, such as `=0`, comes before the categories. A text keeps the placeholders
of its English message and adds none, and a plural form may leave the count out, as in `one
recording`. A message may count what English leaves alone when the English text holds `{count}`.
The value `count` picks the form, so a message whose words agree with another number names that
number `{count}`. Brazilian Portuguese counts 0 as `one`, so its messages give 0 a form `=0` of
its own, such as `0 gravações`. A count given with decimals, such as `1.0`, takes the form that
the language gives a number written with decimals, so English reads `1.0 minutes`. The captions
stay plain texts.

A message may mark words in two ways, and a translation marks the same words. Two asterisks on
each side, `**Restart the server**`, give strong emphasis, for the key noun or action of a
sentence or a warning, and backticks mark code, a command, a program, a file or a variable, such
as `` `cuju render serve` `` or `` `$CUJU_FFMPEG` ``. A shortcut in backticks, a chord of key
names in English such as `` `Ctrl K` ``, `` `Shift + ?` `` or `` `Esc` ``, shows as keycaps, each
key named in the language of the page for a screen reader, and `Mod` names the primary modifier,
Ctrl, or Command on a Mac. The page builds strong, code and keycap elements from the marks and
puts every word in as text, so a message never holds markup, and where a text goes into a title,
a tooltip or a notification the marks drop away and a shortcut shows its legends.

`cuju render language new de --name Deutsch` writes `de.json` with every English message, the
header and the plural forms of German filled in, ready to translate in place. `cuju render
language check de.json` compares a file with English and names each message the file lacks,
each message English lacks, and each malformed message, whose placeholders differ from English or
whose plural forms miss a category of the language. It also counts the messages that still read
as in English, which is no fault. It exits with 0 when the file is complete and well formed and 1
otherwise, and `--json` prints the report for a script or an agent.

The folder `languages` of the renderer's folder holds the languages of a person's own. A file
dropped there joins the Language list once the page lists the languages again, and Import a
language file on the settings panel sends a file to the server, which checks it and keeps it there
when every message is well formed. Missing messages are allowed and show in English. A malformed
file is refused with the first problem named, a file in the folder that is malformed shows in the
list as refused, and the code `en` belongs to English, so a variant of it takes a code of its own,
such as `en-x-mine`. A message is well formed when it holds the placeholders of its English
message, the plural forms of its language and as many code spans as the English, since commands,
names and shortcuts are code. Bold words are the translator's choice, since each language stresses
its own words. `cuju render language add FILE`, `list` and `remove CODE` do the same from the
command line.

### Contributing a language

English is the reference, and a new message of the page joins `en.json` first, in
`src/cuju/render/web/languages` of the repository. Other languages live in the folder
`translations` at the root of the repository, outside the package, and load through the language
import. The folder holds the Brazilian Portuguese draft, `pt.json`, with its style guide and its
glossary. A draft may lack messages, which then show in English, and the test suite checks that
each message it has keeps the placeholders, the plural forms and the marks of the English, and
the tests that need a second language import the Portuguese draft. A translation writes in the
voice of its own language and uses that language's own punctuation for an interface, rather than
the plain commas and periods of the English, keeps the same term for the same thing everywhere,
and a native speaker reads it through.

### Agents and scripts

| Route | Does |
| --- | --- |
| `GET /api/languages` | lists the languages, shipped first, each with its code, name, English name, locale, direction, source, whether the page can use it, its count of messages and of missing ones, and its problems |
| `GET /api/languages/CODE` | answers the file of a language |
| `POST /api/languages` | checks the language file of the body and keeps it in the folder, or refuses it with the problem |
| `DELETE /api/languages/CODE` | removes a language of the folder |

The page offers the same as `cuju.language`, whose `list()` returns the languages, `choose(code)`
picks one, or `null` to follow the browser, and `importText(text)` imports a file. An error answer
of the server carries `error` with its English text, `error_id` with the identifier of its
message and `error_values` with the values of its placeholders, and so does each requested match,
game, video, challenge run and tournament match that failed, so an agent reads the text or
matches the identifier.

The names and titles that cuju makes come the same way, so the page shows them in its own
language. GRF's built-in AI, the sides Left and Right of a recording whose teams have no names,
You and Player 1 on the Play page, a person with a registered team as teammates, a policy without
a name of its own, and the titles of games, challenge attempts, the demo, the Recorder, live
sources and the shipped samples each travel as a label. A label holds the English text in its
field, such as `title` or `name`, and beside it `title_id` and `title_values`, or `name_id` and
`name_values`. A value may be a label of its own, a scenario, which the page shows by its name, or
a challenge, which the page shows by its title. A recording keeps its labels in its header, and a
summary of the library adds `team_labels`, the label of each team or null. The page shows a label
of a title or a name in its language when the label names one of the messages that names and
titles carry, those whose identifiers start with `server.names.` or `server.tournament.label.`,
and shows the English text of any other label. A title, a scenario or a team name that is no text
shows as the empty text, or as the digits of a number. A name that a person
gave, a renamed built-in AI and a title typed on the Recordings page stay plain text and show as
given, and a recording of an earlier version shows the English text it holds. The command line and
every English answer read the same text as before. The slate messages of the feed, its list of
sources and its refusals carry their identifiers in the same way, and so does a team's name inside
a refusal of the server, with a scenario named by its name on the page.

## Keyboard

Tab and Shift Tab move between controls on every page. Enter or Space activates a control.
Ctrl K opens the command palette outside text fields, as described under Page layout.
The skip link moves the focus to the main content and leaves the address of the page as it is.
Menus and lists use the arrow keys, Home and End.
Esc closes a menu or panel and returns focus to its opener, unless another dialog took the focus
meanwhile. Dialogs keep Tab inside them, except the card of the guided tour, which leaves the
page usable.
Sliders use the arrow keys. Color fields accept a hex value beside the color picker.

Each page has a title of its own in the window, such as `Help · cuju`, and Watch takes the title
of the recording that plays. The main content carries the name of the page in view, and a screen
reader hears the name of each page it moves to. Every page has one heading at the top level, the
visible title on Teams, Tournaments and Help and a heading for a screen reader on the other pages,
and the headings below it descend one level at a time. The clock of the score bug is a timer, so
a screen reader reads it when asked while the HUD says goals and banners as they come, and the skip
buttons of Watch carry their names, such as Back 30 seconds. The timeline of
Watch is a slider that says where it stands as it moves, such as `1:23 of 5:00`.

Home cards open their pages. Watch keeps its playback and camera keys while the picture has
focus. Focused controls use their own keys, and text fields keep typing within the field. Buttons
and links take Enter and Space alone, so a single key such as H, the question mark, M or F reaches
the page while one has the focus, outside a dialog or a menu. Space on
a focused control acts on that control, so a summary that opens a section opens it while playback
carries on as before. The controls of the Watch page stay in view while keyboard focus is inside
them and rest again once focus leaves.
Recordings supports folder arrows and row arrows, Enter opens a row, and Space selects it.
The grid of environments on Watch moves between its tiles with the arrow keys, Home and End, and
between its pages with Page Up and Page Down, and Enter shows the focused environment.
Matches and Play setup use Tab through their forms, and the input settings of Play change the
keys of play. Teams uses arrows through its list and
section menus, with Tab through editor controls. Field uses Tab through settings and the
preview, where the camera keys move the view and arrows turn it. Play uses Esc for its pause menu,
with Home available there and on the end card. The arrows, Home and End move between the buttons
of the pause menu and of the end card, as in any menu. Home pauses an active game. Quit to Home ends
the game and saves it when Save to Recordings is enabled. A natural ending shows Full time
for a complete match
and End of episode otherwise.

The picture uses plus and minus to zoom, and Watch uses Alt with arrows to turn the camera.
The brackets choose the player of the Follow player camera, as a click on a player does.

The painter canvas uses arrow keys to move its cursor and Space to paint. Page Up and Page Down
select objects. Arrow keys move a selected object, Shift increases the distance, the plus and
minus keys resize it, and the bracket keys rotate it. Enter edits selected text.
The post match show uses Enter to advance and Esc to finish while the picture has focus.

## Recording format

Optional header fields carry scenario timing. The `duration` is the configured number of steps.
The `second_half` field is the configured step of the second half, or null when no half time occurs.
The clock threshold is `second_half` times 1800 milliseconds. The `full_match` field identifies a
scenario with a duration of at least 3000 steps and no early episode end conditions. Full time
needs `full_match` set to `true`. Missing timing leaves the recording playable, with End of episode
for an episode end flag and End of recording otherwise.

Bits 0 and 1 of the frame flags mark episode end and start respectively, with values 1 and 2.
The offside flag has value 4. Player references in the frame use indices in the header's player
list, including the scorer, foul offender, victim and offside player.

The optional `engine_scorer` header flag enables bits 8 through 12 of the frame flags. They hold the
engine scorer index in the header's player list plus one, with zero meaning the scorer is
unavailable. Older pages ignore these bits.
The optional `offside_called` header flag enables bit 2 of the frame flags. When set, the offside
integer holds the last toucher penalized at a buffered free kick without a foul. Otherwise it
retains the first offside candidate. Older recordings retain their candidate based interpretation.

A recording is a gzip compressed file with the extension `.cjr`. After decompression it holds the
seven bytes `CUJREC1` followed by a newline, the length of a header as an unsigned 32 bit integer,
the
header as UTF 8 JSON padded with spaces to a multiple of four bytes, and the frames. Every number is
little endian. Version 1 stores the frames back to back, each of the same size and aligned to four
bytes, and version 2 stores them coded in sections, as [Version 2](#version-2) describes. Both
versions hold the same frames bit for bit. The recorder, requested matches and games on the Play
page write version 2, `Recorder(batch, version=1)` writes version 1, and the page, the library and
the module `cuju.render` read both. A live stream sends the header of version 1 and its frames
uncompressed.

The header records the version, 1 or 2, the title, the scenario, the steps per second, 10, the
names of the fourteen joints and the parent of each, one entry per player with its team, its index
within the team, whether it is the goalkeeper and whether an agent controls it, the name and colors
of each team, the size of a frame as version 1 stores it and the number of frames, which a live
stream gives as null.

The library and the module `cuju.render` read a recording of at most 256 MiB once decompressed,
with a header of at most 1 MiB, at most 32 players and at most 50,000 frames, far above the
largest that cuju writes, a tournament match of 5000 steps of eleven a side, which takes 41 MB in
version 2. A file of version 1 gives the size of a frame of its players, a file of version 2 the
keyframe interval of 100, and a file past any of these limits ends its reading with an error that
names the limit. A header holds the numbers of JSON alone, which leave out NaN and the infinities.
Each field of the header that the library reads holds its type. The title, the scenario and the
name of each team are text or null, each player names its team, 0 or 1, its index and its flags,
true or false, and the steps per second are a number above 0. Importing a file whose header holds
another type ends with an error that names the field, and such a file copied into the folder of
the library lists under its identifier. A title or team name that names a message by `title_id` or
`name_id` names one of the names that cuju makes, under `server.names` or
`server.tournament.label`, and the library reads a name with any other message as its text. A last
frame of version 1 cut short is left out, as the page leaves it out.

The header also holds a `provenance` object, which records what was known of the recording's
origin when it was made. Every recording names the version of cuju that made it as
`cuju_version` and its `source`, which is `requested_match`, `human_game`, `challenge`, `recorder`
or `live`.
A requested match adds its resolved `seed`, the `scenario`, the registry identifiers of both
`teams`, the `controls` of each side, the `agent_counts`, the engine's `action_set` and the
`ability` that played on each side. A game on the Play page adds its seed, scenario, the sides of
the people as `humans`, the action set and the ability. A match of a tournament adds `tournament`,
with the identifier and name of the tournament, the name of its stage, the label of the match and
its key, the names of its two entrants as the tournament shows them as `names`, home first,
which also name the teams of the recording, and the `ability` that the tournament gave each side,
home first, null for the scenario's own, and a match of a set length
adds `length`. An agent's attempt of a challenge adds the `challenge`, the index of the `attempt`
from zero, its seed, the scenario, the `teams` with the registry identifier of the left team or null
for a Python policy, the `competitor` by name, the `policy` name of a Python policy, the agent
counts, the action set and the ability. A recorder and a live source add the
`environment` index of the batch, and leave the seed unknown, since a batch may have been reset
with another seed before the capture began. A field that is absent means its value is unknown. A
seed above `2**53 - 1` is written as a decimal string, so the page reads it exactly. A registry
identifier names a team of this machine, whose files may have changed since the match was played.

The library summary beside each recording carries the same provenance, and a recording copied into
the folder without a summary gets its provenance from its header. Provenance adds to the header
alone and leaves the version 1 frame layout as it was, so recordings made before it open as before,
with an empty provenance.

A frame opens with eight signed 32 bit integers, seven floats and four more integers, as the table
lists them.

| Field | Type | Content |
| ----- | ---- | ------- |
| step | int32 | the step of the episode, 0 at the reset |
| game mode | int32 | GRF's game mode, 0 in normal play and 1 to 6 for the restarts |
| score | int32 twice | the goals of the left team, then of the right team |
| ball owner team | int32 | the team that owns the ball, as GRF's raw observation gives it, or -1 |
| ball owner | int32 | the owner's index in the header's list of players, or -1 |
| clock | int32 | the match time in milliseconds, 90 minutes over the 3000 steps of a full match |
| flags | int32 | episode boundaries, called offside and scorer, as described above |
| ball | float32 seven times | the position of the ball, then its rotation as a quaternion |
| foul offender | int32 | the player who committed the referee's current foul, or -1 |
| foul victim | int32 | the player fouled, or -1 |
| foul kind | int32 | 0 for none, 1 for a foul, 2 for a yellow card and 3 for a red card |
| offside | int32 | the called player when flag 4 is set, otherwise the first candidate, or -1 |

The joints of every player follow, seven signed 16 bit integers per joint, fourteen joints per
player in the order of the header. The first three hold the world position in steps of 2 mm, which
spans 65 m either way of the center spot, and the last four the rotation as a quaternion, x, y, z
then w, in steps of one part in 32767. A full match of eleven a side occupies 13 MB of frames
before compression and 12 MB in a file of version 1, half the size of the same match stored as
32 bit floats, and 4.4 MB in a file of version 2. Every
position is in the frame of the pitch, with the center spot at the origin, the left team defending
negative x and the z axis pointing up.

Three runs of one byte per player close the frame, each padded with zeros to a multiple of four
bytes. The first holds bits, 1 for a player on the pitch, 2 for a yellow card, 4 for a red card
and 8 for a player that an agent controls on the step, so a red card sets 2 and 4 together.
Recordings of an older cuju carry no 8, and the page then marks the agents' players of the header.
The second holds the kind of the player's current animation
in GRF's numbering, 8 for a shot, 4 to 6 for the passes, 9 and 10 for a deflection and a catch and
13 for a slide among them. The third holds 0 for a player who did not touch the ball during the
step, and otherwise 1 plus GRF's kind of the touch, 1 for a kick, 2 for another intended touch and
3 for an accidental one.

A live stream sends the same bytes uncompressed.

A page that asks a live source for annotations, with `annotations=1` beside `sequence=1`, receives
a header with `stream_annotations` set to 1. Between the frames, such a stream sends batches of
annotations, each made of the serial `2**64 - 2`, the length of a UTF 8 JSON object as an unsigned
32 bit integer and the object. Its `records` take the form of the section `ANNO` of version 2, with
`f` holding the serial of the annotated frame. The page of cuju 0.2.0 asks for no annotations and
reads the stream as before.

### Version 2

A file of version 2 adds two fields to the header, `frame_count`, the number of frames, and
`keyframe_interval`, the number of frames from one keyframe to the next, 100 in the files that cuju
writes. Sections follow the header, each made of a tag of four ASCII letters, the length of its
payload as an unsigned 32 bit integer, the payload and zeros up to a multiple of four bytes. A
reader keeps the first section of each tag and skips the tags it does not know, so a later version
can add sections that an earlier reader passes over. The section `FRMS` holds the frames, and every
file has it.

The frames section stores each field of the frames as a lane, the values of that field in every
frame in order, and its values decode to the frames of version 1 bit for bit. The coding starts
afresh at every frame whose index is a multiple of the keyframe interval, a keyframe, so a frame
decodes from the keyframe at or before it, and a reader that seeks decodes at most one interval of
frames. The page decodes every frame when it opens a recording, and `cuju.render` decodes from the
keyframe before the first frame that it reads, so the library reads the last frame of a recording
for its summary at once.

A lane of 16 bits stores each value zigzag coded, so that 0, -1, 1 and -2 become 0, 1, 2 and 3. A
run of such lanes stores the low byte of every value of its first lane, then of its second lane and
so on, and the high bytes after all the low bytes. A lane of 32 bits stores four such planes, the
lowest byte first, and a lane of 8 bits stores its bytes as they are. A value coded as a difference
is the value less the value of the frame before, wrapped to the width of its lane, and a keyframe
stores the value itself. A value coded as a difference of differences takes the difference twice.
A byte coded as an exclusive or is the byte XOR the byte of the frame before, and a keyframe stores
the byte itself.

The section holds the runs of lanes in the order of the table, where n is the number of players and
p the bytes of each of the three byte runs that close a frame. The joints count from 1 to 13 in the
order of the header, after the root joint `player`. Lanes of the joints go joint by joint, then
component by component, then player by player, and lanes of the root go component by component,
then player by player.

| Run | Lanes | Width | Coding | Content |
| --- | ----- | ----- | ------ | ------- |
| head | 19 | 32 bits | difference | the 19 words of the frame head, the floats of the ball by their bits |
| root position | 3 n | 16 bits | difference of differences | x, y and z of the root joint of each player |
| root rotation | 4 n | 16 bits | difference | the rotation of the root joint of each player |
| local rotation | 39 n | 16 bits | difference | x, y and z of each joint's rotation relative to its parent |
| sign | 13 n | 8 bits | exclusive or | 1 where w of the local rotation is negative, else 0 |
| local offset | 39 n | 16 bits | difference | each joint's position relative to its parent, in the parent's frame |
| rotation residual | 52 n | 16 bits | none | each joint's rotation less the predicted rotation |
| position residual | 39 n | 16 bits | none | each joint's position less the predicted position |
| closing bytes | 3 p | 8 bits | exclusive or | the three byte runs that close a frame |

A reader rebuilds the joints of each player in the order of the header, so a parent comes before
its children, with `U = 32767`, the parent's decoded rotation `P` and position, the local rotation
`k` and the local offset `o`, all as integers.

1. `k` takes x, y and z from its lanes, and w is the integer square root of the larger of 0 and
   `U*U - x*x - y*y - z*z`, negated where the sign lane holds a value other than 0.
2. The rotation of the joint is the Hamilton product `P k`, each component `c` of it turned into
   `floor((2*c + U) / (2*U))`, plus the rotation residual, wrapped to 16 bits.
3. With `a` the x, y and z of `P` and `w` its w, the vector `s = U*U*o + 2*w*cross(a, o) +
   2*cross(a, cross(a, o))` turns the offset, and the position of the joint is the parent's
   position plus `floor((2*s + U*U) / (2*U*U))` for each component, plus the position residual,
   wrapped to 16 bits.

The Hamilton product takes quaternions stored x, y, z and w, as the frame stores them.

```text
x = w1*x2 + x1*w2 + y1*z2 - z1*y2
y = w1*y2 + y1*w2 + z1*x2 - x1*z2
z = w1*z2 + z1*w2 + x1*y2 - y1*x2
w = w1*w2 - x1*x2 - y1*y2 - z1*z2
```

Every product and sum of these steps is an integer below `2**53`, so a reader in double precision,
as JavaScript computes, reaches the same integers as one in 64 bit integers. The writer chooses the
local rotations and offsets and holds each one where it moves by one step or less, so the lanes
change slowly and gzip finds them, and the residuals carry whatever the prediction misses, which
keeps every frame exact. The shipped full match of eleven a side takes 4.4 MB in version 2 and
11.7 MB in version 1, and the shipped match of five a side 1.1 MB and 2.7 MB.

The section `ANNO` holds the [annotations](#annotations) of a recording that has them, as a UTF 8
JSON object whose `records` list one record for each frame and player, in the order of the frames.
A record holds `f`, the index of its frame, and as it needs them `p`, the index of its player in
the header, absent for the whole match, `v`, an object of named numbers, `t`, the text, `a`, the
action chosen, and `k`, the likely actions as pairs of an action and its probability, the most
likely first. A reader that meets a malformed section plays the frames without annotations.

## Folder and server

The renderer's folder holds eight subfolders, `matches` for the recordings, `teams` for the
submissions, `live` for the announcements of running sources, `requests` for the history of
requested matches, `tournaments` for the tournaments with their ratings and presets, `scenarios`
for the scenario files of set match lengths, `challenges` for the leaderboards and `achievements`
for what the teams of the registry earned. A ninth, `videos`, holds the videos that the page
exports, the three latest of the running server beside the one in progress, and the server empties
it before its first export. A tenth, `index`, holds the index of the moments of the library, one
JSON file per recording, which the server rebuilds from the recordings whenever it needs. The
folder `languages` holds the languages a person adds, one JSON file each. Each
leaderboard is one JSON file named after its challenge, and each
team's achievements one JSON file named after the team, both written through a temporary file
under a lock and read with every field checked, so a file or an entry of the wrong form is skipped
with a warning through the logger `cuju`. The file `samples.json` names the sample matches that
the library has received, `sample-teams.json` names the team that the starter team became, and
`tutorial.json` keeps the lessons that pages reported done. Requested matches play one at a time,
and each request keeps a small JSON file in the subfolder `requests`, with its teams, scenario,
resolved seed, ability, state, error and the times it was made, started and finished. The server
writes each file through a temporary file and removes any temporary file left behind when it starts.
A file that holds a field of the wrong type, edited by hand or written by a later version, is
skipped with a warning through the logger `cuju`, and the server starts with the rest of the
history.

A restart of the server marks every request that was waiting or playing as interrupted, and Retry
queues it again. A match that was playing when the server stopped runs in a process of its own,
which usually ends at its next report to the server, but one close to its end may still save its
recording. That recording then appears in the library while its request stays interrupted, and
its provenance names the same seed.

The variable `CUJU_RENDER_HOME`, or the option `--home`, moves the whole folder, so a project can
keep its own matches beside its code.

The server listens on the loopback interface alone, since its API deletes files and plays the code
of submissions, and it checks the loopback host on every request. Requests that change data also
check any
Origin header against the server's own address, including the scheme and port. Each request runs
on a thread of its own, and a thread that finished waits half a minute for the next request, so a
page that asks for its few hundred files makes few new threads. The server holds up to 128
connections waiting to be accepted, since a page opens its files many at once and Windows refuses
a connection beyond the queue. A page whose module fails to load all the same reloads once after
a second. A server on another
machine is reached through a tunnel, such as
the port forwarding of SSH, which makes it a loopback server of the local machine, as
[Remote use](#remote-use) describes.

While a server runs, the file `server.json` of the renderer's folder names its port, its process
and the key that lets a notebook frame its page, and the server removes the file when it stops,
on Ctrl+C, on a terminate signal and when the process that started it ends. `show` and
`cuju render open` read the file and ask the server whether it answers, so they reuse a running
server of the same folder and start one only when none answers, and they remove a file whose
process has ended. A server that `show` starts in the background writes its messages to
`server.log` beside it.

## Command line

`cuju render`, also `python -m cuju.render`, takes the option `--home` before its subcommand, which
picks the renderer's folder for that command alone.

| Command | Does |
| --- | --- |
| `cuju render` | serves the page and opens Home, or opens Home of the server that already runs for the folder |
| `cuju render serve` | serves the page until interrupted, with `--port`, `--open` to open the page and `--remote` for [Remote use](#remote-use) |
| `cuju render open TARGET` | opens a `.cjr` file, the identifier of a recording or a live source, or a URL of the page, with `--port` for a server that it starts |
| `cuju render app` | opens the page in a window of its own, with `--port`, `--route` and `--browser`, and adds or removes a launcher with `--install` and `--uninstall`, as [The app window](#the-app-window) describes |
| `cuju render team add FOLDER` | registers a submission folder or archive, with `--name`, `--format`, the control options and `--json` |
| `cuju render team list`, `show ID`, `set ID`, `export ID`, `remove ID` | lists, shows, changes with `--name`, `--format` and the control options, exports with `--out` or removes registered teams, as [Teams and requested matches](#teams-and-requested-matches) describes |
| `cuju render team sound ID KIND FILE` | gives a team the sound of a moment, checked as the page's upload is, removes it with `--remove` in place of the file, or lists the team's sounds without a moment, with `--json` |
| `cuju render play` | records a match between `--left` and `--right` on `--scenario`, with `--seed`, `--device`, `--left-ability`, `--right-ability` and `--json` |
| `cuju render sample` | adds the sample matches and the starter team again or restores them, or one with `5v5`, `11v11` or `starter-team`, or `sample-5v5` and `sample-11v11`, and `list` prints what the library holds of each, with `--json` |
| `cuju render tutorial` | prints the lessons for an agent and checks each one, with a lesson's identifier, `--json`, `--check` and `--reset`, as [The tutorial for agents](#the-tutorial-for-agents) describes |
| `cuju render doctor` | prints the diagnostic report, with `--json` and `--out`, as [Diagnostic report](#diagnostic-report) describes |
| `cuju render demo` | streams a live match between the built in AIs to the page, as [Quick start](#quick-start) describes |
| `cuju render tournament` | makes, checks, lists, shows, runs, cancels, awards, resumes and deletes tournaments and lists ratings, as [Tournaments](#tournaments) describes |
| `cuju render challenge` | lists the challenges with `list`, plays one headless with `run ID` and `--team`, `--attempts`, `--device`, `--no-recordings` and `--json`, or benchmarks teams with `bench`, `--team` for each, `--challenge`, `--workers`, `--keep-recordings`, `--json` and `--csv`, as [Challenges](#challenges) describes |
| `cuju render recordings` | lists the library with the group of each challenge run, one group with `--group`, the Trash with `--trash`, and moves a group with `--delete-group` or `--restore-group`, with `--json`, as [Recordings](#recordings) describes |
| `cuju render pack` | checks a presentation package with `check`, writes a new team with `new`, previews a package with `preview` or shows and sets the package of each side with `sides`, as lines or as JSON with `--json`, as [Presentation packages](#presentation-packages) describes |
| `cuju render search QUERY` | finds moments across the library, with `--limit` and `--json`, as [Searching moments](#searching-moments) describes |
| `cuju render captions RECORDING` | writes the captions of a recording or a `.cjr` file as WebVTT with `-o`, or as JSON with `--json` |
| `cuju render video SOURCE` | exports a range of a recording as an MP4 video, as [Exporting video](#exporting-video) describes |
| `cuju render feed [SOURCE]` | prints the address of a clean feed, or of every source a feed may follow, as [Streaming with OBS](#streaming-with-obs) describes |
| `cuju render language` | writes a new language with `new CODE`, checks one with `check FILE`, and lists, adds and removes the languages of the folder with `list`, `add FILE` and `remove CODE`, with `--json`, as [Languages](#languages) describes |

`cuju render open` copies a recording file from outside the library into it, under a new
identifier, and opens the copy. A file whose bytes the library already holds opens that recording,
so opening the same file twice adds it once, and a file of the library's own folder opens as it is.
When a server of the folder runs, the command opens its page on the target and returns at once.
Otherwise it serves the page in the foreground on `--port`, 8780 by default, with the browser
opened on the target, until interrupted with Ctrl+C. A bare `cuju render` behaves the same way for
Home.

The commands explain what went wrong and what to do about it. A port that another program holds
names that program as another cuju server or another program, and suggests another port or
`--port 0` for a free one, and a port held by the server of the same folder names its address. A
missing file, a file that holds no recording, an identifier that names nothing and a recording in
the Trash each have a message of their own. A folder that is a file, lies under a file, or cannot
be created or written stops every command at its start, with a message that names the folder and
the option `--home`.

A command run with `--json` prints its error as JSON on standard output alone when it fails, an
object of `error`, the English text, and `error_id` and `error_values`, the message and its values
when the error carries one and `null` otherwise, so a script reads one answer whatever happens. A
failure exits with status 1, and arguments that do not fit exit with status 2. When the command
prints text, the error goes to standard error as one line.

In Python, the errors of the renderer read as the public classes they belong to, such as
`cuju.errors.ArgumentError` and `cuju.render.PolicyError`, and `dir(cuju.render)` lists the names
of `cuju.render.__all__`. The `repr` of a recorder names its environment, scenario, version and
state, the frames of the episode it captures, the episodes that ended and those it saved and
dropped.

## Remote use

A server on another machine, such as a training server, serves the page on its own loopback
interface, which the machine of the browser reaches through a tunnel. The option `--remote` of
`cuju render serve` prints the exact SSH command for the machine and port of the server. Inside an
SSH session it names the address and port that the session came in on, with the user that runs
the server, and elsewhere the name of the machine.

```sh
cuju render serve --remote
```

The command to run on the machine of the browser then reads like this one, and the page opens at
`http://127.0.0.1:8780/` there while the command runs.

```sh
ssh -N -L 8780:127.0.0.1:8780 user@training-server
```

The server then waits for the page and prints one line with the time when a browser first reaches
it, which confirms that the tunnel works. `cuju render serve --remote` on a port that a server of
the renderer already serves prints that server's SSH command as well, so the tunnel reaches the
server that runs. A tunnel that forwards another local port works the same
way, with the page at that port.

VS Code with its Remote SSH extension forwards a port from its Ports view, where adding 8780 opens
the page in the local browser, and VS Code often offers to forward the port by itself when the
server prints its address in the integrated terminal. A notebook of VS Code on a remote machine
shows the inline viewer once the port is forwarded. Google Colab needs no tunnel, since `show`
serves the page through Colab's own proxy, as [Notebooks](#notebooks) describes. A notebook of
Jupyter on a remote machine needs the same SSH tunnel as the page, and its inline viewer and link
then open through the tunnel.

## See also

- [Team presentation packages](presentation.md), the contract of a team's own presentation
- [States][cuju-states], the state format that the renderer reads, and the module `cuju.state`
- [Recipes][cuju-recipes], the Kaggle competition and the training loops that a recorder joins
- [Python reference](reference.md), the reference of `cuju.render`
- [cuju's API reference][cuju-api], the batch, its step observers and `cuju.state`

[cuju-api-step-observers]: https://github.com/AndreKoraleski/cuju/blob/main/docs/api.md#step-observers
[cuju-states]: https://github.com/AndreKoraleski/cuju/blob/main/docs/states.md
[cuju-recipes]: https://github.com/AndreKoraleski/cuju/blob/main/docs/recipes.md
[cuju-api]: https://github.com/AndreKoraleski/cuju/blob/main/docs/api.md
