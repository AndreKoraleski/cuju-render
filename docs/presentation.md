# Team presentation packages

A team presentation package lets a team decide how it looks, moves and sounds in the renderer,
with no installer and no change to the renderer's own files. The package travels inside the
team's `cuju-team` folder, so it goes wherever the team goes, through an exported zip, a
duplicate and an import on another machine. It brings its own models, clips, sockets, persistent
behaviours, material looks, reflexes and, when it likes, a worker module with arbitrary logic.
The renderer gives it a clean, early and exact view of the match to react to, and runs all of it
under a short list of limits.

Everything in a package is presentation. The engine never reads it, so a match plays bit for bit
the same with a package, without one, watched or unwatched. A package changes what the page
draws and plays, never the simulation, its observations, rewards, actions, recordings or seeds.

This page is the reference of the presentation contract, version 1.1, written so that a team
author can build a package from it. A package of version 1.0 plays as it is. The template that
`cuju render pack new` writes is the small example to start from, and the test package in
`tests/support/team` is the full example, with every part described here.
[Rendering](rendering.md) describes the renderer itself.

## Principle

A package may present its team however it likes, within six limits that the renderer enforces.

1. The match never changes. Package code never reaches the engine or the server.
2. A team never affects the opponent. A package addresses its own players, its own effects and
   the shared things it borrows on its own moments, and reads the opponent's players without
   being able to address them.
3. Package code stays sandboxed. A worker runs in an opaque origin with no network, no files, no
   server, no page and no storage, and reaches nothing of another team.
4. Budgets keep the page running. A team past its budget steps down a ladder of lighter looks,
   down to the stock look, and the rest of the page goes on.
5. The viewer's safety and preferences win. Mute, pause, a hidden page, the viewer's levels, the
   renderer's loudness and flash rules and reduced motion all apply to every package.
6. Readability. An effect that hides the ball or a player fades, and camera, overlay and
   environment requests are suggestions the renderer weighs.

A part of a package that breaks a limit while the match plays fades out over half a second and the
rest keeps playing.

The contract works on three levels. The manifest declares assets and reflexes, bindings from
events to actions that the renderer runs at once. Behaviours and tracks that the renderer
evaluates on every drawing give continuous motion. An optional worker holds arbitrary logic and
answers each frame of the match with commands.

## Making a package

`cuju render pack new FOLDER` writes a small working team into an empty folder, with an agent, a
team file, a manifest, a worker, a shader, a ring to attach and a short sound, and prints the
commands that come next. `--name` gives the team and its package a name of their own. The team
draws GRF's own figure, which carries the package's parts, so its players wear the spinning ring
over their heads, glow with each event of the team, bob gently and spark on every touch.

```
cuju render pack new my-team --name Lanterns
cuju render pack check my-team
cuju render pack preview my-team
cuju render team add my-team
```

`cuju render pack check PATH` reads a team folder, its `cuju-team` folder, its `presentation`
folder, the manifest `presentation.json` itself or an exported zip as the server and the page read
it. It runs every check of an import and of serving, the paths, kinds and sizes of the files, the
limits of a package and the manifest's own check, and adds what the page meets as it draws, the
static rules of the shaders of the section Shaders, the budgets by static count, the references
to nodes, clips, sockets and files, the contact markers, the loudness of every WAV sample and the
team's own `model.glb` by the rule of an import. It prints a readable report, or JSON with
`--json` for agents, and exits with 1 when anything is an error.

An error is what makes the server leave a part out or refuse the package, or what the page can
never run, a required feature this renderer lacks, a team model that import sets aside or a module
that does not parse. A warning is what the page holds back or degrades as it draws, and the rest
is information. Messages count reflexes, actions, behaviours and layers from 1, and a behaviour
with an `id` goes by its id.

The check also names the figures the team draws. Each player draws a model of the package, the
team's own `model.glb`, a shipped character or GRF's own figure, as the section GRF's figure
describes, and the information says how many players draw GRF's figure. On GRF's figure a node
of a socket or a behaviour that the figure lacks is a warning, which lists GRF's nodes, and so is
a clip role, a layer or a driver other than `grf`, since GRF's figure shows them on a model of
the package or the team's own model alone.

The check reads shaders by their static rules, and one rule of syntax catches an operator with
nothing after it, such as `return e + ;`. The page alone compiles shaders, before it draws, and a
shader of either mode that fails draws the standard material and the page names it in a notice.
The report's information counts the shaders it read and says it compiled none.
The check parses the worker and the worklet with Node.js when Node.js is installed, and says so
in its information when it is not, in which case the page is the first to read their syntax and
names a worker that does not load in a notice. A WAV sample shorter than one block of 400 ms
reads its integrated loudness as its mean over its own length, so the report shows it above the
momentary loudness, which spreads the sample over 400 ms, and the check says so.

`cuju render pack preview PATH` registers the package as a team under the name of its manifest, sets
it on a side, `--side left` by default, and opens the shipped five a side sample with the preview
panel. The package draws on that side alone, so a preview on the right after one on the left moves
it there. A second preview of the same folder or zip updates that team in place and keeps its
identifier and its kit. A team whose `team.json` names no kit takes the next kit of the renderer's
turn, as a team added on the Teams page does, so two such teams differ, and a match between teams of
alike shirts dresses the right team in its away kit. The sample's players draw the models of the
package's `models` and GRF's figure otherwise, so a package made for the team's own model shows on
GRF's figure in the preview and on that model in a match of the team. A server of the home that
already runs serves the page, and otherwise the command serves it until interrupted. `--no-open`
opens no browser and prints the address, and `--json` prints the address, the team's identifier, its
name and the side as one line of JSON for agents. The browser opens only on a machine with a
display.

The preview panel's buttons send the team's own events, and its meters show the team's budgets, the
flash governor, the loudness of the master and of the team's buses, and the newest lines of the
worker's log, in the page's language with its own decimal sign. The panel opens with `preview=left`
or `preview=right` in the page's address on that side, or with `preview=1` on the side whose package
loads. When the page offers its 2D view in the same corner, the panel sits below the offer. An agent
reads the same figures from `cuju.presentation.status()`, which also shows the level each package
runs at, its worker's state and sandbox, its budgets, the entities with their drivers, bounds and
behaviours, and the commands that wait for later renderer work. Setting
`cuju.presentation.settings.metering` to false holds every team at its rung of the ladder, which
helps when a slow machine or a headless browser draws an author's package.

The test package in `tests/support/team` is the full example, a manifest and a worker that use
every level of the contract, and `tests/support/package.py` builds its binary files and packs the
team as a zip. Import the zip on the Teams page, play a match of the team, and the browser
console lists any part of the manifest the server left out and why.

## Layout of a package

A package is the folder `presentation` inside the team's `cuju-team` folder.

```
my-team/
    main.py
    cuju-team/
        team.json
        model.glb
        presentation/
            presentation.json
            worker.js
            models/keeper.glb
            models/halo.glb
            audio/strike.wav
```

The manifest is `presentation/presentation.json`. Every other file sits in the folder or in at
most three levels of subfolders of it, under lowercase names of letters, digits, dots, dashes and
underscores. The folder holds at most 256 files and 80 MB.

