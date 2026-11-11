# Changelog

All notable changes to cuju-render are documented in this file. Through cuju 0.2.0 the
renderer shipped inside cuju, and the changes up to then are in
[cuju's changelog](https://github.com/AndreKoraleski/cuju/blob/main/CHANGELOG.md).

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-11-11

### Added

- `cuju render app`, the page in a window of its own in any browser. It opens the system's web
    view through pywebview, the new extra `cuju-render[app]`, else Edge, Chrome, Chromium or Brave
    in app mode with a profile of its own, else the default browser with a note, and `--route`
    and `--browser` choose. A server that it starts ends with the window.
    `cuju render app --install` adds a launcher with the cuju icon, a Start menu and desktop
    shortcut on Windows, an entry of the applications menu on Linux and `cuju.app` in
    `~/Applications` on macOS, and `--uninstall` removes exactly what it made.
- An offer to install the page as an app comes to the person. Once Chrome or Edge is ready to
    install the page, Home shows a small card from the second visit on, whose Install opens the
    browser's question and whose Not now keeps it away for good in that browser. The card hides
    in an installed app. Help names Safari's File, then Add to Dock, in Safari, and
    `cuju render app --install` in every browser.
- Export video on the Watch page draws and encodes the video in the browser itself, with
    WebCodecs, so a person who installed `cuju[render]` alone exports without Chrome or ffmpeg.
    The browser steps the recording one frame at a time in a frame of its own, so a slow computer
    still draws every frame, and writes MP4 with H.264, or WebM with VP9 or VP8 where H.264 is
    missing, with the same sizes, safe areas, frame rates, qualities, cameras and overlays as the
    server's export, a bar of progress, Cancel export and Download video. A browser without a
    video encoder uses the server's export when the server has Chrome and ffmpeg, and otherwise
    hears in two lines what would make export work. The diagnostic report names where Export
    video makes its videos.
- `cuju render video` and the server's export need only a Chrome, Edge or Chromium. The headless
    browser runs the same export of the page and hands the file back in pieces, MP4 with H.264
    where it encodes H.264 and WebM with VP9 or VP8 otherwise, and `--format` asks for `mp4`,
    `webm` or `auto`. ffmpeg stays optional and encodes an MP4 only where the browser has no H.264.
    The page that draws an export may sit in a frame of its own server, as the clean feed's page
    does.
- `cuju render team sound ID KIND FILE` gives a team the sound of a moment from the command line,
    checked as the page's upload is, `--remove` takes it away and a bare `team sound ID` lists the
    sounds. The HTTP table of the docs lists the routes of a team's model, images, sounds and
    clips.
- Groups of challenge runs. The recordings of one run show as one row of the Recordings page that
    names the challenge, the competitor and the result and opens to the attempts by mouse, keyboard
    and screen reader, and Delete moves the whole group to the Trash in one step. Each summary of
    the library carries its `group`, which `GET /api/matches?group=`, `cuju render recordings
    --group` and `cuju.render.recordings` list, and `DELETE /api/groups/ID`,
    `cuju render recordings --delete-group` and `cuju.render.delete_group` move a whole group.
- Keep attempts as recordings, a setting of the Challenges section, with `--no-recordings` of
    `cuju render challenge` and `keep_recordings=False` of `cuju.render.challenge`, for runs that
    score, rank and earn as before and add nothing to the library.
- `cuju render team show` and `cuju render team set`, which change a team's name, format and
    control from the command line, the control options `--players`, `--assignment`,
    `--selection`, `--goalkeeper` and `--action-set` of `team add` and `team set`, and `--json`
    for `team list`, `team show`, `team add`, `team set` and `sample`.
- The routes of the registry, the requested matches and the games of the server, documented with
    their bodies for scripts and agents.
- `--json` for `cuju render play` and for `cuju render challenge`, its catalog and a run.
- Play offers Low graphics quality once a visit when its picture draws fewer than 12 frames a
    second, as Watch offers the 2D view.
- Languages of the page. Every text the page shows comes from a language file, one JSON object of
    messages with placeholders and plural forms by language, and the page ships English and
    Brazilian Portuguese. The Language list of the settings panel follows the browser by default,
    a file dropped into the folder `languages` or imported on the panel adds a language, the
    address takes `lang`, and a message a language lacks shows in English.
- `cuju render language new`, `check`, `list`, `add` and `remove`, with JSON for agents, and
    `/api/languages`, which lists, serves, imports and removes languages.
- The error answers of the server and the failed requests, games, videos, challenge runs and
    tournament matches carry the identifier and values of their message beside the English text, so
    the page shows them in its language.
- Search of moments across the library. The server indexes the goals, shots, saves, passes,
    tackles, cards, fouls, offsides, set pieces and changes of possession of every recording, by
    the rules of the event catalog, and keeps the index up to date as recordings arrive and go. A
    panel on the Recordings page, the command palette, `GET /api/search`, `cuju render search` and
    `cuju.render.search` take a small query language such as `goal team:Greens after:60`, and a
    result opens Watch a few seconds before its moment.
- Captions of the events on Watch and Play, short plain lines timed to the events in a live region
    for screen readers, with a setting for on, off and size, saved as WebVTT from Watch, with
    `cuju render captions` and from `GET /api/matches/ID/captions.vtt`. Every caption is a message
    of the language files.
- Team presentation contract 1.1. Packages draw particles, trails, decals, mesh effects, pool and
    local team lights and worker geometry, compile their own shaders in a chunks or a material
    mode with renderer uniforms, add passes on their own layer and, at high quality on their own
    moments, on the whole view, play music stems and AudioWorklet processors on team buses with a
    BS.1770 loudness governor and true peak limiters, suggest camera shots, freezes and slow
    motion, tint the sky, strike lightning, raise a tifo, draw in overlay slots, reach for the ball
    with FABRIK chains, lay clips over GRF's joints and bend the drawn ball through each contact.
    A flash governor holds every team intensity to three rises a second and dims the teams on a
    third measured flash, by WCAG 2.3.1. Packages of contract 1.0 play as they are.
- `cuju render pack check`, `pack new`, `pack preview` and `pack sides`, the author tools of
    presentation packages, with JSON for agents, a preview panel on the page with event buttons
    and safety meters, and `/api/presentation/sides`, the team whose presentation each side draws.
- A Team music level in the settings panel, 0.8 by default.
- Annotations. `Recorder.annotate` and `LiveSource.annotate` attach named numbers, a text, the
    chosen action and the likely actions to a step, for a player or the whole match. Recordings
    of version 2 keep them in a section, live sources stream them to viewers that ask, and filters
    read them. The Watch page shows them under the players and as lines on the timeline, with an
    Annotations panel to pick what shows, and stays as before for a recording without them.
- Recorder filters. `Recorder(keep='goals')`, `every=N`, `min_reward=x` or a function of the
    episode's summary, with its score, goals, length and rewards, decide at the end of each episode
    whether to save it, and the frames of a dropped episode are discarded unwritten.
- Team presentation packages, contract 1.0. A team's `cuju-team/presentation` folder brings
    models by role and shirt number, clips by semantic role with contact markers, sockets,
    attachments, presentation bounds, persistent behaviours, material looks, reflexes and a
    worker module that runs in a sandboxed opaque origin with no network. The team driver draws
    players from the package's clips, with locomotion matched to the distance covered and actions
    that meet the estimated contact. The renderer gives packages four clocks, stable identities
    and epochs, an event catalog of frame, inferred and presentation events with look-ahead, ball
    custody, a track ledger, per team budgets with a degrade ladder and developer mode for a
    trusted local folder. The server checks every package on import, export and request.
- Recording provenance with the version of cuju and the source, the resolved seed and
    configuration of requested matches and human games, and the environment index of recorders
    and live sources. Library summaries carry the same, including for copied recordings.
- Persistent history of requested matches with resolved seeds and times, and Retry and Repeat on
    the Matches page. A restart of the server marks waiting and playing requests as interrupted.
- Favorites, tags and notes on recordings, source and result filters, storage totals and the
    provenance of a recording in Recordings, and a Trash view with Restore and permanent deletion.
    Deleting a recording now moves it to the Trash.
- Duplicate saved team in the team editor, which copies a submission team with its files,
    controls and presentation settings.
- Celebration clips. A team uploads binary glTF animations on a skinned skeleton, up to 10 MB
    each and 40 MB in all, and picks them as goal celebrations for the team and for each player.
    The page retargets each animation onto GRF's player and any model by the joint mapping of
    custom models, editable and guessed for rigs such as Mixamo's, keeps the scorer near the spot
    and on the pitch, and previews it in the editor. The server checks every clip, and clips
    travel in team export and import.
- Live streams that reconnect. The page numbers the frames of a live source, reconnects a dropped
    connection up to three times in each outage, drops repeated frames, shows lost frames as a
    cut with their count, and tells the end of a source from a lost connection.
- Live environment switching. `LiveSource.select_environment` and an Environment field on the
    Watch page show another environment of the batch from its next step on, leaving every output
    of the batch unchanged, and every page that watches the source follows it.
- Registered teams in games on the Play page, as the opponents or, with dynamic assignment, as a
    person's teammates. A team answers each step on a thread of its own within nine tenths of the
    step, and the built in AI plays its players for a step it misses. The first call has an
    allowance of its own, and a team that fails or stops answering ends the game, which keeps its
    recording. The provenance of a played game names the team of each side.
- Input settings on the Play page, kept in the browser. Keys of play can be changed, apart from
    H, M and F and without duplicates, the dead zone of the controller stick can be set, and each
    side of a game for two people can be given its own device. A tester shows what each device
    holds, and the status line of a game shows the engine's action for each person, sampled.
- Player labels on the Watch page with the number and name of each player in sight, and a setting
    that follows a player with the Follow player camera after a click on that player.
- Crowd, ambience and action sounds levels in the settings, which only lower their part of the
    sound beneath the volume, and a Motion setting that follows the system's preference for
    reduced motion or sets it for the page. Reduced motion replaces camera glides with cuts,
    hides the ball trail and stills the turning of the editor preview.
- `cuju render demo`, which starts the server or uses a running one, opens the page and streams a
    live match between the built in AIs from a process of its own, five or eleven a side, until
    Ctrl+C ends it cleanly.
- A command palette on every page, opened with Ctrl K or the Commands button of the top bar,
    which finds pages, recordings, live sources, games by scenario, settings, View menu choices,
    players to follow and help topics by fuzzy search, works by keyboard alone and returns focus
    to where it was.
- Presets at the top of the settings panel. Quick look turns off the lineups, celebrations,
    replays, decision replays, restart transitions and post-match show, Full broadcast turns them
    on, and Custom brings back the person's own mix.
- A friendlier first run. Empty pages name the next step, such as the demo and a sample match on
    Watch and the samples and the recorder on Recordings, each page shows a short tip until it is
    dismissed, and the main controls show a line of help on focus and hover.
- Touch controls on Play, an on-screen stick and the short pass, long pass, high pass, shot,
    sprint and dribble buttons of GRF's layout for several fingers at once, which press the same
    inputs as the keyboard and controllers, with a setting to show or hide them. On Watch, the
    controls grow to finger size on touch screens and a swipe along the timeline moves through the
    match.
- A 2D view of Watch, a top-down drawing on a 2D canvas without WebGL from the same timeline, with
    players in team colors and numbers, the ball with a cue of its height, and the scoreboard. The
    View menu and a setting turn it on, a browser without WebGL opens in it, and a very slow 3D
    picture offers it once. Replays and shows that need the 3D view are skipped while it draws.
- A grid of environments for live sources. The Watch page shows up to 64 environments of the batch
    as small 2D views with their scores, clocks and indices, and a click or Enter on a tile shows
    that environment. The source reads states for it only while it is watched, at most 4 in a
    step, 10 a second and a twentieth of the wall time, leaving every output of the batch
    unchanged, through `GET /api/live/<id>/grid` with the source's host and origin checks.
- Tournaments in the renderer, of registered teams, the built in AI at chosen abilities and people,
    on a Tournaments page with a setup wizard, an advanced editor of every stage, brackets, tables
    with their tiebreaks explained, fixtures with recordings, live progress and a trophy ceremony,
    and as `cuju render tournament new`, `check`, `list`, `show`, `run`, `cancel`, `delete`,
    `presets`, `ratings`, `forfeit`, also named `award`, and `resume`, each with `--json`, with
    `--rounds` and a documented configuration file, and routes of the server. A
    chain of up to eight stages of knockout with byes or a play-in round, double elimination,
    leagues of any cycles, groups with pots and best places, the Swiss system, ladder,
    king of the hill and gauntlet takes 2 to 256 entrants, with the scenario, match length,
    ability, legs, settling of drawn ties, points, tiebreakers, seeding, ratings, advancing
    entrants and matches at once set for each stage, and fourteen presets that ship. The same
    configuration and seed give the same draw and match seeds, and a tournament resumes after a
    restart. People play their matches on the Play page. Requested matches and games take a match
    length and keep the tournament match in their provenance.
- A registered team may enter a tournament more than once, each entrant under a name of its own,
    unique within the tournament without regard to case or spaces. The Entrants step proposes a
    free name such as Rex 2 for a team added again, marks a name that repeats another and lists
    them in Review, and `cuju render tournament` takes `--as NAME` after an entrant. A typed name
    that repeats another is refused in English and Portuguese. Two entrants of one team meet as a
    match of the team against itself, the right side in its away kit with its goalkeeper apart,
    share the team's rating, which their own match leaves as it is, and a failing policy is named
    by the entrant whose side failed. Tournament files of before load and resume as they did.
- `cuju.render.show`, which opens the viewer on a batch, a recording file, an identifier or a URL
    from a script, a terminal or a notebook. It reuses the server of the renderer's folder, which
    `server.json` names, or starts one in the background that ends with the process unless asked
    to stay. `cuju.render.record`, `Recorder.close` and `LiveSource` serve as context managers that
    detach, and save a recorder's episode, at the end of a `with` block.
- The inline viewer in notebooks. In Jupyter and VS Code `show` displays the page in a frame with
    a link to open it full size, and in Google Colab it serves the page through Colab's port proxy.
    The server lets only a page with the key of its server sit in a frame, and only in a notebook.
- `cuju render open` for a recording file, an identifier or a URL, which starts the server when
    none runs, and `cuju render serve --remote`, which prints the SSH tunnel command for the
    machine and port and reports when a browser first reaches the page. A bare `cuju render`
    serves the page and opens Home, and the commands name the cause and a remedy for a port in
    use, a missing or foreign file and a folder that cannot be used.
- Video export. `cuju render video` draws a range of a recording, given in seconds, minutes and
    seconds or around a goal, on the page in a headless Chrome or Chromium frame by frame and
    encodes a silent MP4 with ffmpeg, with options for the camera, size, frame rate, quality,
    scoreboard, arena and time of day, a maximum length and size, progress and Ctrl+C. Export
    video on the Watch page asks the server for the same export and offers the file. Both
    programs are optional and found on the path.
- A browser job in continuous integration, which runs the page check in the runner's headless
    Chrome against the mock server with sound muted and exports two seconds of a sample match.
- Surprise me in the team editor and in the form that adds a team, a seeded generator of a team's
    name, badge, kit, goalkeeper kit, numbers, fans and roster names in seven kit styles, with
    readable numbers and kits clear of the built in AI and common kits, and `cuju.surprise` for
    scripts.
- Photo mode on the Watch page, opened with O or from the View menu. It holds the moment and
    frames it with a free camera, depth of field that follows the center of the picture or a
    set distance, seven film looks, vignette, grain, roll, field of view and frame guides, and
    saves a PNG at the window's size or a chosen one. It works by keyboard and controller, and
    scripts use it through `window.cuju.photo`.
- Challenges, a drill for every academy scenario and two one on one matches, each with bronze,
    silver and gold targets, attempts on a fixed sequence of seeds and a leaderboard of people and
    agents. People play them on the Play page, and teams and Python policies play them headless
    from the page, from `cuju render challenge` and from `cuju.render.challenge`, every attempt
    scored from its recording by the same rules.
- Achievements, such as Hat trick, Straight from the corner, Giant slayer and Academy graduate,
    which people and teams of the registry earn by the same rules from the frames of their games,
    requested matches and challenges, shown on end cards and listed per team and for the person.
- A guided tour of the pages, which points at the real control of each step, moves the focus,
    works by keyboard and screen reader, resumes where it stopped and offers a sample when a step
    needs one. It starts from Help, the tip of a first visit and the command palette.
- Lessons to do by hand on Help, such as jumping to a goal, following a player, playing 30 seconds,
    registering a team, starting a challenge and making a photo, each noticed from the page's own
    state, with progress kept in the browser and a reset. `cuju render tutorial` gives agents the
    same lessons as steps of the command line, Python and the page's scripts, checked from the
    home folder, with `--json` and `--check`.
- The starter team, a small Kaggle submission that ships as a sample, and the Samples part of
    Help, which adds or restores each sample in one action, as `cuju render sample` and
    `/api/help/samples` do.
- A diagnostic report on Help and as `cuju render doctor`, with versions, the browser, WebGL,
    WebGPU, the decode worker, the sound, the home folder, the library and the server's recent
    errors, as text to copy or a file, holding no personal path beyond the home folder and no
    secret.
- The page installs as an app in Chrome and Edge, with a manifest, icons made in the repository
    and a service worker that keeps the page's own files for a fast start and an offline start,
    never an answer of the API, follows each new build and works on the loopback addresses alone.
- A clean feed at `/feed` for OBS and other streaming programs, the match at a fixed size with
    its broadcast graphics alone, no pointer, controls, messages or dialogs, silent unless asked,
    over a solid or transparent background, with the graphics alone as an option, an even frame
    rate of its choice and a slate while it waits. It follows a recording, a live source by
    identifier or title through its restarts, the newest recording, the latest match of a
    tournament or the request queue, reconnects to a lost stream or server, and reloads a page
    that stops. Copy feed address in the View menu of Watch, `cuju render feed`,
    `cuju.render.feed_url` and `GET /api/feed` give its addresses, and `cuju.feed.state()` its
    state.
- Picture sizes shared by the feed, video export and photo mode, the presets 480p, 720p, 1080p,
    1440p, 4K, square, portrait and vertical and any custom width and height, a scale for the
    graphics and safe areas that keep the score, banners and captions inside the picture at every
    shape, with a margin for the buttons of short video apps as an option.

### Changed

- The controls of the page show symbols, the Lucide icons that the page ships in
    `web/vendor/lucide` under the ISC License. Toolbars, rows, dialogs, the painter, the tabs of the
    top bar, the menus of Watch, the choices of the Field page and the states of requests,
    tournaments and lessons show a symbol, alone where it reads clearly and beside its words where
    the words are the content. A symbol alone keeps its name from the language files as its
    accessible name and its tooltip, which shows on hover and on keyboard focus.
- The renderer is its own package, cuju-render, which `pip install 'cuju[render]'` installs
    into the folder of cuju. `import cuju.render`, `cuju render`, `python -m cuju.render` and
    `CUJU_RENDER` work as they did in cuju 0.2.0, and the renderer uses only the public interface
    of cuju.
- The main thread budget of a team presentation package is the mean of each drawing over two
    seconds, 1.5 ms at high quality, 1.25 ms at medium and 1 ms at low, and counts the package's
    own work alone, its behaviours, clips, reach, attachments, effects, worker messages and
    geometry. The meter starts once the package settled, after its worker's first answer, leaves
    out a drawing that stalls the page, and a team that runs under 60 percent of its budget for
    ten seconds climbs back one rung, its resting worker starting again, each fall after a climb
    doubling the wait, until a third fall keeps it down. A worker's silence counts the time the
    page draws, ten seconds before its first answer and two after.
- `cuju render pack sides` prints a line for each side, and JSON with `--json`.
- `cuju render search` prints the title of each recording beside its identifier, the time of each
    moment and the whole address that opens Watch, with how to open it when no server runs.
- Under `--json`, a command that fails prints its error as JSON on standard output alone, with
    `error`, `error_id` and `error_values`, `play`, `challenge` and `tournament` included.
- An export over HTTP takes any whole frame rate from 1 to 60, as the command line does.
- `cuju render serve --remote` on a port that a server of the renderer holds prints that server's
    SSH command.
- `repr` of a recorder names its environment, state and counts, the renderer's errors read as the
    public classes they belong to, and `dir(cuju.render)` lists the public names.
- The tutorial adds the five a side sample with `cuju render sample 5v5`, as the guide names it.
- The README offers `cuju render demo` for a first look.
- Play again, the next attempt of a challenge and every game after the first start at once, in a
    process that the server readies while the game before plays and lets go after ten minutes
    without a game or when it ends. The game, its seed, frames and recording stay exactly as in a
    new process, and the scoreboard of the game before leaves as soon as the next game starts.
- A number given as `player` to `annotate` counts the players of the left team first, as the
    rewards and observations of a batch do.
- New teams take eight kits in turn, the one that fewest teams of the registry wear first.
- `cuju.render.PolicyError` is public and an `Error` of cuju, and a policy that fails prints its
    one line without a traceback, which `CUJU_RENDER_DEBUG=on` brings back. An action outside the
    action set names the action and the set.
- A challenge of the built in AI or of a Python policy returns no achievements, as it keeps none,
    a lambda plays as Python policy, and the leaderboards mark teams and Python policies apart.
- `cuju render sample` also adds the starter team, takes the names `sample-5v5`, `sample-11v11`
    and `starter-team`, and prints what the library holds of each with `list`.
- The page decodes recordings in a Web Worker, reading them itself where a worker cannot start,
    loads the art of the players, the ball, the goals and the stands all at once, builds the
    players of a recording once with their models, and shows the progress of each stage. Sounds
    load when the sound is turned on and the montage of Home when Home shows. The sample of eleven
    a side reaches its first frame in about half the time in headless Chrome.
- `cuju.render.Recorder` codes and writes its recordings on a thread of the renderer, so the step
    that ends an episode only hands its frames over. `saved` gains a path once its file is
    written, `save()`, the new `flush()` and closing the batch wait for the writes, and a failed
    write logs a warning and raises on the next `save` or `flush`.
- Recordings use format version 2, which codes each joint relative to its parent in lanes that
    restart at a keyframe every ten seconds, and decodes to the frames of version 1 bit for bit. A
    full match of eleven a side takes about 4.4 MB instead of 11.7 MB, and the shipped samples are
    converted. The page and `cuju.render` read both versions, and `Recorder(version=1)` still
    writes version 1.
- `cuju.render.Recorder` and `cuju.render.watch` attach to their batch as step observers, so a
    recorder captures every reset and step by itself. Code that calls `Recorder.capture` keeps
    recording the same frames, since the first call turns the automatic capture off. The renderer
    reads batches, Kaggle submissions and states through public interfaces alone.
- Reduced motion keeps the lineups, celebrations, replays, decision replays, restart transitions
    and post-match show, with still shots joined by cuts in place of camera moves, fades in place
    of wipes, and the flashes, confetti and ball trail left out.
- Video export takes every shared picture size with even sides, wide, square or tall, lays the
    page out with its shorter side at 720 pixels and keeps the graphics inside the safe area, with
    `--scale` and `--safe` on the command line and in the Export video dialog, which also takes a
    custom size. Photo mode offers the shared sizes and a custom size.
- The automatic cameras frame square and tall pictures, widening the view upwards so a shot keeps
    its area, leading the ball by less and following it faster in the broadcast camera, fitting
    the whole pitch in the tactical camera, and turning the high replay and the goal kick towards
    the goal and the taker. Pictures of 16 by 9 and wider frame as before.

### Fixed

- Install the app on Help appears in Chrome and Edge. The browser's offer to install came right
    after the page loaded, before the part of Help that listens for it, and was lost, so Help only
    named the browser menu. The first script of the page now keeps the offer for the page.
- `cuju.render.show`, `cuju render app` and the other commands that start a server in the
    background find it from a Python of a virtual environment on Windows. That Python runs the
    server in a process of its own beneath the one started, so the wait for the server never
    matched it and gave up after a minute. The server file now names the call that started it.
- The page starts every time on Windows. The server and the page of a video export queued five
    connections at most, Windows refused the next ones as the page asked for its modules at once,
    and a refused module left the page blank. They queue 128 now, and a page whose module fails
    to load reloads once.
- `cuju.render.show('sample-5v5')` and `cuju render open sample-5v5` open a shipped sample in a
    home folder whose server never started, as the notebook example of the guide does.
- A page other than Watch writes its address only when it changes, so a hash typed or set there
    opens what it names, such as a match at a time, and the browser no longer throttles the page
    for writing its address many times a second.
- `cuju render tournament forfeit` and `resume`, and Award on the page while `cuju render
    tournament run` plays the tournament, reach the process that runs it, which applies them and
    answers. A wrong match key is refused first, and a process that never answers is named with
    the route of its server.
- A presentation package shows on GRF's own figure, its sockets, attachments, behaviours, material
    looks, shaders and lights, so the template of `cuju render pack new` and `pack preview` show
    the spinning ring, the bob and the glow on GRF's players. `pack check` says how many players
    draw GRF's figure, warns of a node GRF's figure lacks, naming its nodes, and of a clip role or
    a driver that shows on models alone, and says it compiled no shader.
- The template of a package keeps its full look and its worker on real hardware, where it stepped
    down its ladder and lost its worker within seconds, since a browser's clock of a tenth of a
    millisecond read single drawings as overruns and the page's own pose and loading counted
    against the team.
- `cuju render pack preview --side right` moves a package previewed on the left to the right.
- A team whose `team.json` names no kit takes the next kit of the turn on import, where every
    such team wore red, and a second preview of a package keeps its team's kit.
- A team sound is read past its first bytes, so a WAV file of a header alone, an Ogg or MP3 file
    of no sound and a stray MP3 sync answer 400 with `server.teams.sound_damaged` or
    `server.teams.sound_type`.
- The preview panel of a package shows its levels, worker states, rungs, budgets and events in
    the page's language, with the language's decimal sign, and the refusal of an unknown
    behaviour, channel, clock or driver lists the choices in words.
- The summary that a recorder's filter reads names an annotation's player by the number that
    `annotate` took, the left team first, in place of its index in the file.
- An input of a game over HTTP for a side that no person plays names the sides a person plays.
- `cuju render demo` ends within about a second of Ctrl+C.
- The first run tip takes another corner when it would cover a control or a notice, and waits
    while photo mode is open.
- The tour scrolls a control below the fold back into view while its page settles, and reads the
    text of a step once.
- The diagnostic report names the checks that warn, and says every check passes only when none
    fails or warns.
- Headings descend one level at a time on every page, with one h1 each, and the clock of the score
    bug stays out of the live region of the HUD.
- The skip buttons of Watch carry names, Surprise me says the team it makes, an open Help page shows
    lessons finished from the command line, and the command palette lists the languages.
- The values of the settings panel wrap instead of losing their end, the Watch bar keeps its
    address field on a phone, and the empty Watch page and the live count meet AA contrast in the
    light theme with targets of 24 pixels.
- The arrows move through the pause menu of Play, and Cancel in the controller setup keeps the
    notice of a controller without the standard mapping.
- The names and titles that cuju makes show in the page's language, GRF's built-in AI, Left and
    Right, You, Player 1, a person with a team, Python policy, and the titles of games, challenge
    attempts, the demo, the Recorder, live sources and the samples. Each travels as a label beside
    its English text, which the command line still prints, and a name that a person gave stays as
    given. Refusals of the server name a scenario by its name on the page, the feed's slates,
    sources and errors carry message identifiers, the leaderboard's default name, the badges of the
    achievements and the manifest of an installed page follow the language, and many Portuguese
    texts read more naturally, among them the server's refusals, Academia, Visão rápida and Rodar
    em segundo plano.
- The tournament page shows every name that the rules give in the page's language, the
    rounds, ties, groups, stage names, built in AI entrants, notes and recording titles, and
    the error of a stopped tournament in full. A failing team is named as its entrant, a
    policy failure in a person's game shows on the match, Award asks before it awards, the
    third place section and round agree, and the entrant rows line up.
- `cuju.render.watch` checks the environment before it closes the batch's earlier source, so an
    index past the batch leaves that source streaming, and `LiveSource` has a readable repr.
- A server that `show` started removes its `server.json` when its parent ends, and a file whose
    process ended is removed when the next command looks for a server.
- The sample matches date from their shipped files, so the user's own recordings list above them,
    and five a side lists before eleven a side.
- `cuju render team add` of a missing folder says that it found nothing there, `team remove` says
    what it removed, `--home` names the default folder in its help and `cuju render demo --help`
    describes the command.
- `cuju render demo` opens the browser only where a display is, as every other command does.
- The caption cues of `cuju render captions --json` and `cuju.render.captions` keep their times to
    the millisecond.
- The command table of the guide lists `challenge` and `pack`, and the README names
    `cuju render video`.
- The guide and the docstring of `Recorder` agree that version 1 takes about 2.3 times the room
    of version 2, as full matches of five and eleven a side measure.
- A chunks shader of a team package that does not compile leaves its materials standard, so the
    team's players stay visible, and the page names it in a notice, with the compiler's message in
    the browser console.
- A worker's log adds up across replies, the newest 50 lines kept, and shows in the preview panel
    and the browser console. A worker that fails for good keeps its reason, its package reads the
    level manifest, and the page names the failure in a notice.
- `cuju render pack check` reports as errors a required feature the renderer lacks, a worker or
    worklet that does not parse, read with Node.js when it is installed, a shader operator with
    nothing after it and a team model that import would set aside. It reads the manifest file
    itself, names the value it refuses in its messages, counts reflexes, actions, behaviours and
    layers from 1, adds no budget warning for a value it refuses and says why a sample shorter
    than 400 ms reads its integrated loudness above its momentary loudness.
- Import maps a team's own `model.glb` without `model.joints` in `team.json` by its bone names, as
    the team editor guesses them, and `pack check` applies the same rule.
- `cuju render pack preview` updates the team of an earlier preview of the same folder and keeps
    its identifier, names it after the manifest, takes `--no-open` and `--json`, opens the panel on
    its side after a reload and places it below the offer of the 2D view.
- `cuju render pack new` writes readable JSON with short lists on one line and prints the
    commands that come next.
- Play now on a person's match of a tournament starts the game on a page that opened on
    Tournaments with nothing on Watch.
- `cuju render play` and `cuju.render.play` print no lines of progress as JSON. The command shows
    the share played on one line of a terminal, and a submission that fails ends it in one line.
- The end card of a game that ended for the page's silence says so, and the errors of end cards
    start with a capital.
- A notice leaves the live region once its toast fades, so none carries into the next game.
- The notice of a controller with a layout of its own sets up that controller.
- The status line of Play names the sticky direction that the person holds while the engine's
    action is idle.
- Controls in the pause menu moves the focus into the card above the menu, and Esc closes the
    card before the menu.
- The ability left to the scenario reads Scenario default on Play and Matches.
- `cuju render challenge` says when an attempt scored after the time limit and when no attempt
    counts, in place of 0 seconds to score.
- A failed match of a tournament waits for an award or a retry while the matches that do not
    depend on it play on, and the tournament stops only once failed matches alone hold it up. A
    failed match shows Award on the page, an award that leaves a match to play runs the
    tournament on, and a stopped tournament leaves its lock so the command line can change it.
- A match awarded by forfeit leaves the ratings as they are.
- The presets that ship fit any number of entrants, so the Swiss of 16 plays two rounds with three.
- `cuju render tournament` reports every refused option in one line, an unknown preset among them.
- `cuju render tournament show` names a tie that has played none of its matches as not played,
    and the page shows its state alone, where both showed 0 to 0.
- Tournament identifiers start with `cup-`, so they differ from those of teams.
- The error of a failed tournament match names the team whose policy failed, the notice of a
    stopped tournament offers Award for each failed match, and Play now waits while the tournament
    is stopped, as the server does.
- The recordings of a tournament's matches name their sides as the tournament's entrants, such as
    Built-in AI 0.80 or a renamed team, on Watch, in feeds, videos and the trophy ceremony.
- A tournament fixture shows the scores of a replay and of deciding matches, and its spoken label
    gives the score and the winner. A bracket names a final or a third place match once.
- New tournament offers the teams registered while the Tournaments page was open, names a team
    entrant in words and shows the rating each entrant holds.
- A Swiss table counts byes in a column of their own, and `cuju render tournament show` names the
    bye of each round, the format of a stage in words, how ties were decided and the final ranking.
- `cuju render tournament cancel` refuses a tournament that has already ended.
- A table names no tiebreak before any of its matches has played.
- The trophy ceremony after a game of the Play page hides that game's scoreboard and live state
    while the recording loads.
- The stage editor shows points and tiebreakers only for the formats that read them.
- The grid of environments keeps its tiles while requests arrive late, as on a busy machine. A
    source reads for 15 seconds after its last answer and keeps what it read until the range
    changes, and the page keeps the last picture of a tile and marks it as refreshing.
- A video export or a clean feed never shows the offer of the 2D view, which a low frame rate of
    the export brought into the video. A video shows a recording's annotations only with
    `--annotations` or the Annotations check box of the Export video dialog.
- `cuju render video` checks the range before it looks for Chrome and ffmpeg.
- A clean feed with `bg=transparent` is transparent in Chrome and OBS, whose frame drew an opaque
    backdrop behind a page of another color scheme.
- `cuju render feed` lists live sources by title and stops with an error for a recording that the
    library lacks or a tournament that the server lacks.
- The Copy feed address dialog offers the camera, the graphics alone and each live source and
    tournament of the server, and names its scale list Graphics scale.
- `cuju.photo.set` throws for a number out of range, as documented, and an unknown resolution
    names the sizes that fit.
- A tall or square feed gives the scoreboard the width of the safe area, so team names show whole.
- A feed moves on from a live stream that lost its connection to the newer source that the server
    names, and a question to the server that hangs counts as failed after 10 seconds.
- A video under a megabyte reads in KB, the server's errors carry no class name, the page's
    message of a missing program names the variable that the server takes, and the doctor warns of
    a missing Chrome or ffmpeg rather than passing it as ok.
- The offer of the 2D view says 1 frame a second in the singular.
- A page out of sight lets its live stream go after half a minute and resumes it when shown, so
    tabs left behind others no longer take the six connections that a browser keeps to the server
    and keep new pages from loading. The server sends each answer without the delay of small
    writes, which made every request take a fifth of a second on Windows, and puts the shipped
    languages into the page. The decode worker no longer loses its first request.
- On a narrow screen the banner of a restart shows under the scoreboard rather than over it, and
    in a picture of fixed size the team sheets keep clear of the scoreboard and the banner of the
    kick off.
- A team package whose worker fails for good keeps its shaders, passes and lights, and a page
    that draws slowly waits three drawings past the two seconds before it ends a silent worker.
- The captured pointer is released when any panel, details section, menu or card opens, the
    panels added in this release among them, and when focus moves to a control.
- Space on a focused summary or other control acts on that control alone, and the Watch controls
    stay in view while keyboard focus is inside them.
- The renderer shows Full time only for a recording or live source whose header names a full
    match. An older recording without timing that ends an episode shows End of episode, and the
    show after it opens under Episode complete.
- Enter closes the renderer's statistics screen from the focus it opens with, as it does anywhere
    away from a control.
- The statistics of a live source with automatic resets describe its latest completed episode,
    and the current episode only while none has completed.
- Recordings and teams saved in the same second each receive an identifier of their own, so no
    save overwrites another and no added or duplicated team fails.
- The history of requested matches keeps the newest 200 requests that have ended, with every
    waiting or playing one, and the Matches page lists them 50 at a time behind Show more.
- `cuju render sample` restores a sample from the Trash with its details and says so.
- Importing a team keeps the files of its `cuju-team` folder that the page leaves unread. A file
    that the page reads and that fails its check is set aside under its name followed by
    `.rejected` and logged, where the import deleted every file it did not know before.
- A team sound replaced in the editor plays on the page at once. Team entries carry a
    `sounds_version` that changes with the sound files, and the page loads the sounds again when
    it changes.
- Sounds of the play stop on a seek, a jump, a restart and a change of match, team sounds and
    sounds due later included, and at most twelve of them sound together, the oldest ending first.
- KayKit's characters and custom player models wear the shirt numbers on their backs, placed from
    the torso of each model, and the team style's `hidden_numbers` turns them off on the models
    where they do not fit.
- The guided tour's card leaves the focus and the Tab key free, so Try it reaches its control
    from the keyboard, and screen readers meet it as a dialog beside the page. A dialog that
    closes gives the focus back to its opener only while no other dialog took it.
- The Watch timeline says its value as a slider, such as `1:23 of 5:00`, and H, the question
    mark, M, F and the other single keys of the page work while a button or a link has the focus.
- The skip link keeps the address of the page, every page has a window title, a name and a
    heading of its own, and a change of page is said to screen readers.
- The lessons that only a page can check complete when a script follows the steps of
    `cuju render tutorial` without starting them, and Help takes in the lessons the server knows
    done when it loads.
- The lesson panel is a named region and keeps the focus after Open the sample match, the
    first-run tip comes right after the top bar in the Tab order, and the lesson Follow a player
    says what a number key does.
- Scenario names such as `5_vs_5_l0_r0` read as 5 vs 5, with the agents of each side in words.
- Links, unearned achievements and the A button of the controller icons meet a contrast of
    4.5 to 1 in both themes, and No more tips is a target of at least 24 pixels.
- The command palette finds Photo mode, Surprise me and every challenge, and its `gotea` example
    finds Go to Teams.
- `cuju.surprise({apply: true})` throws unless a team editor shows on the Teams page, and a seed
    other than text or a number throws.
- The tour rings the part of a large region in view and sets its card beside a tall control, the
    Help samples list the starter team as in the registry, the install status reads as one
    sentence, the leaderboard tables have captions, the icons of the top bar are hidden from
    screen readers, the Start and End fields of Export video are named by their labels alone, and
    the Annotations button of Watch and the Date and Size columns of Recordings fit at 1280 by 720.
- Play and the challenges read plainly. A challenge run gives the seconds of its counting attempts
    as seconds in all, or its value alone when no attempt counted, a first run says so in place of
    a new personal best, the medal shows once, an achievement earned again shows once a run, the
    last end card returns the focus to the challenge just played, and every button of a challenge
    names its challenge. The status line of a game names a held direction, sprint and dribble, in
    natural Portuguese too, and the ability rows keep the slider and its value on one line at
    phone width.
- The annotation labels of Watch and of exported videos hang under the feet of each player, the
    team sheets show the formation of both teams of five a side, a Trophy ceremony hides the
    scoreboard of a game of Play at once, and the Export video dialog names the range of a finished
    export.
- Captions name every player as of a team, as in number 4 of Right, with no article before a
    team's name, in English and Portuguese. Recordings keep the rule of the Title cell across a row
    whose other cells wrap, a folder of one file reads as 1 file, a black kit keeps its outline on
    the dark Teams list, and a team's control names its action set as such.
- A recording of version 1 must have the frame size of its players, as the page requires, and
    a last frame cut short is left out.
- Importing a broken recording raises an ArgumentError that says why, in place of a raw
    traceback.
- A recording that decompresses beyond the cap names the cap in a message of its own rather than
    inside the message of a failed decompression, and one beyond the caps of frames names its
    frames and its frames times players.
- Annotations of a negative or non-integer frame, and annotation files nested too deeply, are
    left out.
- The summary of a recording that a hard stop left empty during an import is made once and kept,
    and every summary is written through a temporary file.
- The server skips alone a live announcement with a field it cannot read or a port below 1024, so
    the list of the other live sources stays whole, and the page keeps a live stream within its
    80 MiB budget whatever its header claims.
- NOTICE names the icons of the installable page, drawn from cuju's logo, under CC BY 4.0, and
    every asset that `web/assets/manifest.json` lists as converted from Gameplay Football, and the
    README links the guides, the changelog, NOTICE and the licenses by their full addresses, so
    they open from PyPI.
- A reset of the lessons waits out a look at the server's lessons under way and drops an answer
    that the reset overtook, so a lesson done right after a reset is reported to the server and
    stays done.

### Security

- The sandbox of team workers keeps an opaque origin when its route opens as a whole window, by a
    sandbox directive of its own policy, and its bootstrap starts a worker only inside a frame, in
    an opaque origin, for the page right above it. The page refuses a worker that reaches storage
    as well as the network, every response keeps its window apart from a window of another site
    that opened it, and the service worker answers only with copies that carry the digest of their
    file, so a page of another site can no longer plant a page in the cache.
- An imported team takes the identifier of its folder and never the one its `team.json` names, an
    import that fails at any step removes the folder it began, the registry reads a team file of
    at most 1 MiB that holds an object and leaves out alone a folder that fails to read, and
    values of the wrong type in a team file, a model, a clip or a package model fall back or fail
    their check by name. A crafted archive can no longer break the list of teams or reach files
    outside the folder of teams.
- A team's AudioWorklet module loads into an audio context of the team's own, whose sound streams
    into the team's buses through their governor and limiter, so a module can no longer change
    the renderer's meters, governors or limiters. The server reads each module as JavaScript does
    and refuses every import, dynamic import, `import.meta` and export from, however a comment,
    string or statement hides it, and it serves every package module but the sound worklet as
    plain text outside developer mode.
- Each overlay slot counts the flashes of the drawings a worker sends it, on a grid of its own,
    and a slot that reaches three flashes in a second hides for three seconds, so a worker's
    overlay can no longer flash past the flash governor.
- A team shader runs its nested loops at most 1024 times, counted through helper calls, and at
    most 65536 words of code a vertex or a fragment through loops, helpers and macros, on the
    server and on the page. A team worker draws with the 2D context alone, with no WebGL, WebGPU
    or nested worker, so a package can no longer hang the GPU.
- An uploaded tar archive is read one member at a time and refused at the first member past the
    limits of 10,000 files and 500 MB, with at most 1 MiB of headers for each member and 564 MB
    read in all, and the entries of a zip archive are counted from its bytes before zipfile reads
    its directory, so a compressed archive of a few kilobytes that holds 200,000 members is
    refused at once. On a Python without the data filter of tar, the members land without their
    mode, owner or times.
- The Python reader of recordings holds a header to 1 MiB, a file to 256 MiB once decompressed,
    a recording to 32 players and 50,000 frames, and decodes version 2 a thousand frames at a time,
    so a small crafted file no longer takes gigabytes of memory.
- A recording header that holds NaN or an infinity is refused, and the server answers the page
    with strict JSON, so one crafted recording no longer breaks the library list.
- The type of every header field that the library reads is checked at import and when a
    summary is made, and search, captions and moments keep working with the files of an older
    install that hold others.
- A recording whose title, scenario or team names are numbers, lists or objects lists on Home,
    Recordings, the palette and the Match menu by its id or by the digits of the number, every
    summary of the library reaches the lists with its fields made text, and labels nest at most
    16 deep. A title or a name shows a message of the page only when its id starts with
    `server.names.` or `server.tournament.label.`, so a crafted header can no longer break the
    lists, overflow the stack or show any message of the page as its title.
- The server keeps the message of a recording's title and team names to the names that cuju
    makes, so a crafted header can no longer show any other message of the page.
- The page opens a recording that decompresses to at most 128 MB, down from 512 MB, holds at
    most 50,000 frames and 1,000,000 frames times players and lists at most 64 players, and reads
    a recording itself only when the decoding worker cannot start, so a small crafted file can no
    longer take gigabytes of the browser's memory or be decoded twice. A header that is no object
    or whose players lack a team or an index is refused with a message, malformed teams and rates
    of steps fall back to Left, Right and ten steps a second, and an engine scorer or a foul that
    names a player beyond the header is set aside.
- Save captions writes each cue on one line, with a line break of a team name as a space and
    `&`, `<` and `>` as character references, so a team name can no longer add cues or markup to
    the WebVTT file.
- The WebVTT file of the server and of `cuju render captions` keeps each caption on one line
    with `&`, `<` and `>` escaped, as the page saves it.
- The page takes from a team worker plain data alone and bitmaps only in its overlays at the size
    of their slots, and the sandbox's wrapper keeps its port out of the module's reach, so a
    worker can no longer send bitmaps of any size or answers around the reply limit.
- The server serves the images, sounds, model and clips of a team by their exact names alone and
    never through a link, and an import sets aside a file named as one of them in another case or
    with more after the slot, such as `Shirt-Front.png`, `shirt-front.x.png` or `clips/foo.GLB`,
    so no file of an archive reaches the page unchecked where names match whatever their case.
- An archive with a member whose name opens a device on Windows, such as `nul`, `con.txt`,
    `COM¹` or `CONIN$`, or whose name ends in a dot or a space, is refused on every system, so an
    upload can no longer open a device, lose members or hang.
- The name that a team file brings, imported or edited by hand, keeps only the characters that
    print, so the escapes of a terminal and the marks that turn the direction of text become
    spaces before `cuju render team list` prints it.
- A tournament file carries a seal, a keyed digest under a key of the home folder, and a running
    tournament whose file has no valid seal, one dropped into the folder or edited by hand, loads
    stopped until a person resumes it, and every file plays at most eight matches at once, so a
    dropped file can no longer play the teams it names unasked.
- Behind the proxy of Google Colab the server takes a request that changes data only from an
    origin that names the host of the request, so the page of another notebook can no longer
    change the data of this one.
- The doctor's report writes the renderer's home folder outside the user's home as
    `$CUJU_RENDER_HOME` and the user's name as `<user>`, and on Windows matches either path
    whatever its case, so a pasted report keeps them private.
- A team added from a folder leaves out every link of the folder, to a file or to a folder, and
    logs it, so a link to a key of the user's can no longer travel into the team and its exports.
- Every Python process that the renderer starts runs with `-P` on Python 3.11 and later, and on
    Python 3.10 starts in an empty folder, so the folders of the home such as `teams` and
    `requests` never import as packages there.
- A path inside a team package is refused by the rule of Windows devices that archive members
    follow, so a part such as `nul.glb` or one that ends in a dot never reaches the folder.

### Known limits

- Each tab of the page opens its own live stream of a game or a live source, so several tabs on
  one server hold several streams. One stream shared between the tabs of a browser is planned for
  cuju-render 0.2.

[Unreleased]: https://github.com/AndreKoraleski/cuju-render/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/AndreKoraleski/cuju-render/releases/tag/v0.1.0
