# Copyright 2026 The cuju Authors
# SPDX-License-Identifier: Apache-2.0

"""Watches cuju's matches in a browser, saved or live, in 3D with sound.

The renderer reads GRF states and never writes one, so a match plays the same bits watched or not.
`show` opens the viewer on a batch, a recording or a live source in one call, starting the server
when none runs. `Recorder` and `record` save the matches of a batch, `watch` streams one
environment of a running batch, `add_team` registers a Kaggle submission folder, `play` records a
match between two teams of the registry, `challenge` plays a challenge headless with a team or a
policy, and `serve` runs the local page that plays them all. `feed_url` gives the address of a
clean feed for a streaming program such as OBS. The guide is in the repository's
`docs/rendering.md`.
"""

from __future__ import annotations

import logging
import struct
import threading
import weakref
from collections.abc import Callable
from pathlib import Path
from typing import Any

from cuju.errors import ArgumentError

from ._format import annotations as _annotations
from ._format import keep as _keep
from ._format import recording as _recording
from ._format import writer as _writer
from ._http.server import serve
from ._playing.errors import PolicyError
from ._registry.teams import add_folder as add_team
from ._store import library as _library
from ._store.home import home
from ._text import messages as _messages
from ._watch import live as _live
from ._watch.live import LiveSource
from ._watch.show import View, show

__all__ = [
    'LiveSource',
    'PolicyError',
    'Recorder',
    'View',
    'add_team',
    'captions',
    'challenge',
    'challenges',
    'delete_group',
    'feed_url',
    'home',
    'on_batch_created',
    'play',
    'record',
    'recordings',
    'restore_group',
    'search',
    'serve',
    'show',
    'watch',
]

_LOGGER = logging.getLogger('cuju')