| Kind | Extensions | Largest file | Check on import |
|---|---|---|---|
| Models and attachments | `.glb` | 30 MB | binary glTF 2.0, every buffer and image inside the file |
| Textures | `.png`, `.jpg`, `.webp`, `.ktx2` | 16 MB, 30 MB for `.ktx2` | the bytes of their kind |
| Sound | `.ogg`, `.mp3`, `.wav` | 16 MB, 30 MB for `.wav` | the bytes of their kind |
| Worker and worklet | `.js` | 2 MB | UTF-8, one self-contained module without imports |
| Data | `.json` | 2 MB | JSON |
| Shaders | `.glsl` | 256 KB | UTF-8 |
| WebAssembly | `.wasm` | 8 MB | the WebAssembly header |

The server checks every file when a team is imported, deletes what fails, and checks the files
again when it serves or exports them, so a file changed on disk after the import stays out. A
team's own `model.glb`, roster, kit, images and sounds keep their roles from `team.json`, and a
package adds to them.

The server reads each module as JavaScript does, past its comments, strings, templates and
regular expressions, and refuses one whose code holds the keyword `import`, as a static import, a
dynamic `import()` or `import.meta`, or an `export` with `from`. A slash right after a closing
brace reads as a division or as a regular expression depending on what the brace closes, so a
module writes that expression in parentheses. The server sends the sound worklet as JavaScript,
since the page loads it by its address, and every other module as plain text, which the page
reads and hands to the sandbox of its worker.

A team's own `model.glb` is a skinned binary glTF file of at most 30 MB. Its joints, the bones
that stand for GRF's nodes, come from `model.joints` in `team.json`, as the team editor saves
them, with a bone for `body` at least. A model without `model.joints` takes the joints the team
editor guesses from its bone names, such as `Hips` or `mixamorig:Hips` for `body`, and draws as
the team's model unless `team.json` names another in its style. A model whose joints give no
bone for `body`, or name bones the model lacks, is set aside on import, and
`cuju render pack check` reports it as an error.

## The manifest

The manifest is a JSON object. Its sections are all optional except `contract`.

```json
{
    "contract": "1.1",
    "name": "Lanterns",
    "requires": ["drivers.team"],
    "prefers": ["lookahead"],
    "models": {"goalkeeper": "models/keeper.glb", "byNumber": {"6": "models/beacon.glb"}},
    "rig": {
        "driver": {"outfield": "team", "goalkeeper": "team"},
        "sockets": {
            "gaze": {"node": "body", "forward": [0, 0, 1]},
            "core": {"offset": [0, 1.02, 0]}
        },
        "bounds": {"radius": 1.22, "height": 3.05, "clearance": 0.013}
    },
    "clips": {"move": {"space": "speed", "clips": [["Orbit", 0]]}, "lineup": "Arrival"},
    "behaviours": [{"type": "spin", "clip": "Orbit", "period": 20, "rate": 2.4}],
    "reflexes": [{"on": "winner.reveal", "do": [{"audio": "fanfare", "class": "moment"}]}],
    "audio": {"cues": {"fanfare": ["audio/fanfare.wav"]}},
    "worker": "worker.js"
}
```

The server checks each section on its own. A section that fails its check is left out with a
warning, and the page draws that part as it would without a package, so a mistake in one
behaviour leaves the clips, models and reflexes working. A key the contract does not name is left
out with a warning too. The warnings show in the browser console when the team is drawn.

### Versions and features

`contract` gives the version of the contract as `major.minor`. The renderer serves any package of
its own major version and a minor version up to its own, which is 1.1 here. Minor versions only
add, majors may change. A manifest of a newer contract stays on disk untouched, and the team shows
its stock look on this renderer.

`requires` and `prefers` list features by name. A required feature the renderer lacks drops the
package to the highest level it supports. A missing feature that only a worker uses, such as
`drivers.worker` or `overlay.offscreen`, drops the worker and keeps the manifest. Any other drops
the package to the stock look, the page names the feature in a short notice, and
`cuju render pack check` reports it as an error. A preferred feature the renderer lacks is
reported to the worker in its Hello, so it can choose another way.

This renderer implements these features.

| Feature | What it gives |
|---|---|
| `drivers.grf`, `drivers.team`, `drivers.worker` | the drivers of section Animation |
| `lookahead`, `lookahead.outcomes` | forecasts of contacts and outcomes |
| `inference.pass/1`, `inference.shot/1`, `inference.header/1`, `inference.volley/1` | the inferred events of version 1 |
| `inference.slide/1`, `inference.save/1`, `inference.goal/1`, `inference.sprint/1`, `inference.dribble/1` | further inferred events |
| `clips.markers` | contact markers in clips |
| `drivers.grf+layers` | GRF's joints with the package's clips over masked bones |
| `bend.ball` | the drawn path of the ball bent through the estimated contact of each touch |
| `ik.fabrik` | chains of bones that reach the drawn ball around a contact |
| `shader.custom`, `shader.sceneColor` | the package's own shaders, with the frame drawn so far |
| `post.layer`, `post.fullscreen` | passes on the team's own objects and, on its moments, the view |
| `geometry.worker`, `overlay.offscreen` | geometry a worker builds and drawing in overlay slots |
| `audio.worklet`, `audio.music` | the package's own sound processors and music stems |
| `camera.suggest`, `time.suggest` | camera and time suggestions on the team's own moments |
| `environment.sky`, `environment.lightning`, `fans.tifo` | moments of the sky, lightning and a tifo |

Contract 1.1 added every feature from `drivers.grf+layers` on. A feature that changes a shared
thing, a pass, a moment of the sky, a camera or a time suggestion, the bend of the ball, a reach or
a custom shader, plays only for a package that names it in `requires` or `prefers`, so a package
of 1.0 draws as it always did. Effects, lights, sound and the other sections need no feature.

### Models

`models` picks the model each player draws. `byNumber` maps shirt numbers to files and wins,
then `goalkeeper` for the keepers and `outfield` for everyone else. A player with no model of the
package draws the team's own `model.glb`, or the model its roster entry names. Each model is a
skinned binary glTF file, and its animations become the clips of its players.

### Rig

`rig` describes how the package's figures stand and move.

- `driver` names the driver of each role, `outfield` and `goalkeeper`, or one driver for both.
  The section Animation describes the drivers. The default is `grf`.
- `joints` maps GRF's nodes to bones of the package's models, as the team editor does for a
  team's own model, for the `grf` driver. When it is absent the page takes the team's own mapping,
  then guesses one from the bone names. The `team` driver needs only `body`.
- `sockets` names attachment points. Each has a `node`, a bone or node of the model, or none for
  the root of the figure, an `offset` in meters, a `rotation` in degrees, and its own `forward`
  and `up` vectors in the node's frame, by default `[0, 0, 1]` and `[0, 1, 0]`. The socket `gaze`
  gives the forward of the node that looks at things, and the socket `root` without a node gives
  the pivot of the figure's cosmetic offset.
