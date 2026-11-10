# Rendering

In cuju, the **renderer** is a browser page that shows matches in three dimensions, with the
players, the ball, the pitch and the crowd drawn from the art of Google Research Football, or GRF,
and from free characters, and with sound mixed in the browser. It watches two kinds of source.
A **recording** is a match saved to a file,
which the page plays at any speed, forwards and backwards, and a **live source** is one environment
of a running batch, which the page shows while the batch plays. The renderer ships in the package
as the module `cuju.render`. Its server needs only Python's standard library beside cuju's own
dependencies, and its page runs in the browser.

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

The demo starts the server, or uses the server that already answers on its port, and plays a
match between the built in AIs in a process of its own, five a side by default. It opens the page
on that match as a live source, so play shows within seconds of the command, and one match follows
another until Ctrl+C, which ends the match, any server that the demo started and the command
itself. The option `--eleven` plays eleven a side, `--scenario` plays another shipped scenario,
such as `academy_corner`, `--port` names the port of the server, `--seed` fixes the seed and
`--no-open` leaves the browser as it is. A server that keeps another folder lists other sources,
so the demo then says so and opens the page at its start, and the option `--home` of
`cuju render` gives both the same folder.

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
[step observer](api.md#step-observers) of its batch, so from its creation on it captures every
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
A recorder that captures by hand does so after every step to preserve consecutive motion. Each
recorder takes one batch of a `MultiDeviceBatch`, as a live source does. A recorder that fails
while it captures by itself, from a full disk for example, leaves its batch with one warning
through the logger `cuju`, and the batch steps on.

A full match of eleven a side takes 3001 frames with automatic resets and 3002 without, about 12 MB
on disk, and one of five a side about 1 MB with the built in AI on both sides and up to about 5 MB
when agents keep the players moving. A full match of
eleven a side plays and records in about half a minute on one core of a laptop processor. The
library keeps each recording as a `.cjr` file beside a small summary that the page lists. The
summary also holds the favorite mark, tags and notes that the page edits, and the time a recording
went to the Trash, so every one of these changes rewrites the small file and leaves the frames as
they are. Deleting a recording on the page moves it to the Trash, which keeps both files on disk
until a recording is deleted from there for good.

Two sample matches ship with the renderer, a full match of eleven a side and one of five a side,
both played by the built-in AI. The first start of the server copies each into the library as
`sample-11v11` and `sample-5v5`, where they appear on Home and in Recordings and open in Watch like
any other recording. The folder notes each sample it has received in `samples.json`, so a deleted
sample stays deleted, and a recording of the same name stays as it is. A sample in the Trash stays
there when the server starts, and Restore brings it back. The command `cuju render sample` adds
both samples again, and `cuju render sample 11v11` or `cuju render sample 5v5` adds one. A sample
that sits in the Trash comes back from there with its folder, tags and notes, and the command says
which samples it restored and which it added.

The page opens a recording in stages and shows each on a bar over the view, the download with its
share, the reading of the frames, and the players and the stadium while their files still load. A
background worker of the browser unpacks the recording and reads its frames, so the page keeps
drawing and loading meanwhile, and where a worker cannot start the page reads the recording itself
into the same frames. The art of the players, the ball, the goals and the stands loads all at once
beside the recording, and the players of a recording are built once, with their models. The rest
loads when the page first needs it, the montage of Home when Home shows, the sounds when the sound
is turned on, and the models and animations of other characters when a team wears them.

## Live sources

A live source streams one environment of a running batch to the page. The environment variable
`CUJU_RENDER` gives every batch of a process a source, with `on` for environment 0 or an index for
another environment, the call `cuju.render.watch` gives one batch a source from code, and
`cuju.render.show` gives one and opens the page on it. Every
batch that cuju creates while the variable is set calls `cuju.render.on_batch_created`, which
gives it a source, and either way the source joins the [step observers](api.md#step-observers) of
its batch.

```python
source = cuju.render.watch(batch, environment=0, title='Self-play, league match')
```

A source listens on a free port of the loopback interface and announces itself with a small file in
the renderer's folder, which the server lists and relays to the page. While a viewer watches, the
source reads passages of 50 consecutive steps, five seconds of play, and starts the next passage
when the wall clock has caught up. A batch that runs faster than real time therefore reaches the
page as continuous passages, which the page joins with cuts, and pays for about ten state reads per
second of wall time, about 5 milliseconds each. A batch that runs slower than real time is shown
step by step. Each step checks whether the batch has step observers, and a batch without any
does nothing more. An attached source also checks its viewers under a lock and reads states for
viewers or the backlog.
On the GPU, each read also waits for the step in flight, as `get_state` does, and a GPU batch that
queues many steps ahead of the device may take tens of seconds to send its first frame.

A source keeps the last 10 seconds of the steps it read, and a viewer who joins late receives them
first, so a second viewer, or a page reopened, starts with that history. The first viewer of a quiet
source starts at the present. The variable `CUJU_RENDER_BACKLOG`, or `backlog=True` for `watch`,
makes the source read every step, watched or not, at the cost of one state read per step, so that
every viewer starts 10 seconds back.

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

The grid reads states only while a viewer asks for it, and stops 3 seconds after the last request,
so an unwatched source pays one attribute check per step for it. While it reads, the reads stay
small and bounded four ways. They happen at the end of a step of the batch, as the stream's do,
and no step reads more than 4 states for the grid. The grid reads at most 10 states a second of
wall time, the pace at which a watched stream reads its own, and starts a pass over the range at
most twice a second, so a grid of 4 environments refreshes twice a second, one of 16 about every
1.6 seconds and one of 64 about every 6.4 seconds. After each step that read, the grid also waits
until its reads amount to at most a twentieth of the wall time, which a slow machine reaches first.
Each read leaves every observation, reward, done flag and state of the batch as it was, bit for
bit, and consumes no random numbers. On a laptop with 64 environments of eleven a side, a state
read and the gathering of its fields took about 2 milliseconds on the CPU and 3.5 milliseconds on
CUDA, and a watched grid took about 3.5 percent of the wall time on either. The stream of the
source goes on beside the grid at its own cost.

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
cuju render team export t-20261106-101500-3fa9 --out baseline.zip
```

The team add command also accepts exported zip files, keeping the team name, format, control
settings and assets. The option `--name` can rename the import.

A match requested on the page plays in a process of its own on the CPU and becomes a recording in
the library. The play command also takes a device. Each submission runs from its own folder,
with its own modules, as on Kaggle. Full matches follow the format of the team, five or eleven a
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

A submission is Python code that runs with the permissions of the server's user, so only trusted
code belongs in the registry, and a submission that imports Kaggle's helpers needs the package
`kaggle_environments` installed beside cuju. A submission that fails ends only its own match, and
the page shows its error. A match that runs past 30 minutes ends, and the page cancels a waiting or
running match on request.

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
seconds and brought to the level of the other sounds on the page.

A team also holds up to four sponsors, wide images made in the same editor from uploaded images and
drawing, which the advertising boards around the pitch show while the team plays. Boards alternate
between the sponsors of the two teams and fall back to GRF's boards. The fans of a team wear one to
four colors of its choosing, its kit's colors by default, and fill the stands behind its goal and
its half of the side stands.

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

### Export

A team leaves the page as its submission folder, a zip archive with `main.py` and the submission's
files at its top, as Kaggle reads them, and a folder `cuju-team` that holds the team's format,
style, roster, images, sponsors, model and celebration clips. Kaggle ignores the extra folder, and a
submission folder that holds one brings the whole look back when it is added to a registry again,
on the page or from the command line, each file checked as an upload is. The built in AI exports its
look alone.

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
Commands, Settings and Fullscreen sit at the right end of the bar. On a narrow screen the tabs
fold into one menu of pages.

Commands, or Ctrl K on any page, opens the **command palette**, a search field over a list of
everything the page does. The list holds every page, the live sources and the eight newest
recordings, a game on Play in each listed scenario, a request for a match, the settings of sound,
theme, broadcast mode, player labels, motion and the presets of the presentation, the choices of
the View menu, which are the cameras, the arenas, the four times of day, the weather and
fullscreen, every player of the open match to follow with the Follow player camera, and the topics
of the Help page. Typing narrows the list, with the letters of each word in order anywhere in a
name, so `gotm` finds Go to Teams and `follow 10` finds the player with that number. Words that
belong to an action also find it, such as `volume` for Mute. The arrows move through the list,
Page Up and Page Down move further, Enter runs the chosen action, a click runs any action and Esc
closes the palette. Focus then returns to the control that held it before. Ctrl K reaches the
palette from everywhere except a text field, which keeps its own keys, and an open palette
releases a captured pointer as any dialog does.

A first visit finds help along the way. Each page but Help shows a short tip in its lower left
corner after a moment, which points to the next thing to try, such as the command palette on Home
or the camera keys on Watch once a match is open. Got it puts that tip away for good, the button
No more tips turns every tip off, and the setting Tips for new visitors turns them on again with
every tip back. The browser keeps each dismissal. The main controls carry a short line of help,
which shows beside a control when keyboard focus reaches it, and under the pointer for a control
without a tooltip of its own. Esc, a click or leaving the control hides it.

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
The Match menu opens a
recording file from the computer, takes an address, leads to the Recordings and Matches pages, lists
the goals of the open match, each of which jumps to six seconds before it, and lists the live
sources and the six newest recordings, with a count of the live sources on the menu's button. The
address field takes the identifier of a live source or of a recording, such as
`m-20261106-105640-3a3f`. The View menu chooses the camera, turns broadcast mode, fullscreen and
the 2D view on and off, sets the hour, the weather and the arena, and sets the quality and the
theme. A recording
also opens when its file is dropped anywhere on the page. The view shows a spinner while it waits
for a live source to send its first step, and a bar of progress while a recording downloads.

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
and F2 at hand. The count above the list gives the total size of the recordings of the library,
or of the Trash in the Trash view.

The search also reads the tags and notes of each recording. Three more filters narrow the list,
Favorites to the recordings marked as favorites, Source to requested matches, played games,
recorders, live sources or recordings of unknown source, and Result to the matches the left team
won, those the right team won, draws and recordings whose score is unknown. Details opens a panel
above the list for the selected recording, with a Favorite mark, tags separated by commas, up to
twenty of at most forty characters each, and notes of up to ten thousand characters, which Save
details keeps and Close or Esc leaves. The panel also lists the provenance of the recording, the
source, the version of cuju and, where they are known, the seed, scenario, teams, controls, agent
counts, action set, ability and environment, as described under Recording format. A field that the
panel leaves out is unknown. Favorites show a star beside their title, and the first three tags
follow it.

Delete moves the selected recordings to the Trash at once, and a message says where they went. The
View filter switches between the library and the Trash, which lists the recordings deleted from the
library with the same search, filters and sorting. In the Trash, Restore returns the selected
recordings to the library with their folder, details and frames as they were, and Delete
permanently removes their files from the disk after a question, which cannot be undone. Only a
recording already in the Trash can be deleted for good. A recording of the Trash opens in Watch
once it is restored, and the Trash keeps using disk space until its recordings are deleted.

**Matches** requests a match between two teams of the registry. Two cards pick the left team,
which plays at home, and the right team, which plays away. Each card shows the count, assignment,
fixed selection, goalkeeper and action set, and has an Ability control. The scenario list offers
full matches of the team format and academy scenarios, and a short text under it gives the chosen
scenario's players a side, length, difficulties, the events that end an episode and, for an
academy, its drill. A seed field takes a whole number or stays empty for a random one. Each
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
It lists the pages, getting started steps, Watch shortcuts, Play controls and keyboard navigation.
Its links open the full guide and repository.

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
up to 30 minutes within an 80 MiB memory budget, about 15 minutes for eleven a side.
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

The Grid button beside these controls, and the Grid of environments entry of the View menu, open
a panel over the view with many environments of the same batch at once. Each tile is a small 2D
view of one environment, from above as in the 2D view, with its index, its score and its clock
along the top, and the tile of the environment that the main view shows carries a border. The
tiles refresh at the modest pace that the grid of environments under Live sources describes, and
a tile that the source has not read yet says it is waiting. The Tiles field sets 4, 9, 16, 25,
36, 49 or 64 tiles, up to the first size that holds the whole batch, and the choice stays in the
browser. Previous and Next, or Page Up and Page Down on a tile, move to the neighboring page of
environments, and the panel names the range it shows.

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
under the roof line, off the seats and clear of the players' bodies. After 20 seconds without
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
offer for good in that browser.

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
Any other controller reports its own layout, and a notice offers to set it up. The setup, also
on the controls card and in the pause menu, first asks the style of the controller, Xbox,
Nintendo or PlayStation, preselected from the id the browser reports. It then asks for each
button in turn, the four face buttons, the bumpers, the triggers, the two system buttons, the left
stick and the D-pad, drawing each on a small sketch of the controller, and takes the next press,
whether the controller reports it as a button or as an axis. A trigger or button read as an axis
counts as pressed past half its travel. Skip keeps what a position had, Back returns a step, and
Cancel or Esc leaves the layout as it was. The page keeps the style and the layout in the
browser's storage for each controller id, so two people each set up their own controller, and
before the style is chosen a press on another controller moves the setup to that one. The controls
card also shows the id the browser reports and whether its mapping is standard or custom.

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

Esc or Start opens the pause menu, which pauses the game on the server and offers Resume, the
controls, the controller setup, Quit, Home and Quit to Home. The paused picture and the end of a
game fall silent. Home pauses the game and opens Home. Return to Play to Resume or Quit. Quit to
Home ends the game and opens Home. A page that hides pauses its game, a game that hears nothing from
its page for eight seconds waits for it and carries on by itself as soon as the page is heard again,
and after two minutes of silence the game ends. A game that ends, at full time or on Quit, lands in
Recordings when the setup asked for it, up to where it stopped, and the card at the end offers to
watch it on the Watch page with every feature of the viewer. Restart transitions, replays and
celebrations stay off during a game, so play never waits for the page, while the scoreboard, the
clock, the goal graphic and the sound remain. The server plays one game at a time, independently of
its queue of requested matches. Leaving Play for another page pauses the game, and returning
lets it resume. Losing window focus releases the keyboard inputs. The end card offers Play again
with the same setup, New game to return to setup and Home. The Play page calls a natural ending
Full time when the scenario is a full match, the final frame marks an episode end and both the
step and the clock reach the configured duration. Other natural endings show End of episode.
A saved game needs at least one played step. Its stream stays separate from the list of live
training sources.

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
    stage sets. Every pair meets at most once. Such a pairing always exists while each entrant has
    met fewer than half the field, so a Swiss stage plays at most half as many rounds as it has
    entrants, rounded up.
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
for one stage, which overrides the default.

| Setting | What it sets |
| ------- | ------------ |
| Scenario | Any scenario that every entrant can play, by default the Kaggle match, or five against five when every registered team is five a side. Stages may use different scenarios and formats, such as groups of five against five and a final of eleven against eleven, when every entrant who could reach a stage can play its scenario. |
| Match length | The steps a match lasts, from 50 to 5000, ten steps a second, or the scenario's own. |
| Ability | The ability of the built in AI sides, which plays beside a team or a person, and of a built in AI entrant that has no ability of its own. |
| Legs | The matches of a tie, from 1 to 10, the higher seed playing the last leg at home, and goals adding up across them. The final may have its own count. |
| Drawn ties | An ordered list of ways to settle a tie that ends level. Away goals count when the legs are even. A replay, up to five, is one more match. A deciding match plays a chosen scenario twice, such as an academy drill, each side attacking from the left once, and adds the goals of both. Lots drawn from the tournament seed always come last and always decide. |
| Points | The points for a win, a draw and a loss, any whole numbers from minus 100 to 100. |
| Tiebreakers | An ordered list of what separates entrants level on points, goal difference, goals scored, fewer goals conceded, the matches between them, wins, away goals, fair play from cards, Buchholz, the points of the opponents met, and lots from the seed, which always come last. |
| Seeding | For the first stage, at random from the seed, by hand in the order of the entrants, or by rating. For a later stage, by the standing of the stage before it, at random or by rating. |
| Matches at once | How many matches of agents play at the same time, from 1, the default, to 8. |
| Forfeit score | The goals by which a match awarded by hand is won, 3 by default. |

The settings of each format, the bracket, the stop of a knockout, the third place match, the reset
of a grand final, cycles, groups, pots, qualifiers, best places, rounds, the points of a bye, laps,
what a draw does and how many advance, are described with their formats above. A setting that
cannot work, such as more Swiss rounds than allow a pairing without rematches, groups of one, a
bracket too small for its entrants, a stage that receives fewer than two entrants or a team in a
scenario of another format, is refused with a message that names the setting, the stage and why.

Ratings come from earlier tournaments. Every match of a tournament moves the rating of both
entrants by the Elo formula, 20 points for an upset at most, and a new entrant starts at 1500.
A registered team, the built in AI at each ability and each person by name keep their own rating.
An entrant's rating may also be set by hand, and seeding by rating uses the ratings as they stand
when the tournament is made.

### Determinism

The same configuration and **tournament seed** give the same draw and the same seed for every
match, whatever order the matches finish in. Each match has a key, such as `0/w4-1/2` for the second
leg of the first semi-final of the first stage, and its seed comes from the tournament seed and that
key. The draw of groups, pots, random seeding and lots each draw from the tournament seed and their
own purpose. So a tournament repeats with the same seed, and a match that a stop cut short plays
again from the start with the same seed and gives the same result.

### Presets

A preset holds a tournament's format, its stages, defaults and seeding, without its entrants. Those
that ship adapt to the number of entrants where their format allows.

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
2. **Entrants** adds registered teams one at a time or every one at once, the built in AI at an
    ability, or four of them at rising abilities, and people by name, with the built in AI or a
    team of dynamic assignment as their teammates. Each entrant may be renamed, given a rating and
    moved up or down, which is the seeding when it is manual, or removed.
3. **Settings** names the tournament, takes its seed or draws one, and sets the seeding, the
    scenario, match length and ability of every stage, the matches at once and the forfeit score.
4. **Stages** is the advanced editor. Each stage is a card with every setting that its format
    reads, the ordered lists of tiebreakers and ways to settle a tie, and buttons to add, move and
    remove stages. Edit as JSON shows the stages and defaults as JSON to change as text.
5. **Review** checks the tournament on the server and shows each stage with its entrants, those
    who advance, its scenario and the draw of its first round or its groups, or the reason it
    cannot be made. It also saves the format as a preset. Start tournament begins it.

An open tournament shows its state, seed and progress, the matches playing now, and buttons to
cancel it, resume it after a failed match, hold its trophy ceremony, run it again with the same
settings and a new seed, or delete it, which leaves its recordings in Recordings. Its stages are
tabs. A knockout or a double elimination shows its **bracket**, one column a round, each tie between
the two that feed it, with the play-in round, the losers bracket, the grand final and the third
place match in sections of their own, and a bracket wider than the page scrolls sideways. Leagues,
groups, Swiss rounds, ladders and the challenges of a king show **tables**, with the places that
qualify marked, a caption that names the order of the tiebreakers, and a line for each entrant that
stands above another on equal points that names the tiebreaker that placed it there. **Fixtures and
results** list every round with its matches, their scores, how a tie was decided, the progress of
a match that plays, and Watch, which opens the recording of each match. The page follows a running
tournament as it plays and announces a match that waits for a person and the end of a tournament.

A match with a person shows **Play now**, which starts it as a game of the Play page with the
tournament's scenario, length, abilities and match seed. The person's name stands on the
scoreboard, and two people in one match play the game for two. A game that reaches its end gives
the result, and the end card leads back to the tournament. A game that ends early, by Quit or a
lost page, leaves the match to be played again. **Award** gives a match to either side by the
forfeit score, for a person who cannot play or a team that keeps failing.

The **trophy ceremony** of a finished tournament opens the last match that the champion played on
the Watch page at its end, and holds the podium and confetti of the show after a match, with the
champion's players on the steps in the champion's colors, the champion's name, and the tournament
won with the runner up beneath it. Close ends it.

### The command line and the server

```sh
cuju render tournament new --preset world_cup --name "Office cup" --seed 7 \
    --team t-20261106-101500-3fa9 --builtin 0.3 --builtin 0.8 --person Ana --run
cuju render tournament list
cuju render tournament show t-20261110-090000-1a2b
cuju render tournament run t-20261110-090000-1a2b
cuju render tournament cancel t-20261110-090000-1a2b
cuju render tournament presets
```

The new command makes a tournament from a preset, `quick_cup` by default, or from a JSON file of a
whole configuration given to `--config`, with the entrants in the order of the options `--team`,
`--builtin`, with an ability or `any`, and `--person`. The options `--seeding`, `--scenario`,
`--length` and `--concurrency` change the preset. A running server plays a new tournament, and
`run` plays it in the terminal until it ends or waits for people, who play their matches on the
page. One process at a time runs a tournament, and a lock file beside it names the process, so the
server leaves alone a tournament that `run` plays, and the page follows it. A cancel from either
reaches the process that runs it.

The server answers `GET /api/tournaments`, `GET /api/tournaments/ID`, `GET
/api/tournaments/presets`, `GET /api/tournaments/ratings`, `POST /api/tournaments` with a
configuration, `POST /api/tournaments/check`, which resolves a configuration and returns its draw,
`POST /api/tournaments/ID/cancel`, `resume`, `play` and `forfeit`, `POST
/api/tournaments/presets/NAME`, and `DELETE` of a tournament or a preset, with the same Host and
Origin checks as every other route.

Each tournament lives in a JSON file of the folder `tournaments`, with its resolved configuration,
the result of every match and its state, written through a temporary file. A file that cannot be
read is skipped with a warning, and the server starts with the rest. A restart of the server
resumes every running tournament where it stopped, and a match that was playing plays again from
its start with the same seed. The ratings and the presets of the user live in `ratings.json` and
`presets.json` of the same folder. A match length writes a small scenario file into the folder
`scenarios`, which plays the shipped scenario for that many steps, with the second half starting at
the same share of the match.

## Broadcast presentation

The page presents a match as a broadcast does, and covers the seams of the engine, the jumps of
players to their places at a restart, with the transitions of television. Settings turn each part
off.

**Lineups.** A recording opened at its start pauses for a pan across the ground under the team
sheets, with each team's goalkeeper, its lines from the back and its formation. Enter or a click
starts the match.

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
    number. Reduced motion settings keep the medal and name in place and omit the flash, the
    camera movement and the shine on the medal.
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

The Motion setting follows the system's preference for reduced motion by default, and Reduced or
Full sets it for the page alone. Reduced motion plays a match without the lineups, the
celebrations, the replays after goals, the transitions of restarts and decisions and the
post-match show, and the end of a recording opens its statistics in place of the show. A change
of camera and the flights of the free camera and of the Field page reach their view at once, the
ball trail hides, the preview of the team editor stands still and the animations of the page end
at once. R then plays the last goal again from three seconds before it in the current camera.

Three quality levels in the View menu set the resolution of the shadows, the pixel ratio, the
glow of bright lights, the particles of rain and snow, the detail of the crowd and the shadows of
the floodlights, and the page picks one from the device.

## Keyboard

Tab and Shift Tab move between controls on every page. Enter or Space activates a control.
Ctrl K opens the command palette outside text fields, as described under Page layout.
The skip link moves to the main content. Menus and lists use the arrow keys, Home and End.
Esc closes a menu or panel and returns focus to its opener. Dialogs keep Tab inside them.
Sliders use the arrow keys. Color fields accept a hex value beside the color picker.

Home cards open their pages. Watch keeps its playback and camera keys while the picture has
focus. Focused controls use their own keys, and text fields keep typing within the field. Space on
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
with Home available there and on the end card. Home pauses an active game. Quit to Home ends
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
header as UTF 8 JSON padded with spaces to a multiple of four bytes, and the frames back to back,
each of the same size and aligned to four bytes. Every number is little endian.

The header records the version, 1, the title, the scenario, the steps per second, 10, the names of
the fourteen joints and the parent of each, one entry per player with its team, its index within the
team, whether it is the goalkeeper and whether an agent controls it, the name and colors of each
team, the size of a frame and the number of frames, which a live stream gives as null.

The header also holds a `provenance` object, which records what was known of the recording's
origin when it was made. Every recording names the version of cuju that made it as
`cuju_version` and its `source`, which is `requested_match`, `human_game`, `recorder` or `live`.
A requested match adds its resolved `seed`, the `scenario`, the registry identifiers of both
`teams`, the `controls` of each side, the `agent_counts`, the engine's `action_set` and the
`ability` that played on each side. A game on the Play page adds its seed, scenario, the sides of
the people as `humans`, the action set and the ability. A match of a tournament adds `tournament`,
with the identifier and name of the tournament, the name of its stage, the label of the match and
its key, and the names of its people as `names` when it was a game, and a match of a set length
adds `length`. A recorder and a live source add the
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
then w, in steps of one part in 32767. A full match of eleven a side occupies 13 MB before
compression and 12 MB in the file, half the size of the same match stored as 32 bit floats. Every
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

## Folder and server

The renderer's folder holds six subfolders, `matches` for the recordings, `teams` for the
submissions, `live` for the announcements of running sources, `requests` for the history of
requested matches, `tournaments` for the tournaments with their ratings and presets, and
`scenarios` for the scenario files of set match lengths. The file `samples.json` names the
sample matches that the library has received. Requested matches play one at a time, and each
request keeps a small JSON file in the subfolder `requests`, with its teams, scenario, resolved
seed, ability, state, error and the times it was made, started and finished. The server writes each
file through a temporary file and removes any temporary file left behind when it starts. A file
that holds a field of the wrong type, edited by hand or written by a later version, is skipped
with a warning through the logger `cuju`, and the server starts with the rest of the history.

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
Origin header against the server's own address, including the scheme and port. A server on another
machine is reached through a tunnel, such as
the port forwarding of SSH, which makes it a loopback server of the local machine, as
[Remote use](#remote-use) describes.

While a server runs, the file `server.json` of the renderer's folder names its port, its process
and the key that lets a notebook frame its page, and the server removes the file when it stops.
`show` and `cuju render open` read the file and ask the server whether it answers, so they reuse a
running server of the same folder and start one only when none answers. A server that `show`
starts in the background writes its messages to `server.log` beside it.

## Command line

`cuju render`, also `python -m cuju.render`, takes the option `--home` before its subcommand, which
picks the renderer's folder for that command alone.

| Command | Does |
| --- | --- |
| `cuju render` | serves the page and opens Home, or opens Home of the server that already runs for the folder |
| `cuju render serve` | serves the page until interrupted, with `--port`, `--open` to open the page and `--remote` for [Remote use](#remote-use) |
| `cuju render open TARGET` | opens a `.cjr` file, the identifier of a recording or a live source, or a URL of the page, with `--port` for a server that it starts |
| `cuju render team add FOLDER` | registers a submission folder or archive, with `--name` and `--format` |
| `cuju render team list`, `export ID`, `remove ID` | lists, exports with `--out` or removes registered teams |
| `cuju render play` | records a match between `--left` and `--right` on `--scenario`, with `--seed`, `--device`, `--left-ability` and `--right-ability` |
| `cuju render sample` | adds the sample matches to the library again, or one with `11v11` or `5v5` |
| `cuju render demo` | streams a live match between the built in AIs to the page, as [Quick start](#quick-start) describes |
| `cuju render tournament` | makes, lists, shows, runs and cancels tournaments, as [Tournaments](#tournaments) describes |

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
it, which confirms that the tunnel works. A tunnel that forwards another local port works the same
way, with the page at that port.

VS Code with its Remote SSH extension forwards a port from its Ports view, where adding 8780 opens
the page in the local browser, and VS Code often offers to forward the port by itself when the
server prints its address in the integrated terminal. A notebook of VS Code on a remote machine
shows the inline viewer once the port is forwarded. Google Colab needs no tunnel, since `show`
serves the page through Colab's own proxy, as [Notebooks](#notebooks) describes. A notebook of
Jupyter on a remote machine needs the same SSH tunnel as the page, and its inline viewer and link
then open through the tunnel.

## See also

- [States](states.md), the state format that the renderer reads, and the module `cuju.state`
- [Recipes](recipes.md), the Kaggle competition and the training loops that a recorder joins
- [API reference](api.md), the reference of `cuju.render` and `cuju.state`