class Recorder:
    """Records the matches of one environment of a batch into the renderer's library.

    The recorder is a step observer of the batch, so it captures every `reset` and step by itself.
    A recording ends when its episode ends, and `save` writes it, so a batch with automatic resets
    yields one recording per episode. Code that calls `capture` after each step, as with cuju
    0.2.0, still works, since the first call of `capture` turns the automatic capture off.

    Filters keep only the episodes worth watching. At the end of each episode the recorder reads
    its summary, and an episode that a filter drops is discarded without writing anything.
    `annotate` attaches numbers and text of a training loop or a policy to the captured steps.

    The step that ends an episode only hands its frames over, and one thread of the renderer codes
    and writes the recording while training steps on. `save` and closing the batch wait for the
    recordings handed over, and `flush` waits for them alone.

    Attributes:
        environment: The index of the environment.
        saved: The paths of the recordings written so far, each added once its file is written.
        version: The version of the recording files.
        episodes: The number of episodes that ended, saved or dropped.
        dropped: The number of episodes that the filters dropped.
    """

    def __init__(
        self,
        batch: Any,
        environment: int = 0,
        title: str | None = None,
        teams: list[dict[str, Any]] | None = None,
        scenario: str | None = None,
        version: int = 2,
        keep: str | Callable[[dict[str, Any]], Any] | None = None,
        every: int = 1,
        min_reward: float | None = None,
    ) -> None:
        """Attaches a recorder of `environment` to `batch`, which captures from the next call on.

        Args:
            batch: The batch.
            environment: The environment to record.
            title: The title of each recording, by default the scenario and the environment.
            teams: The name, `color` and `secondary` color of the left and right team, each an
                RGB list of three integers from 0 to 255, each optional.
            scenario: The name of the scenario that the header records, by default the batch's.
            version: The version of the recording files, 2, or 1 for the readers of cuju 0.2.0,
                which takes about two and a half times the room.
            keep: Which episodes to save, `all` or `None` for every one, `goals` for those with a
                goal, or a function that takes the summary of the episode and returns whether to
                save it. The summary holds the `episode` number, counted from 0 over the episodes
                that the recorder ended, the `environment`, the `score` of the left and right
                team, the number of `goals`, the `length` in frames, the last `steps` number, the
                `rewards` of each agent summed over the captured steps, their sum, `reward`, and
                the `annotations` of the episode, each with its `frame`, `step`, `player`,
                `values`, `text`, `action` and `probabilities`, the player numbered as
                `annotate` takes it.
            every: Saves the first episode and every `every`-th after it, counting every episode
                that ends, saved or not.
            min_reward: Saves only episodes whose `reward` is at least this.

        Raises:
            ArgumentError: If the batch is not a `BatchEnvironment`, the environment is not one of
                the batch, or a version or filter is invalid.
        """
        if not callable(getattr(batch, 'add_observer', None)):
            raise ArgumentError(
                'expected a BatchEnvironment, found a batch whose states the recorder cannot read; '
                'record one of the batches of a MultiDeviceBatch instead'
            )
        if not 0 <= environment < batch.environment_count:
            raise ArgumentError(
                f'expected an environment from 0 to {batch.environment_count - 1}, '
                f'found {environment}'
            )
        if version not in _recording.VERSIONS or isinstance(version, bool):
            raise ArgumentError(f'expected a version from {_recording.VERSIONS}, found {version!r}')
        self.version = version
        self._filter = _keep.Filter(keep, every, min_reward)
        # The rewards of the episode, the episodes ended so far and those dropped.
        self._rewards: list[float] = []
        self.episodes = 0
        self.dropped = 0
        # The recordings handed to the writer and not written yet, and the error of a failed
        # write, which the next `save` or `flush` raises.
        self._pending = 0
        self._written = threading.Condition()
        self._failure: Exception | None = None
        # The annotations of the recording, by frame and player.
        self._notes: dict[tuple[int, int], dict[str, Any]] = {}
        # The batch holds the recorder, which holds the batch weakly, so that a dropped batch
        # frees its memory without waiting for the garbage collector.
        self._batch = weakref.ref(batch)
        self.environment = environment
        self._title = title
        self._teams = teams
        self._scenario = scenario or _live.scenario_name(batch)
        players = int(batch.left_players[environment] + batch.right_players[environment])
        self._reader = _recording.StateReader(players)
        self._lineup: list[dict[str, Any]] | None = None
        self._frames: list[bytes] = []
        self._timing = None
        self.saved: list[Path] = []
        # The information of the last step, whose scoring signal completes an ending episode.
        self._information: dict[str, Any] | None = None
        # Whether the caller captures by hand, as with cuju 0.2.0, which ends automatic capture.
        self._manual = False
        batch.add_observer(self)

    def __repr__(self) -> str:
        batch = self._batch()
        if batch is None:
            state = 'its batch gone'
        elif any(observer is self for observer in batch.observers):
            state = 'by hand' if self._manual else 'capturing'
        else:
            state = 'detached'
        return (
            f'Recorder(environment {self.environment}, {self._scenario!r}, version {self.version}, '
            f'{state}, {len(self._frames)} frames of the current episode, {self.episodes} '
            f'episodes ended, {len(self.saved)} saved, {self.dropped} dropped)'
        )

    def __call__(self, batch: Any, done: Any, information: dict[str, Any]) -> None:
        """Captures a reset of the environment or a step, as a step observer of the batch.

        A batch that closes waits for the recordings handed to the writer.
        """
        if done is None:
            if information.get('close'):
                self._wait()
                return
            if self._manual or 'reset' not in information:
                return
            reset = information['reset']
            if reset is None or bool(reset[self.environment]):
                self._capture(batch, None)
            return
        self._information = information
        if not self._manual:
            self._capture(batch, done)

    def capture(self, done: Any = None) -> Path | None:
        """Adds the environment's current step by hand, and saves the recording when its episode
        ended.

        The recorder captures by itself, so a program needs this only to choose its steps. The
        first call turns the automatic capture off for good and drops the frames that it took and
        has not saved, so code written for cuju 0.2.0, which calls this after `reset` and after
        each `step`, records the same frames as before.

        With automatic resets, the step that ends an episode already shows the next one's start,
        so the recording ends at the step before, marked as the end, and the new start opens the
        next recording.

        Args:
            done: The done flags that `step` returned, or `None` after `reset`.

        Returns:
            The path of the recording that this call hands to the writer, which `saved` lists
            once its file is written, or `None`, also for an episode that the filters dropped.

        Raises:
            ArgumentError: If the batch is gone.
        """
        if not self._manual:
            self._manual = True
            self._frames, self._lineup, self._rewards, self._notes = [], None, [], {}
        batch = self._batch()
        if batch is None:
            raise ArgumentError('expected the batch of the recorder, found it gone')
        return self._capture(batch, done)

    def _capture(self, batch: Any, done: Any) -> Path | None:
        """Adds the environment's current step, as `capture` describes."""
        ended = done is not None and bool(done[self.environment])
        if done is not None:
            # The step's rewards belong to the episode that it ends, if it ends one.
            rewards = _keep.step_rewards(batch, self.environment, self._information or {})
            if not rewards:
                rewards = [0.0] * len(self._rewards)
            self._rewards = [
                total + reward
                for total, reward in zip(
                    self._rewards or [0.0] * len(rewards), rewards, strict=True
                )
            ]
        saved = None
        if ended and batch.auto_reset:
            if self._frames:
                last = bytearray(self._frames[-1])
                (flags,) = struct.unpack_from('<i', last, 28)
                struct.pack_into('<i', last, 28, flags | 1)
                # GRF: the scoring signal is 1 when the left team scores and -1 for the right.
                information = self._information or {}
                signal = information.get('score_reward')
                scored = int(signal[self.environment]) if signal is not None else 0
                if scored:
                    offset = 8 if scored > 0 else 12
                    (goals,) = struct.unpack_from('<i', last, offset)
                    struct.pack_into('<i', last, offset, goals + 1)
                    struct.pack_into('<i', last, 28, (flags | 1) & ~(31 << 8))
                self._frames[-1] = bytes(last)
            saved = self._finish()
        state = batch.get_state(self.environment, stacked=batch.stacked)
        self._timing = _recording.scenario_timing(state)
        if self._lineup is None:
            self._lineup = self._reader.lineup(state)
        closing = ended and not batch.auto_reset
        self._frames.append(self._reader.frame(state, 1 if closing else 0))
        if closing:
            saved = self._finish()
        return saved

    def _finish(self) -> Path | None:
        """Ends the episode, which the filters save or drop, and returns the path of a save."""
        if not self._frames or self._lineup is None:
            self._rewards = []
            return None
        notes = [
            _annotations.public(note, self._frames, self._lineup) for note in self._notes.values()
        ]
        summary = _keep.episode_summary(
            self.episodes, self._frames, self._rewards, self.environment, notes
        )
        self.episodes += 1
        if self._filter(summary):
            return self._hand_over()
        self._frames, self._lineup, self._rewards, self._notes = [], None, [], {}
        self.dropped += 1
        return None

    def annotate(
        self,
        values: dict[str, Any] | None = None,
        text: str | None = None,
        player: Any = None,
        step: int | None = None,
        probabilities: Any = None,
        action: Any = None,
    ) -> None:
        """Attaches numbers or text to a captured step, which the page shows with the recording.

        Annotating reads nothing of the batch and changes nothing of it. Several calls for one
        step and player join their numbers, and a later text, action or probabilities replace the
        earlier ones. A recording of version 1 has no room for annotations and leaves them out.

        Args:
            values: Named numbers, such as `{'value': 0.4, 'reward': 1.0}`, at most 16 names of at
                most 40 characters. Each number is kept to six significant digits.
            text: A short text, cut at 200 characters.
            player: The player, a number that counts the left team's players first and then the
                right team's, as the batch counts its agents, or a pair of team, 0 for the left,
                and the index within the team, or `None` for the whole match. The summary that a
                filter reads names the player by the same number.
            step: The step of the current episode, as the frame's step counts it, by default the
                step captured last.
            probabilities: The probability of each action, a sequence indexed by action or a
                mapping of action to probability. The three most likely actions are kept.
            action: The action chosen.

        Raises:
            ArgumentError: If no step is captured yet, the step is not one of the current
                episode, or a part is invalid.
        """
        if not self._frames or self._lineup is None:
            raise ArgumentError('expected a captured step to annotate, found none')
        record = _annotations.note(self._lineup, values, text, player, probabilities, action)
        _annotations.merge(self._notes, _annotations.frame_of(self._frames, step), record)

    def save(self) -> Path | None:
        """Writes the frames captured so far as one recording, starts a new one, and waits until
        every recording handed to the writer is written.

        A call by hand saves whatever the filters say, as a training run that stops may wish.

        Returns:
            The path of the recording, or `None` when nothing was captured.

        Raises:
            Exception: The error of a write that failed since the last `save` or `flush`.
        """
        path = self._hand_over()
        self.flush()
        return path

    def flush(self) -> None:
        """Waits until every recording handed to the writer is written.

        Raises:
            Exception: The error of a write that failed since the last `save` or `flush`, which
                the logger `cuju` also reported when it happened.
        """
        self._wait()
        with self._written:
            failure, self._failure = self._failure, None
        if failure is not None:
            raise failure

    def _wait(self) -> None:
        """Waits for the writes of the recorder."""
        with self._written:
            self._written.wait_for(lambda: self._pending == 0)

    def _hand_over(self) -> Path | None:
        """Hands the frames captured so far to the writer, and returns the path they will take.

        The step pays for the header and the name of the file alone, and the writer codes and
        writes the recording. A writer that is busy with several recordings makes this wait for
        room.
        """
        if not self._frames or self._lineup is None:
            return None
        # A title of the recorder's own is a label, which the page shows in its own language.
        title = self._title or _messages.label(
            'server.names.recorder',
            scenario=_messages.scenario(self._scenario),
            environment=self.environment,
        )
        # A batch may have been reset with another seed before the capture, so the recording
        # names its environment alone and leaves the seed unknown.
        head = _recording.header(
            title,
            self._scenario,
            self._lineup,
            self._teams,
            len(self._frames),
            self._timing,
            {'source': 'recorder', 'environment': self.environment},
        )
        frames, notes = self._frames, list(self._notes.values())
        self._frames, self._lineup, self._rewards, self._notes = [], None, [], {}
        path = _library.reserve()
        version = self.version

        def write() -> None:
            try:
                _library.save(head, frames, path.stem, version, notes)
            except Exception as error:
                if not path.exists():
                    path.with_suffix('.json').unlink(missing_ok=True)
                _LOGGER.warning(
                    'cuju render: the recorder could not write %s, %s: %s',
                    path.name,
                    type(error).__name__,
                    error,
                )
                with self._written:
                    self._failure = error
            else:
                self.saved.append(path)
            finally:
                with self._written:
                    self._pending -= 1
                    self._written.notify_all()

        with self._written:
            self._pending += 1
        _writer.WRITER.submit(write)
        return path

    def close(self) -> Path | None:
        """Detaches the recorder from its batch, saves the frames captured so far and waits until
        every recording handed to the writer is written.

        Returns:
            The path of the recording that this call saved, or `None` when nothing was captured.

        Raises:
            Exception: The error of a write that failed since the last `save` or `flush`.
        """
        batch = self._batch()
        if batch is not None and any(observer is self for observer in batch.observers):
            batch.remove_observer(self)
        return self.save()

    def __enter__(self) -> Recorder:
        return self

    def __exit__(self, *exception: object) -> None:
        """Closes the recorder, so that a `with` block saves its last episode at its end."""
        self.close()