- `bounds` is the conservative envelope of every pose the figure takes, `radius` and `height` in
  meters, with `top` and `clearance` when they help. Cameras, the spacing of ceremonies and the
  readability rule use it. It never touches the simulation's geometry. A worker may report
  smaller current bounds inside the envelope.
- `rootMotion` is `ignore`, the default, which keeps the root of every clip on the simulation's
  position, or `cosmetic`, which keeps its height and nothing else.
- `blend` is the time in seconds over which layers fade in and out, by default 0.2.
- `attachments` places rigid models of the package on sockets. Each names a `file`, a `socket`,
  an `offset`, a `rotation`, a `scale`, whether it casts `shadows`, and a `when` selector of the
  players that wear it. Ornaments that differ by shirt number are attachments with a `when` on
  the number. Each wearer owns the materials of its attachments, which behaviours may drive.
- `ik` names chains that reach for the ball, with the feature `ik.fabrik`. Each gives its `chain`,
  two to eight bone names from the root to the tip, an optional `socket` at its end, a `window`
  in seconds around each contact, 0.15 by default, a `weight`, the `iterations` of the solver, the
  action `roles` that reach and a `when` selector. Over the window the chain bends toward the
  drawn ball by FABRIK, which keeps every bone's length, so a foot, a ring or a tail meets the
  ball. The ball never moves to the figure.
- `layers` lists the layers of the driver `grf+layers`. Each names a `mask` of bones, every bone
  below each included, a clip `role` or a `clip`, a `weight` curve and a `rate`. GRF's joints pose
  the figure, and each layer gives its masked bones the turns of its clip, by its weight, so a
  package may keep GRF's legs under arms of its own.

A selector `when` picks players by `role`, `goalkeeper` or `outfield`, by shirt `number` and by
roster `index`, each a value or a list. Every key it gives must match.

### GRF's figure

A player whom no model of the package picks, and whose team draws GRF's own figure, wears the
package on GRF's figure. Its sockets, attachments, behaviours, material looks, shaders and lights
apply there as on a model, and a socket or a behaviour may name GRF's nodes `player`, `body`,
`middle`, `neck`, `left_shoulder`, `left_elbow`, `right_shoulder`, `right_elbow`, `left_thigh`,
`left_knee`, `left_ankle`, `right_thigh`, `right_knee` and `right_ankle`. A node's frame at rest
has y up and z toward where the player faces, and a node the figure lacks gives the root of the
figure. A chain of `ik` may join GRF's nodes too. GRF's figure plays no clip of a package, so it
keeps the driver `grf`, and the package's clip roles, its layers and the drivers `team`, `worker`
and `grf+layers` show on a model of the package or the team's own model. GRF's kit, skin, hair
and shirt numbers stay, and a material look matches GRF's materials `kit`, `skin`, `shoe` and
`sole` by name.

| Part | Model of the package or the team | GRF's figure |
|---|---|---|
| Sockets, attachments, lights | yes | yes, on GRF's nodes |
| Behaviours, material looks, shaders | yes | yes |
| Effects, sound, reflexes, worker, moments | yes | yes |
| Reach of `ik` | yes | yes, on GRF's nodes |
| Clip roles, layers, drivers `team`, `worker` and `grf+layers` | yes | no, GRF's own motion |

### Clips

`clips` names a clip of the model for each semantic role. A role takes a clip name, a list of
names, of which each player plays the one his seed picks, or a description with `clip`, `speed`,
`stride` and `rate`. The role `move` takes a space of clips by speed.

```json
"move": {"space": "speed", "clips": [
    ["Walk", 1.5], ["Jog", 4], ["Run", 6.5], ["Sprint", 8, 4.2]
]}
```

Each entry is a clip, the speed in meters per second it was made for, and optionally its stride,
the ground one cycle covers, which defaults to the speed times the clip's length.

| Group | Roles |
|---|---|
| Locomotion | `idle.calm`, `idle.alert`, `move`, `turn`, `brake` |
| Actions | `kick`, `pass.short`, `pass.long`, `pass.high`, `shot`, `header`, `volley`, `slide`, `trip`, `catch`, `parry`, `dive.left`, `dive.right`, `throwIn`, `trap`, `deflect` |
| Restarts | `restart.kickoff`, `restart.goal_kick`, `restart.free_kick`, `restart.corner`, `restart.throw_in`, `restart.penalty` |
| Ceremonies | `celebration`, `reaction.win`, `reaction.loss`, `lineup`, `salute`, `lament`, `recovery`, `podium` |

A role without a clip falls back along a chain until one has a clip. `idle.alert` falls back to
`idle.calm`, `move` to `idle.calm`, `turn` and `brake` to `move`, the passes, `shot`, `header`,
`trap` and `deflect` to `kick`, `volley` to `shot`, `parry` to `catch`, `throwIn` to
`pass.short`, each restart to its pass or shot, `reaction.win` and `podium` to `celebration`,
`salute` to `reaction.win`, `reaction.loss` to `lament` and `recovery` to `idle.calm`.

An action clip may mark the moment its contact with the ball happens. The marker sits in the
glTF file, in the `extras` of the animation, as `{"cuju": {"markers": {"contact": 0.42}}}`, in
seconds from the start of the clip. A clip without a marker makes contact 40 percent of the way
through.

The renderer's choreographies use the ceremony roles. The lineups play `lineup`, a goal's
celebration plays the scorer's chosen celebration, a team's still poses play `salute`, `lament`,
`celebration` and `reaction.win` by their kind, and the idle poses of a ceremony play
`idle.calm`.

### Behaviours

`behaviours` lists persistent behaviours, continuous motion that the renderer evaluates on every
drawing against the figure's current anchors. Each has a `type`, an optional `id`, a `when`
selector, a `weight` curve from 0 to 1 and a `seed`.

| Type | What it does | Fields |
|---|---|---|
| `spin` | turns a node about an axis, or drives the time of a clip, by an integrated phase | `node` and `axis`, or `clip` and `period`, `rate`, `phaseFrom`, `perMetre` |
| `oscillate` | a sine wave on a channel | `node`, `channel`, `amp`, `freq`, `offset` |
| `spring` | a damped spring toward a goal on a channel | `node`, `channel`, `goal`, `stiffness`, `damping`, `mass`, `limit` |
| `lookAt` | turns a node toward the ball, the camera or a player | `node`, `target`, `rate`, `slew`, `pitchLimit`, `yawLimit`, `forward`, `descendants` |
| `bank` | leans the figure, or a node, into its movement | `node`, `gain`, `limit`, `rate` |
| `follow` | moves a node toward a target, held within a distance | `node`, `target`, `smoothing`, `limit` |
| `curve` | keys of a value over a clock | `node`, `channel`, `keys`, `clock`, `loop` |
| `materialParam` | drives a numeric parameter of the player's own materials or an attachment's | `material`, `uniform`, `value`, `attachment` |
| `audioParam` | drives a parameter of the team's own sound processor | `processor`, `param`, `value` |
| `lightParam` | drives the `intensity` or `distance` of a light of the manifest | `light`, `param`, `value` |

A behaviour of a channel, `oscillate`, `spring`, `curve` or a `spin` of an axis, may name an
`attachment` in place of a `node`, and then moves or turns that attachment in the frame of its
socket. A `materialParam` reaches the uniforms of the package's own shaders by their names too.

A channel is `x`, `y` or `z`, a move in meters in the root frame of the figure, which turns with
the player, `x` to his left, `y` up and `z` forward, or `rotX`, `rotY` and `rotZ`, a turn in
radians, or `scale`, added to one. Without a `node` a channel moves the whole figure about its
pivot, the socket `root`.

A curve is a plain number, or the value of one input read through rising keys and held flat past
both ends, `{"input": "speed", "keys": [[0, 2.4], [7, 4.4]]}`, or a sum of curves,
`{"sum": [...]}`. The inputs are `speed`, the player's speed in meters per second, `accel`,
`ballDistance`, `excitement`, the renderer's measure of the match's tension from 0 to 1,
`ceremony.amount`, how much a ceremony holds the player from 0 to 1, `ballX.attack`, the ball's
position along the team's attack, `alert`, `jointSpeed:<node>` and `role:<role>`, how much a clip
role plays on the player at the moment, from 0 to 1.

A spin integrates its phase, so a change of rate changes how fast it turns and never where it
is. `phaseFrom` is `cosmetic`, which advances the phase in real time, `distance`, which advances
it with the ground the player covers, so seeks and replays turn it exactly as play did, or
`both`, which adds `perMetre` radians for each meter covered to the real time rate. A spin of a
clip drives that clip's time in seconds, wrapped by `period`.

The `seed` of a behaviour is `entity`, the default, a seed of the player in this match, `number`,
a seed of his shirt number that stays the same in every match, `index`, or a number. Oscillators
and spins start at phases their seeds give, so a team never moves as one.

A behaviour that stops, or whose worker fails, fades out over its fade time. Under reduced
motion the amplitudes of oscillators, springs and banking take the share that `reducedMotion`
gives.

### Materials

`materials` gives looks to the materials of the package's players. Each entry has a `match`, a
material name, a name ending in a star for every name that starts so, or a star for all, a
`when` selector, and values among `baseColor` and `emissive` as three integers from 0 to 255,
`roughness`, `metalness`, `opacity` and `emissiveIntensity`. A goalkeeper's palette is a look with
`"when": {"role": "goalkeeper"}`. The page gives each player his own copies of the materials it
changes. A `shader` entry names a `.glsl` file of the package, described in the section Shaders,
with its `mode`, `uniforms` of its own, numbers, two to four numbers or a seed by `entity`,
`number` or `index`, up to four `textures`, and `transparent`, `blending`, `side` and
`depthWrite`.

### Lights

`lights` names persistent lights on the sockets of the team's players, each with a `socket`, an
`offset`, a `color`, an `intensity` up to 50, a `distance`, a `decay`, a `kind` and a `when`
selector. A light of kind `pool` takes a light of the team's pool, four at high quality, two at
medium and one at low, which the page makes once when it builds the players, so turning one on
never recompiles a program. Every further light and every light of kind `local` lights the team's
own materials alone, through a chunk the page adds to them, up to eight at once. No team light
casts a shadow. A behaviour of type `lightParam` drives a light by its name.

### Post and overlays

`post` holds `layer`, a pass on the team's own players and effects for the whole match, with the
feature `post.layer`. Its `pass` is `glow`, `outline`, `pixelate`, `tint`, `chromatic`, `blur` or
`custom` with a `shader`, with a `color` and a `strength`. `overlays` names the slots a worker
draws in, with the feature `overlay.offscreen`, among `badge`, `lowerThird`, `sting`, `card` and
`lineup`.

### Effects, audio and reflexes

`effects` names effects by a `type`, each described in the section Effects. `audio` holds `cues`,
each a file or a list of files that play in turn by seed, `music`, each a list of `stems`, files
of sound, with a `bpm`, its `beats` in a bar and a `gain`, a `worklet` module and its
`processors`, each a registered `processor` name of the module, a `bus`, `parameters` and
`options`. The section Sound describes how they play.

`reflexes` bind events to actions the renderer runs at once, with no worker.

```json
{"on": "touch", "phase": "occur", "where": {"team": "self"}, "do": [
    {"audio": "strike", "at": "contact", "replay": "quiet"},
    {"effect": "spark", "attach": "ball", "claim": "ball"}
]}
```

`on` names an event of the catalog, `phase` its phase, by default `occur`, and `where` filters by
`team`, `self`, the default, `opponent` or `any`, by `player` and by `role`. Each action of `do`
is one of these.

| Action | Fields |
|---|---|
| `audio` | a cue, `at` the occurrence, the `contact` or an offset in seconds, `class` `moment`, `action` or `bed`, `bus`, `gain` from 0 to 1, `replay` |
| `effect` | an effect, `attach` to `self`, a `socket:<name>`, the `ball`, its `path` or the `world`, `claim`, `replay` |
| `clip` | a clip role played on the event's player, or on the whole team with `"on": "team"` |
| `behaviour` | a behaviour set on the event's player or the team |
| `claim` | `ball`, `goal`, `sky`, `floodlights` or `fans` |
| `music` | music of the audio, its `stems` as places in the music's list of stems from 0, every stem by default, and a `fade`, or `"stop": true` |
| `camera` | a `shot`, `closeup`, `orbit`, `low`, `behindBall` or `path`, a `duration` and a `priority` |
| `time` | a `freeze` of at most 0.3 seconds or a `slow` with its `speed` and `seconds` |
| `environment` | a moment of the `sky`, the `floodlights`, the `fog`, `lightning` or a `tifo` image |
| `overlay` | a slot to show or hide |

`replay` is `repeat`, the default, `quiet`, which plays a sound at half its gain inside a replay,
or `skip`, which leaves the action out of replays. A reflex on `winner.reveal` or `mvp.reveal`
with an audio action of class `moment` plays in place of the renderer's fanfare for its team.

### Worker, reduced motion and quality

`worker` names the worker module, described in its own section. `reducedMotion` gives
`amplitude`, the share of the amplitudes of oscillators, springs and banking under reduced
motion, by default 0.3. `quality` lists, for `low`, `medium` and `high`, the features a package
drops at that quality.

## Animation

Each player has one driver, chosen per role in the rig.

| Driver | What moves the figure |
|---|---|
| `grf` | GRF's 14 joints of the frame, retargeted onto the model as for a team's own model |
| `team` | the package's clips and behaviours, selected from the simulation's velocity, facing, GRF's kind of animation, touches and forecasts |
| `worker` | clip and pose tracks streamed from the worker, smoothed by the renderer, an experimental driver |
| `grf+layers` | GRF's joints, with the package's clips over the masked bones of its `layers` |

Where a player stands and faces always comes from the simulation. The page draws a figure in one
order. The simulation's root comes first, the player's ground point and heading. The cosmetic
offset of the behaviours follows, a lift, sway, bank, turn or scale about the pivot. The pose
comes next, GRF's joints or the package's clips, with root motion kept to the root as the rig
says, and the node channels, spins and gaze of the behaviours over it. Sockets and the
attachments on them resolve last, from the final pose, so they never trail their figure.

With the `team` driver, every weight and every clip time is a function of the simulation and
ceremony clocks, so a seek, reverse play, slow motion and a replay draw the same pose for the
same moment.