def record(batch: Any, environment: int = 0, **options: Any) -> Recorder:
    """Records the matches of one environment of a batch, as a `Recorder` that also serves as a
    context manager.

    Leaving the `with` block detaches the recorder and saves the episode that it was capturing,
    and every episode that ended inside the block is saved already.

    Args:
        batch: The batch.
        environment: The environment to record.
        **options: The other arguments of `Recorder`, such as `title` and `teams`.

    Returns:
        The recorder, whose list `saved` holds the paths of its recordings.
    """
    return Recorder(batch, environment, **options)


def play(
    left: str,
    right: str,
    scenario: str = '11_vs_11_kaggle',
    seed: int | None = None,
    title: str | None = None,
    device: str = 'cpu',
    ability: tuple[float | None, float | None] = (None, None),
) -> Path:
    """Plays a match between two teams of the registry, saves it and returns the recording.

    Args:
        left: The team of the left side, a registry identifier or `builtin`.
        right: The team of the right side.
        scenario: A shipped scenario, without agent counts, which the teams decide.
        seed: The seed of the match, or `None` for one drawn from the clock.
        title: The title of the recording.
        device: `cpu` or `cuda`.
        ability: The ability of the built-in AI on the left and on the right, each from 0 to 1, or
            `None` for the scenario's, GRF's team difficulty for every player the built-in AI
            controls.

    Raises:
        ArgumentError: If a team is unknown, plays another format than the scenario's, or an
            ability lies outside 0 to 1.
    """
    from ._playing.play import play as run

    return run(left, right, scenario, seed, title, device, ability)