- **Locomotion.** The clips of `move` form a blend space by speed, with `idle.calm` or
  `idle.alert` at speed zero when the space has no clip of its own there. A player is alert when
  the ball is within 15 meters or the other team has it. The phase of a moving clip is the ground
  the player has covered divided by its stride, so feet, wheels and rings advance exactly with
  the ground. `turn` and `brake` mix in by the turning rate above 2.5 radians per second at low
  speed and by a deceleration above 4 meters per second squared.
- **Actions.** A forecast or an occurrence of a contact, a touch, pass, shot, header, volley,
  slide, save, catch, deflection or a restart taken, schedules the action clip of its role on the
  player who meets the ball, so that the clip's contact marker meets the estimated contact. When
  the warning is shorter than the wind-up, the wind-up plays up to twice as fast, and past that
  the clip starts later and fades in. A cancelled forecast fades its action out within 0.15
  seconds.
- **Ceremonies.** The lineups, a goal's celebration, the reactions after the match, a reflex's
  clip and a worker's pose track sit over the actions, as actions sit over locomotion.
- **Reach.** The chains of `ik` bend toward the drawn ball over the window around each contact
  of the player, after the pose and before the behaviours.
- **Behaviours.** The behaviours apply on top of every layer.

Each layer fades in and out over the rig's `blend` time, so an interrupted action never pops.
With the `grf` driver, a ceremony's clip blends over GRF's joints by its weight, and the
behaviours apply on top.

## Effects

An effect plays when a reflex or a worker starts it, by its name in `effects`, at the occurrence
of its event, at the event's `contact` or at an offset in seconds. It attaches to `self`, the
event's player, a `socket:<name>` of him, the `ball`, the ball's `path` ahead or the `world`,
where the worker's `params.position` or the event's contact point places it. While the team holds
the ball's custody an effect on the ball follows it, and otherwise it stays where the ball was. An
effect of an event ends at a new epoch, and its seed is the event's, so a replay draws the same
burst. Bursts and streams emit in forward play alone.

| Type | What it draws | Fields |
|---|---|---|
| `particles` | a burst or a stream of points | `count`, `rate`, `duration`, `life`, `speed`, `spread`, `direction`, `gravity`, `drag`, `size`, `color`, `opacity`, `blend`, `texture`, `shader` |
| `trail` | a ribbon facing the camera behind its anchor, or the path ahead | `length`, `width`, `color`, `opacity`, `blend`, `texture`, `duration`, `segments` |
| `decal` | a mark on the pitch that fades, at most 10 square meters and an opacity of 0.7 | `size`, `color`, `texture`, `opacity`, `life`, `fade`, `rotation`, `blend` |
| `light` | a light with an attack and a release, a pool light when one is free, else local | `color`, `intensity`, `distance`, `decay`, `duration`, `attack`, `release` |
| `mesh` | a model of the package for a moment, turning and fading | `file`, `scale`, `duration`, `spin`, `fade` |
| `post` | a pass on the team's layer, or on the whole view on the team's own moment | `pass`, `scope`, `color`, `strength`, `duration`, `shader` |

A pair of numbers gives a start and an end, or the least and the most of a random draw. A team
keeps at most 64 effects live, its particles within its budget and at most 64 decals, and decals
with a `life` of `half` last until half time. A full screen pass plays at high quality alone, on
the team's own goal, save, woodwork, celebration, reaction, lineup or reveal, one at a time, for
at most three seconds. Reduced motion halves the particles and leaves out full screen passes and
the passes that move the picture, `pixelate` and `chromatic`. An effect on the line from the
camera to the ball or to a player's torso fades as the section Safety describes.

A worker may also build geometry of its own with the feature `geometry.worker`. A resource
`{"op": "geometry", "id", "positions", "normals", "uvs", "colors", "indices", "attach",
"material"}` holds at most 65536 vertices within 100 meters, every value finite and every index
inside, counted in the team's triangles, draw calls and geometry memory. A resource of the same
id replaces it, and `{"op": "dispose", "id"}` ends it.

## Shaders

A shader is a `.glsl` file of the package, which the page compiles with the feature
`shader.custom`. The renderer writes the version, the precision and every uniform in front of the
file, so a file declares none. The server checks each shader on import and when it serves it,
`cuju render pack check` runs the same checks, and the page checks again before it compiles.

- Every loop is a `for` loop with constant bounds, integer literals or `const int` names of the
  file, of at most 256 iterations. `while` and `do` loops are refused.
- Loops nested inside each other run their body at most 1024 times, counted through the
  functions they call too, so a loop of 256 holds at most a loop of 4.
- A fragment fetches a texture at most 16 times, counted through the loops and the functions
  around each fetch.
- A vertex or a fragment runs at most 65536 words of code, names and numbers, each counted with
  the trip counts of the loops around it, through the functions it calls and with the words of
  the macros it names, and the file holds at most 262144 words once its macros expand.
- The one include is `#include <cuju_noise>`, with `cujuHash` and `cujuNoise`.

In the mode `chunks`, the default, a shader extends the standard material of a team's player, so
skinning, lights, fog and tone mapping stay the renderer's. The file defines any of the functions
`vec3 cujuVertex(vec3 position, vec3 normal)`, `vec4 cujuColor(vec4 color, vec2 uv)`,
`vec3 cujuEmissive(vec3 emissive, vec2 uv)`, `float cujuRoughness(float roughness, vec2 uv)` and
`float cujuMetalness(float metalness, vec2 uv)`, and the page calls each at its place. In the mode
`material` a shader is a whole material for the package's own objects, particles, worker geometry
and custom passes, a vertex section after the line `#pragma cuju vertex` and a fragment section
after `#pragma cuju fragment`.

| Uniform | Value |
|---|---|
| `uTime`, `uSim`, `uCeremony` | the cosmetic, simulation and ceremony clocks in seconds |
| `uSeed` | a number from 0 to 1 of the player's seed |
| `uTeamColor`, `uTeamColor2` | the first and second colors of the team's kit |
| `uPulse` | 1 at the team's own touch, shot, save, goal or reveal, falling after it |
| `uSpeed`, `uExcitement` | the player's speed and the match's excitement |
| `uBall`, `uResolution` | the drawn ball and the size of the view |
| `uIntensity` | the factor of the flash governor, which every bright part should follow |
| `uSceneColor` | the frame drawn so far, at high quality with `shader.sceneColor`, black otherwise |
| `uLayer` | the team's layer, in a custom pass |

The test package blinks its players this way, each half of a figure by its own seed. Each
distinct file and mode is one program of the team's shader budget, and a shader that fails to
compile draws the standard material and the page names it in a notice.

## Sound

Each team plays on buses of its own, an effects bus and a music bus, which the renderer governs.
A bus runs through a loudness governor, which holds its short-term loudness at most 5 LU above the
programme target, at most −18 LUFS, its momentary loudness at most −14 LUFS and its onsets within
the startle guard, then through a true peak limiter at −6 dBTP and a clipper of the browser's own,
which no package code reaches. A bus whose governor lowers it by more than 6 dB for three seconds
within a minute loses a further 6 dB for the session, and the page says so. The effects bus feeds
the viewer's Action sounds level, the music bus the Team music level. While a package plays sound
the master passes a true peak limiter at −1 dBTP after the renderer's compressor.