def challenge(
    challenge: str,
    team: str | None = None,
    policy: Any = None,
    name: str | None = None,
    control: dict[str, Any] | None = None,
    attempts: int | None = None,
    device: str = 'cpu',
    progress: Any = None,
    keep_recordings: bool = True,
    fail_attempts: bool = False,
) -> dict[str, Any]:
    """Plays a challenge headless with a team of the registry or a Python policy, and scores it.

    Every attempt plays the challenge's seed of its index, as fast as the policy answers, and is
    saved as a recording, and the recordings of the run form one group of the library. A full run
    reaches the challenge's leaderboard, and a run of fewer attempts is practice. A team of one
    dynamic agent faces the very episodes that a person faces on the Play page.

    Args:
        challenge: The challenge, an identifier that `challenges` lists, such as
            `empty_goal_close`.
        team: A team of the registry, or `builtin` for GRF's built-in AI on the whole side.
        policy: A Kaggle agent function, `agent(obs)` or `agent(obs, configuration)`, in place of
            a team.
        name: The name of a policy on the leaderboard, by default the function's name.
        control: The control of a policy, as a team's control settings, by default one player of
            dynamic assignment.
        attempts: The attempts to play, by default the challenge's count.
        device: `cpu` or `cuda`.
        progress: A function called with the result of each attempt as it ends.
        keep_recordings: Whether the library keeps the attempts as recordings. A run with false
            scores, ranks and earns exactly as one that keeps them, and adds nothing to the library.
        fail_attempts: Whether a policy that fails ends its attempt alone, which then counts as a
            failed attempt with the policy's error, while the run goes on, as the page, the command
            line and the benchmarks play.

    Returns:
        A plain dictionary of the run, its `value`, `seconds`, `medal`, `rank`, `personal_best`,
        whether it was `practice`, its `medals` as items, its count of `failed_attempts`, the
        result and recording of each of its `attempts`, `None` for a run without recordings, and
        the `group` of its recordings or `None`.

    Raises:
        ArgumentError: If the challenge, the team, the control or the attempts do not fit.
        PolicyError: If the policy fails, answers with anything but actions, or stops answering,
            unless `fail_attempts` is true.
    """
    from ._playing.challenges import run

    return run(
        challenge,
        team,
        policy,
        name,
        control,
        attempts,
        device,
        progress,
        keep_recordings,
        fail_attempts,
    )