Cues are measured as they decode and scaled down so that each alone stays under the bus's
ceilings and at most at the level of a team's own sounds. A cue plays `at` the contact of its
event, so the strike lands on the contact, and from a socket or player when it names an `attach`.
A team holds its budget of voices, a new one ending the oldest, and a seek ends them all. While
one team plays a sound of class `moment`, the other team's beds lose 6 dB and its actions 3 dB.

Music stems loop on the team's musical clock, set by `bpm` and `beats`, and a `music` command or
action crossfades the stems it names, at once or on the next beat or bar of `at.quantize`.
The command or action names its stems by their places in the list of the music from 0, so
`{"music": "anthem", "stems": [0, 1], "fade": 1}` brings in the first two stems of `anthem`, and
one without `stems` plays them all. Stems are scaled to a bed's loudness, under the renderer's
crowd, and sink under the crowd's swell after a goal.

With the feature `audio.worklet`, the module `worklet` loads into an audio context of the team's
own, at the sample rate of the page's context, whose AudioWorklet scope holds the team's module
alone, apart from the renderer's meters, governors and limiters. Each of `processors` becomes a
node there within the team's worklet budget, and its sound streams into the effects bus or the
music bus of the team, through its governor and limiter like every other sound of the team. The
page sends each processor the team's own events on its port. `audioParam` behaviours and worker
commands `{"op": "param", "node", "param", "value"}` drive its parameters. A processor that fails,
an audio thread that stalls or a bus that runs away stops the team's processors, and its samples
play on. A browser that makes no second audio context plays the samples alone.

## Moments

Camera, time and environment suggestions count only for the team's own events.

- **Camera.** With `camera.suggest`, a suggestion leans the camera toward its subject and
  tightens the framing, in the broadcast camera for at most 1.5 seconds, or in the team's own
  celebration for at most four. The viewer's own camera, the director's other shots and the
  transport in use refuse it.
- **Time.** With `time.suggest`, a freeze of at most 0.3 seconds or a slow motion of no less than
  a quarter of the speed for at most 1.5 seconds plays at the event or its contact, once per team
  in 30 seconds, at plain forward play, and on a live stream only with a second of buffer left.
- **Environment.** A moment tints the sky, the floodlights or the fog with `environment.sky`,
  strikes one bolt of lightning on the goal the team attacks or the ball with
  `environment.lightning`, or raises a `tifo` image of the package in the stand behind the goal
  the team defends with `fans.tifo`. A moment lasts at most six seconds, one at a time, 20
  seconds apart for a team, and fades in and out over 0.3 seconds through the flash governor.
- **Overlays.** With `overlay.offscreen`, the worker's Hello holds an OffscreenCanvas in
  `canvases` for each slot of `overlays`. The worker draws in it with the 2D context and answers
  `{"slot", "op": "draw"}`, and the page shows what it drew in the slot. The badge sits under the
  score on the team's side, the lower third shows on the team's goal, the sting on its goal or
  win, the card on its reveals and the lineup slot in the lineups. No slot covers the score, the
  clock or the banners.

Reduced motion refuses camera and time suggestions, and two settings in the page's storage,
`cuju.teamCamera` and `cuju.teamTime` set to false, refuse them for good.

## The ball and the sides

With `bend.ball` the drawn path of the ball bends through the estimated contact of each touch, of
the section Look-ahead, so the ball leaves the foot at the contact. The page draws only, the
frames stay as they are. Setting `cuju.presentation.settings.bendBall` to true bends it for every
match.

A side draws the package of the team that plays it, or the package of a registered team the
viewer chose for it, which serves matches whose teams are no registered teams, such as the live
batches of a training run. The settings panel holds the choice of each side, the route
`/api/presentation/sides` answers it and takes `{"left": id, "right": null}`, and
`cuju render pack sides --left ID --right none` sets it from the command line, which prints the
choice of each side as a line, or as JSON with `--json`.

## Clocks

Every frame carries four clocks.

| Clock | Advances | On a pause | With speed | In reverse | On a seek | Hidden page | Capture |
|---|---|---|---|---|---|---|---|
| `sim`, with `step` and `fraction` | with playback | stops | scaled | runs back | jumps | stops | stepped |
| `ceremony` | while a lineup, celebration, replay or show after the match plays | holds while the viewer pauses the show | unscaled | not used | starts again | stops | stepped |
| `cosmetic` | always, in real time | runs | unscaled | runs forward | runs | stops | stepped |
| `audio` | with the sound device | runs | unscaled | not used | runs | suspends | not captured |

Each step of the ceremony and cosmetic clocks is held to at most 0.05 seconds, so a tab that comes
back from the background resumes without a jump. While the page is captured with `?capture`, the
capture's fixed step drives them, so a capture draws the same frames every time.

## Identity, seeds and epochs

Positions in frames use the pitch frame of the recording format, meters, with the center spot at
the origin and z up. Team 0 attacks positive x and team 1 negative x for the whole match, and each
Frame carries `attack` for both. Data of a model, its sockets, bounds and clips, stays in glTF's
own frame, y up.

A player's entity is `p` followed by his index in the header's list of players, `p7` for example,
stable for the life of the match. Each player carries his `roster`, name, number, goalkeeper and
celebration, from the team's `team.json`.

A seed is a hash of the match, the side, the entity and a key that holds no epoch, so every
viewer of the same recording gets the same seeds, and seeks and replays reuse them.

An epoch starts at every discontinuity, a seek, a jump past what play covers in one drawing, a
cut, entering or leaving reverse, a new source, the start or end of a replay and a restart of a
package's worker. The Frame names the reason in `reset`, one of `seek`, `cut`, `reverse`,
`source`, `resume`, `replay`, `restart` and `package`, with the times before and after. Forecasts
of the old epoch are cancelled, a worker's replies to the old epoch are dropped, and its
transient effects end. Tracks and persistent behaviours carry over, phases included, and the
estimates read from the simulation, velocities, gaze, springs and banking, start again from the
frame on screen.

## Events

The renderer sends events to reflexes and workers, each with this shape.

```ts
Event {
  id: string            // stable across epochs and replays
  kind: string          // for example "touch", "shot", "goal", "celebration.begin"
  phase: "forecast" | "occur" | "resolve" | "cancel"
  revision: number      // grows when an inferred field is refined
  step: number; t: number   // the simulation time of the event, the contact for touches
  lead: number              // seconds of simulation time until t
  team?: 0 | 1; player?: number; subjects?: number[]
  provenance: "frame" | "inferred" | "presentation"
  inference?: string        // the rule and its version, such as "shot/1"
  replay?: {of, angle, speed}
  data: {...}
}
```