def challenges() -> list[dict[str, Any]]:
    """Returns the catalog of challenges, each with its goal, measure, targets and seeds."""
    from ._playing.challenges import challenges as catalog

    return catalog()


def recordings(group: str | None = None, trash: bool = False) -> list[dict[str, Any]]:
    """Returns the summaries of the library, as the Recordings page lists them, newest first.

    Each summary of a recording of a challenge run holds its `group`, with the run's identifier
    `id`, its `title`, `competitor` and `result`, the `attempt` of the recording and the run's
    `attempts`, `state`, `value`, `seconds`, `medal` and `practice`.

    Args:
        group: The identifier of a group, to list its recordings alone in the order of their
            attempts.
        trash: Whether to list the Trash in place of the library.
    """
    return _library.matches(trash, group)


def delete_group(group: str) -> list[str]:
    """Moves every recording of a group to the Trash at once, and returns their identifiers.

    Each recording restores from the Trash like any other, and `restore_group` restores them all.
    An unknown group, or one already in the Trash, returns an empty list.
    """
    return _library.trash_group(group)


def restore_group(group: str) -> list[str]:
    """Restores every recording of a group from the Trash, and returns their identifiers."""
    return _library.trash_group(group, restore=True)


def search(query: str = '', limit: int | None = None) -> dict[str, Any]:
    """Finds moments across every recording of the library, as `cuju render search` does.

    The query holds words that name kinds of moments, such as `goal`, `shot` or `corner`, other
    words that match the title, scenario, teams and players, and filters such as `team:Greens`,
    `player:9`, `after:60`, `score:trailing` or `source:tournament`, as the guide describes under
    Searching moments.

    Args:
        query: The query, such as `goal team:Greens after:60`.
        limit: The most results, by default the query's `limit:` or 50.

    Returns:
        The `results`, each with the recording as `match`, the `kind`, the time `t` in seconds of
        the recording, the `seek` time a few seconds before it that opens Watch, the `minute` of
        the clock, the team, the player's `number` and `name`, the `score`, a plain line of
        `text` and the address `url` of the page, and the `total` before the limit.
    """
    from ._moments import search as _search

    return _search.search(query, limit)