Events read from the frames are authoritative, provenance `frame`. They are `touch`,
`action.begin`, `action.end`, `possession`, `goal`, `restart.begin`, `restart.taken`, `foul`,
`card`, `sentOff`, `onPitch`, `offside`, `control`, `episode.begin`, `episode.end`, `halftime` and
`fulltime`. A touch carries its kind, kick, intended or accidental, the ball's velocity before
and after, and the estimated contact time and point. `action.begin` carries `expectedContact`,
the forecast contact time when the frames reach it, marked certain, else the usual lag of that
kind of animation, measured on the shipped samples.

Inferred events, provenance `inferred`, follow versioned rules. They are `pass`, `shot`,
`header`, `volley`, `slide`, `save`, `catch`, `deflection`, `block`, `woodwork`, `nearMiss`,
`sprint.begin`, `sprint.end`, `dribble.begin` and `dribble.end`, and the enriched `goal` with its
scorer, assist and kind of finish. A pass or shot resolves later, phase `resolve`, with its
outcome.

The show's events, provenance `presentation`, are `lineup.begin`, `lineup.end`,
`celebration.begin`, `celebration.end`, `reaction.begin`, `reaction.end`, `replay.begin`,
`replay.end`, `mvp.reveal`, `winner.reveal`, `appearance` and `entity.remove`. The transport
sends `pause`, `play`, `speed`, `reverse` and `reducedMotion`.

### Look-ahead

A recording holds every frame and a live stream plays three seconds behind its newest step, so
the renderer announces events before they happen, phase `forecast`, with their `lead`.

| Source | Contact forecasts | Outcome forecasts |
|---|---|---|
| Recording | 2.5 seconds ahead | 0.5 seconds ahead |
| Live stream | the seconds buffered less 0.2, at most 2.5 | 0.5 seconds ahead |
| A game a person plays | none, `action.begin` carries `expectedContact` | none |

Contacts are touches, passes, shots, headers, volleys, slides, saves, catches, deflections and
restarts taken. Outcomes, goals, woodwork, near misses, cards and every resolve, wait until half a
second before they happen, so a package never tells the viewer a goal is coming. A viewer setting
of full look-ahead, `cuju.fullLookahead` in the page's storage, lifts that for showreels.

A forecast is cancelled, phase `cancel`, only at a new epoch, a cut of a live stream, a new
source, entering reverse or a speed above 2.5. An inferred classification may be refined with a
higher `revision`, so a package treats the fields of a forecast other than `t` and `player` as
provisional.

Play forward at a speed up to 2.5 sends each event once. After a seek the renderer sends the
events whose window holds the new time, with a negative lead, so a trail appears in mid flight
just as play showed it. A replay sends its events again with `replay` set and the same `id`.

## Tracks and ball custody

A track is content bound to a span of one clock, a clip, a curve, a pose or an effect, with a
seed and a replay policy. A track on the simulation clock is a pure function of simulation time,
so a seek back, reverse play and a replay show the same thing. The renderer keeps tracks by id in
a ledger across epochs, so it restores them itself after a seek.

The ball is shared, and a team borrows it on its own touches. A claim of `ball` on a touch of the
team grants custody when the team wins that step's touches, the stronger kind of touch first,
then the stronger action, a shot over a pass over the rest, with an exact tie granting no one.
Custody ends at the next touch by anyone, a restart, a new epoch or six seconds of simulation
time. While a team holds the ball it may attach layers to it, a trail, a glow, a light or a
sound, and the ball itself always draws on top. Every Frame names the holder in `ball.custody`.

## The worker

A worker is one self-contained ES module, without imports, that exports `frame` and optionally
`init` and `dispose`.

```js
let hello = null;

export function init(h) {
    hello = h;
}

export function frame(f) {
    const out = { behaviours: [], bounds: [], log: [] };
    if (f.reset) {
        out.behaviours.push({
            op: 'set', id: 'pulse',
            behaviour: { type: 'oscillate', channel: 'scale', amp: 0.01, freq: 0.5 },
        });
    }
    for (const p of f.players) {
        if (p.team === hello.team && p.visible) {
            out.bounds.push({ entity: p.entity, current: { radius: 0.5, height: 2.0 } });
        }
    }
    return out;
}
```

The page starts each team's worker in a sandbox of its own, an iframe of the route
`/sandbox/presentation` with `sandbox="allow-scripts"`, which gives it an opaque origin with no
cookies, no storage and no access to the page. The route is the one page of the server that its own
page may frame, together with the notebooks that may frame the viewer, and its policy allows only
its bootstrap, blob scripts and WebAssembly, and no connection at all. The page hands the module to
the sandbox as text with a message port, the sandbox turns it into a blob, starts a worker that
imports it, and from then on the page and the worker talk over the port alone. Before the module
runs, the worker tries the network and the storage of its origin, and the page refuses a worker that
reaches either.

The route's own policy carries the same sandbox, so the route opened as a whole window also has an
opaque origin, and every page of the server keeps its window apart from a window of another site
that opened it. The bootstrap starts a worker only inside a frame, in an opaque origin, for a
message of the page right above it from the server's own origin.

A worker draws with the 2D context alone. Before the module loads, every OffscreenCanvas of the
worker, the canvases of its overlay slots among them, offers `getContext('2d')` and answers
`null` for every other context, a `getContext` that the module can neither replace nor redefine.
`navigator.gpu` is gone and the worker starts no workers of its own, so a package reaches the GPU
only through the shaders that the renderer checks and compiles, with the limits of the section
Shaders. Each slot's canvas has a fixed size, 96 by 96 pixels for `badge`, 360 by 90 for
`lowerThird`, 320 by 180 for `sting`, 200 by 200 for `card` and 384 by 270 for `lineup`, and the
page shows a drawing of that size alone. The wrapper that loads the module runs in a closure of
its own and keeps its port to the page out of the module's reach, and the module draws in its
slots through the canvases that `init` receives.

`init` receives the Hello once.

```ts
Hello { contract, features, lacking, limits, quality, reducedMotion, instanceId, team, attack,
        roster[], header: {format, scenario, sps, provenance}, seedBase }
```

`frame` receives a Frame and returns a Response, or a promise of one. The page sends a Frame once
the previous one is answered, and the events of the drawings in between accumulate in the next
Frame, never dropped.

```ts
Frame {
  instanceId, epoch, frameId, reset?: {reason, fromT, toT},
  clocks: {sim, step, fraction, ceremony, cosmetic, audio},
  playback: {playing, direction, speed, live, ahead, context},
  quality, reducedMotion, audible,
  players: [{entity, player, team, own, roster, onPitch, visible, hidden, root: [x, y, z],
             facing, velocity: [vx, vy], speed, distance, action, touch, owner, driver, mode,
             ceremonyRole, bounds}],
  ball: {pos, rot, velocity, owner, custody},
  game: {mode, score, clockMs, ownedTeam, attack, excitement},
  events: Event[],
  camera: {pos, target, fov, mode}
}
```

`root` is the drawn position of the player in the pitch frame, `facing` his heading in radians
from positive x toward positive y, `velocity` the simulation's motion in meters per step,
`speed` in meters per second and `distance` the ground he has covered since the match began.
`context` is `play`, `replay`, `celebration`, `lineup`, `post` or `transition`.

```ts
Response {
  behaviours?: [{op: "set" | "update" | "stop", id, entity?, behaviour}],
  tracks?: [{id, entity | "world", event?, from, to, clock, content, seed, replay}],
  effects?: [{op: "spawn" | "update" | "stop", id, kind, attach, at, params}],
  claims?: [{target, event}],
  audio?: [{op: "play" | "param" | "stop" | "music", id, cue, at, class, bus, gain, rate}],
  camera?: {event, shot, subject, duration, priority},
  time?: {event, at, freeze, slow},
  overlays?: [{slot, op}],
  resources?: [{op, id, file}],
  bounds?: [{entity, current: {radius, height}}],
  log?: string[]
}
```

The lines of `log` add up across replies, the newest 50 kept, show in the preview panel and in
the browser console, and `cuju.presentation.status()` lists them under the package's `log`.

The page fills `instanceId`, `epoch` and `sourceFrameId` of a reply itself. It drops a reply of
an older epoch, checks every command, holds it to its ranges and to the team's own entities,
and keeps at most 64 commands of each kind. A behaviour or track without an entity applies to
every player of the team. A track's content is `{"kind": "clip", "clip": "Name"}` or
`{"kind": "pose", "clip": "Name", "time": 0.4, "weight": 1}` for the `worker` driver.
Gains only lower a sound, a camera shot lasts at most four seconds, a freeze at most 0.3 seconds
and a slow motion goes no slower than a quarter of the speed for at most 1.5 seconds. Current
bounds lie inside the rig's envelope.

A reply later than 50 milliseconds is used and counted late. A worker that throws, answers with more
than 512 KB, refuses its sandbox or stays silent for five seconds of drawing and three drawings is
ended. So is a worker whose reply holds anything but plain data, objects, arrays, typed arrays,
strings, numbers and booleans, more than eight overlays, or a bitmap anywhere but in an overlay at
the size of its slot. Each drawing adds at most a tenth of a second to the silence, so a page that draws slowly, or
stalls while it loads models and compiles programs, waits for the reply its own slowness held back,
and a worker has ten seconds of drawing for its first answer. The page then fades what it drove, its
behaviours, tracks and bounds, back to the manifest's own look over half a second, starts a new
epoch and starts the worker once more. A second failure leaves the team with its manifest alone, its
level reads `manifest` in `cuju.presentation.status()`, and the page names the failure in a notice.

## Budgets

Each team has budgets by quality, provisional numbers that real packages will calibrate.

| Resource, per team | High | Medium | Low |
|---|---|---|---|
| Main thread time, mean of each drawing over 2 s | 0.75 ms | 0.75 ms | 0.5 ms |
| GPU time | 2.5 ms | 2.0 ms | 1.0 ms |
| Draw calls | 150 | 100 | 60 |
| Triangles | 400 000 | 200 000 | 80 000 |
| Texture memory | 128 MB | 64 MB | 32 MB |
| Particles | 20 000 | 8 000 | 2 000 |
| Pool lights | 4 | 2 | 1 |
| Shader programs | 16 | 16 | 8 |
| Sample voices | 32 | 24 | 16 |
| Worklet nodes | 4 | 4 | 2 |
| Decoded audio | 64 MB | 64 MB | 32 MB |
| Worker geometry | 32 MB | 16 MB | 8 MB |
| Live effects and decals | 64 | 64 | 32 |
| Local lights | 16 | 16 | 8 |
| Full screen passes | 1, on its moments | none | none |

Attachments count against draw calls, triangles and texture memory as they load, and one past a
budget stays off with a warning. A team whose main thread time runs over its budget for three
seconds steps one rung down the degrade ladder, fewer particles, no passes, local lights,
standard materials, no worker, the manifest alone and the stock look, each step crossfaded over
half a second. A team that runs under 60 percent of its budget for ten seconds climbs back one
rung, the worker at rest starting again, and each fall after a climb doubles that wait. After a
third such fall the team stays on its rung, so a package that truly overruns ends at the stock
look.

The main thread time is the package's own work on each drawing, its behaviours, clips, reach,
attachments, effects, worker messages and geometry, and leaves out the page's own pose of the
figure, which the page draws without a package too. The meter reads the mean of each drawing over
the last two seconds, which a browser's clock of a tenth of a millisecond reads as well as a fine
one. It starts once the package settled, half a second after its worker's first answer, or a
second after the players are built for a package without a worker, and leaves out a drawing that
takes longer than a quarter of a second, a stall of the whole page. The preview panel and
`cuju.presentation.status()` show the mean as `mainMs`, beside the 95th percentile as `p95`.

## Safety

The renderer owns the safety rules, versioned and the same for every package. Loudness follows
ITU-R BS.1770 and EBU Tech 3341 meters, with EBU R 128 targets of −23 LUFS integrated and
−1 dBTP true peak on the master, and EBU R 128 s1 for short team cues, whose short-term loudness
stays at most 5 LU above the target. The principles of ITU-T H.870 apply as relative safeguards, a
moderate default volume, no sudden jumps in loudness, mute always at hand and levels that only
lower sound, since a browser cannot know the sound pressure at the ear. Flashes follow WCAG 2.3.1
and ITU-R BT.1702, at most three general or red flashes in any second over 25 percent of a ten
degree field of view, and reduced motion follows WCAG 2.3.3. The section Sound describes how the
team buses meet the loudness numbers.

Every intensity of a team, its lights, its passes, its moments of the sky, the floodlights and
lightning, passes through an envelope of the flash governor, which lets at most three rises
through in any second and counts saturated red apart. As a backstop, while any team effect plays,
the page reads a 64 by 36 copy of every frame and counts general and red flashes over any window
a third of the view wide and high, an estimate of a ten degree field. On the third flash in a
second every team's effects dim to a quarter for a second and return over 0.3 seconds.

An overlay slot sits beside the picture that the backstop reads, so each slot counts the flashes
of what it shows on a grid of 16 by 16 cells over the slot as one field, each cell the mean light
of the pixels in it and a hidden slot counting as black. On the third flash in a second the slot
hides for three seconds, and the page names it in the list of refused suggestions. A drawing the
page cannot read stays hidden.

An effect that sits on the line from the camera to the ball or to a player's torso fades to a
quarter of its opacity within 0.15 seconds and recovers in 0.3 seconds.

## Developer mode

Developer mode serves a team's package from a folder of the author's own, read afresh on every
request, so each change shows when the team is drawn again. It runs the worker on the page itself
with direct access, its `init` receiving the page and three.js as `developer`, and the page shows
a notice that the team runs from a local folder. The page imports the worker by its address, so
the server sends every module of the folder as JavaScript. It is off unless the file
`developer.json` in the renderer's home names the folder.

```json
{"presentation": {"t-20261110-101500-ab12": "/home/me/my-team/cuju-team"}}
```

Each key is the identifier of a registered team, and each folder an absolute path to a
`cuju-team` folder holding `presentation/presentation.json`. An imported archive never turns
developer mode on, only the home's own file does. A second `cuju render pack preview` of the same
folder updates the team of the first and keeps its identifier, so a `developer.json` that names it
goes on working.

## See also

- [Rendering](rendering.md), the renderer, its teams, custom models and celebration clips
- [Recording format](rendering.md#recording-format), the frames that events are read from