def captions(recording: str | Path, path: str | Path | None = None) -> list[dict[str, Any]]:
    """Returns the caption cues of a recording and writes them as WebVTT when given a path.

    Args:
        recording: A recording identifier of the library, such as `sample-5v5`, or a `.cjr` file.
        path: A file to write the captions to as WebVTT, or `None`.

    Returns:
        The cues, each with its `start` and `end` in seconds to the millisecond, its message `id`
        and `params` of the table of captions and its `text`.
    """
    from ._moments import search as _search

    cues = _search.captions(recording)
    if path is not None:
        text = _search.captions_vtt(recording)
        Path(path).write_text(text, encoding='utf-8', newline='\n')
    return cues


def watch(
    batch: Any,
    environment: int = 0,
    title: str | None = None,
    teams: list[dict[str, Any]] | None = None,
    backlog: bool = False,
) -> LiveSource:
    """Streams one environment of a running batch to the renderer's page.

    The source is a step observer of the batch, which publishes after each step while a viewer
    watches, as `CUJU_RENDER` makes every batch do. Close the source, or the batch, to withdraw it.

    Args:
        batch: The batch.
        environment: The environment to show.
        title: The title that the page lists.
        teams: The names and colors of the left and right team, as for `Recorder`.
        backlog: Whether to read every step, watched or not, so that any viewer starts with ten
            seconds of history, at the cost of one state read per step.

    Returns:
        The source, which the batch holds as one of its observers, in place of any source that
        `watch` or `CUJU_RENDER` gave it before.

    Raises:
        ArgumentError: If the batch shows no live source or `environment` is not one of its
            environments, which leaves any earlier source of the batch as it was.
    """
    if not callable(getattr(batch, 'add_observer', None)):
        raise ArgumentError(
            'expected a BatchEnvironment, found a batch whose steps show no live source; watch '
            'one of the batches of a MultiDeviceBatch instead'
        )
    # The environment is checked before the batch's earlier source closes, so a mistake leaves it.
    _live.check_environment(batch, environment)
    for observer in batch.observers:
        if isinstance(observer, LiveSource):
            observer.close()
    source = LiveSource(batch, environment, title, teams, backlog=backlog)
    batch.add_observer(source)
    return source


def feed_url(source: str = 'auto', *, port: int | None = None, **options: Any) -> str:
    """Returns the address of a clean feed, a picture of fixed size for a streaming program.

    The address names the page at `/feed` of the renderer's server, the running server of the
    renderer's folder, or the server on `port`, 8780 by default, when none runs. The feed shows
    the Watch page with its broadcast graphics alone and follows its source, as `cuju render feed`
    prints it.

    Args:
        source: What the feed follows, `auto`, `live`, `latest`, `tournament`, `queue`,
            `live:NAME`, `tournament:ID` or the identifier of a recording.
        port: The port of the server, when no server of the renderer's folder runs.
        **options: The options of the feed's address, such as `size='vertical'`, `width` and
            `height`, `scale`, `safe`, `bg`, `layer`, `audio`, `volume`, `fps`, `camera`, `loop`,
            `broadcast`, `show`, `score`, `slate`, `quality`, `theme`, `arena`, `time` and `t`.

    Raises:
        ArgumentError: If the source or an option is out of place.
    """
    from ._export import feed as _feed
    from ._http import launch as _launch

    server = _launch.running() if port is None else None
    base = server.url.split('#')[0] if server is not None else f'http://127.0.0.1:{port or 8780}/'
    return _feed.address(base, source=source, **options)


def on_batch_created(batch: Any) -> LiveSource | None:
    """Gives a new batch the live source that `CUJU_RENDER` asks for, and returns it.

    cuju calls this for every batch that it creates while `CUJU_RENDER` is set, and it is the one
    function of the renderer that cuju calls. `CUJU_RENDER` holds `on` for environment 0, or the
    index of the environment to show, and an index past the batch's count shows environment 0.
    A non-empty `CUJU_RENDER_BACKLOG` other than `0`, `off` or `no` makes the source read every
    step.

    Args:
        batch: The batch.

    Returns:
        The source, or `None` when the variable asks for none.
    """
    source = _live.from_environment(batch)
    if source is not None:
        batch.add_observer(source)
    return source


# The modules keep `cuju.render` as the module of the public names.
for _name in (
    PolicyError,
    Recorder,
    watch,
    on_batch_created,
    home,
    play,
    serve,
    LiveSource,
    add_team,
    show,
    View,
    challenge,
    challenges,
    feed_url,
):
    _name.__module__ = __name__
del _name
# The errors that only add the id of a message read as the public class they stand for.
_messages.public_names()


def __dir__() -> list[str]:
    """Returns the public names of the module, those of `__all__`."""
    return sorted(__all__)
