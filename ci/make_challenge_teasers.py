# Copyright 2026 The cuju Authors
# SPDX-License-Identifier: Apache-2.0
"""Makes the teaser videos and the stills of the challenges that the cards of the Play page show.

The teasers are fixed assets. This script rebuilds them only when run by hand, and CI never runs it.

For each challenge of the catalog the script plays attempts with the built-in AI on the whole left
side, on the seeds that `challenges.seeds` gives the challenge, its own attempts first and then
the seeds that follow, up to `--search` seeds. An attempt shows the challenge's goal met when it
counts by the challenge's own rule, and for a margin when the left side wins it, and when play
runs on from the start of its teaser to the goal without another restart, foul or goal, which the
page would caption in words. The first such attempt whose teaser lasts `SHORTEST` seconds or more
makes the teaser alone. A challenge whose attempts all end sooner, as a shot from close range
does, joins its first showing attempts one after the other, up to `LONGEST` seconds. Where no
attempt of the built-in AI shows the goal met, a scripted policy plays one player of dynamic
assignment on the same seeds, running at the ball and then at the goal and shooting in front of
it. Each chosen attempt plays again under `cuju.render.Recorder`, into a temporary home, and its
recording must score as the search did.

`cuju render video` then exports each attempt with the browser alone, the clean picture without
the scoreboard, the broadcast camera, 480 by 270 at 24 frames a second, H.264 in MP4 and silent,
from `BEFORE` seconds before the first goal of the left side to the goal, within the attempt,
so the page's caption of the goal stays out. ffmpeg joins the attempts of a teaser without coding
them again and writes the still, the last frame of a short export of the first moments of the
first attempt, which show the setup, in WebP. A teaser above `MAX_BYTES` is exported again at the
draft quality.

The files go to `src/cuju/render/web/assets/challenges/`, named after the challenge, with
`manifest.json`, which maps each challenge to its files with their SHA-256 and size and records
the policy, the seed, its place in the search, the goal and the range of each attempt chosen, so a
run with the same cuju and the same options makes the same choices.

Usage:
    python ci/make_challenge_teasers.py [--chrome PATH] [--ffmpeg PATH] [--only ID ...]
        [--search 40] [--software]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / 'src' / 'cuju' / 'render' / 'web' / 'assets' / 'challenges'
SIZE = (480, 270)
FPS = 24
# Each attempt of a teaser runs from this long before its goal to this long after it. A teaser
# ends on its goal, before the page captions the goal in words.
BEFORE, AFTER = 3.5, 0.0
# A teaser lasts at least SHORTEST seconds where its attempts allow and at most LONGEST.
SHORTEST, LONGEST = 3.0, 5.0
# The still is the last frame of the first STILL seconds of the first attempt.
STILL = 0.25
# A teaser keeps under this many bytes, and the still under STILL_BYTES.
MAX_BYTES = 250_000
STILL_BYTES = 60_000
# The quality of the WebP still, from 0 to 100.
WEBP_QUALITY = 80
SEARCH = 40
STEPS_PER_SECOND = 10
# The game mode and the foul of a frame, at their places in the head of a recording's frame.
MODE_AT, SCORE_AT, FOUL_AT = 4, 8, 68

# Actions of GRF's default action set.
IDLE, SHOT = 0, 12
# The directions of the default action set by the angle of the move, from +x in steps of 45
# degrees with y growing downward as GRF has it, right, bottom right, bottom, bottom left, left,
# top left, top and top right.
DIRECTIONS = (5, 6, 7, 8, 1, 2, 3, 4)


def scripted(observation):
    """Returns the action of a simple scripted policy from GRF's raw observation of its player.

    The player runs at the ball, and with the ball runs at the far goal and shoots from inside the
    box, in front of the goal.
    """
    x, y = observation['left_team'][observation['active']]
    ball = observation['ball']
    owned = observation['ball_owned_team'] == 0 and (
        observation['ball_owned_player'] == observation['active']
    )
    if owned and x > 0.7 and abs(y) < 0.2:
        return SHOT
    target = (1.0, 0.0) if owned else (ball[0], ball[1])
    dx, dy = target[0] - x, target[1] - y
    if math.hypot(dx, dy) < 1e-3:
        return IDLE
    return DIRECTIONS[round(math.atan2(dy, dx) / (math.pi / 4)) % 8]


def make_batch(spec, seed, agents):
    """Returns the batch of one attempt, as the challenge's own runs make it."""
    from cuju import BatchEnvironment

    ability = tuple(spec['ability'])
    return BatchEnvironment(
        f'{spec["scenario"]}_l{agents}_r0',
        agent_counts=[(agents, 0)],
        environment_count=1,
        representation='raw',
        seed=seed,
        auto_reset=False,
        device='cpu',
        difficulty=None if ability == (None, None) else [ability],
        action_set='default',
    )


def play(spec, seed, policy, keep=False):
    """Plays one attempt, and returns its frames or, when `keep`, its recording's path.

    Args:
        spec: The challenge, as `challenges.find` returns it.
        seed: The seed of the attempt.
        policy: `builtin` for the built-in AI on the whole left side, or `scripted`.
        keep: Whether the renderer's recorder saves the attempt.
    """
    import torch

    from cuju.kaggle import players_raw
    from cuju.render import Recorder
    from cuju.render._format import recording as _recording

    agents = 0 if policy == 'builtin' else 1
    batch = make_batch(spec, seed, agents)
    try:
        recorder = Recorder(batch, title=spec['title']) if keep else None
        reader = _recording.StateReader(int(batch.left_players[0] + batch.right_players[0]))
        batch.reset()
        frames = [reader.frame(batch.get_state(0))]
        done = False
        while not done:
            actions = torch.zeros((1, agents), dtype=torch.int32)
            if agents:
                actions[0, 0] = scripted(players_raw(batch, 0, 0)[0])
            _, _, finished, _ = batch.step(actions)
            done = bool(finished[0])
            frames.append(reader.frame(batch.get_state(0), 1 if done else 0))
        if recorder is not None:
            recorder.flush()
    finally:
        batch.close()
    if not keep:
        return frames
    if len(recorder.saved) != 1:
        raise RuntimeError(f'expected one recording of {spec["id"]}, found {recorder.saved}')
    return recorder.saved[0]


def shows_goal(spec, result):
    """Returns whether an attempt shows the challenge's goal met, by the challenge's own rule."""
    from cuju.render._playing import challenges as _challenges

    if spec['measure'] == 'margin':
        return result['scored'] and result['goals'][0] > result['goals'][1]
    return _challenges._counts(spec, result)


def teaser_range(goal, duration):
    """Returns the start and end of an attempt's part of a teaser, around its goal."""
    end = min(duration, goal + AFTER)
    start = max(0.0, goal - BEFORE)
    if end - start < SHORTEST:
        start = max(0.0, end - SHORTEST)
    return round(start, 2), round(end, 2)


def clean(frames, start, goal):
    """Returns whether play runs on from a teaser's start to its goal without another restart,
    foul or goal, since the page captions those in words.

    The restart that opens the attempt, such as its corner or kick off, counts as play.
    """

    def mode(frame):
        return struct.unpack_from('<i', frame, MODE_AT)[0]

    opening = next((index for index, frame in enumerate(frames) if not mode(frame)), len(frames))
    first, last = round(start * STEPS_PER_SECOND), round(goal * STEPS_PER_SECOND)
    score = struct.unpack_from('<2i', frames[first], SCORE_AT)
    for index in range(first, min(last, len(frames))):
        frame = frames[index]
        if index >= opening and mode(frame):
            return False
        if struct.unpack_from('<i', frame, FOUL_AT)[0]:
            return False
        if struct.unpack_from('<2i', frame, SCORE_AT) != score:
            return False
    return True


def choose(spec, search, log):
    """Returns the attempts a teaser shows, each with its policy, seed and range."""
    from cuju.render._playing import challenges as _challenges

    for policy in ('builtin', 'scripted'):
        short = []
        for index, seed in enumerate(_challenges.seeds(spec['id'], search)):
            frames = play(spec, seed, policy)
            result = _challenges.score_attempt({}, frames)
            if not shows_goal(spec, result):
                continue
            # The recording runs from its first frame to its last, as the export reads it.
            duration = (len(frames) - 1) / STEPS_PER_SECOND
            start, end = teaser_range(result['seconds'], duration)
            if not clean(frames, start, result['seconds']):
                continue
            attempt = {
                'policy': policy,
                'seed': seed,
                'search_index': index,
                'goal_seconds': result['seconds'],
                'goals': result['goals'],
                'start': start,
                'end': end,
            }
            if end - start >= SHORTEST - 1e-6:
                return [attempt]
            short.append(attempt)
        if short:
            chosen, total = [], 0.0
            for attempt in short:
                length = attempt['end'] - attempt['start']
                if chosen and total + length > LONGEST:
                    break
                chosen.append(attempt)
                total += length
                if total >= SHORTEST:
                    break
            return chosen
        log(f'{spec["id"]}: no attempt of the {policy} policy shows the goal met in {search} seeds')
    raise RuntimeError(f'expected an attempt of {spec["id"]} that shows its goal met, found none')


def export(chrome, source, output, start, end, quality, software):
    """Exports a range of a recording with `cuju render video` and returns the size written."""
    command = [
        sys.executable,
        '-m',
        'cuju.render',
        'video',
        str(source),
        '--output',
        str(output),
        '--format',
        'mp4',
        '--overwrite',
        '--start',
        f'{start:g}',
        '--end',
        f'{end:g}',
        '--camera',
        'broadcast',
        '--size',
        f'{SIZE[0]}x{SIZE[1]}',
        '--fps',
        str(FPS),
        '--quality',
        quality,
        '--no-score',
    ]
    if chrome:
        command += ['--chrome', chrome]
    if software:
        command.append('--software')
    subprocess.run(command, check=True, stdout=subprocess.DEVNULL)
    return output.stat().st_size


def join(ffmpeg, parts, output, work):
    """Joins the videos of several attempts into one without coding them again."""
    if len(parts) == 1:
        shutil.copyfile(parts[0], output)
        return
    listing = work / 'parts.txt'
    listing.write_text(''.join(f"file '{part.as_posix()}'\n" for part in parts), encoding='utf-8')
    subprocess.run(
        [
            *(ffmpeg, '-v', 'error', '-y', '-f', 'concat', '-safe', '0', '-i', str(listing)),
            *('-c', 'copy', '-map_metadata', '-1', '-movflags', '+faststart', str(output)),
        ],
        check=True,
    )


def still(ffmpeg, clip, output):
    """Writes the last frame of a clip as a WebP still with ffmpeg."""
    subprocess.run(
        [
            *(ffmpeg, '-v', 'error', '-y', '-sseof', '-0.1', '-i', str(clip), '-frames:v', '1'),
            *('-map_metadata', '-1', '-c:v', 'libwebp', '-quality', str(WEBP_QUALITY)),
            *('-compression_level', '6', str(output)),
        ],
        check=True,
    )
    return output.stat().st_size


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make(spec, attempts, args, work, log):
    """Records and exports the attempts of one challenge and returns its manifest entry."""
    from cuju.render._format import recording as _recording
    from cuju.render._playing import challenges as _challenges

    sources = []
    for attempt in attempts:
        source = play(spec, attempt['seed'], attempt['policy'], keep=True)
        again = _challenges.score_attempt({}, list(_recording.frames(source)))
        if again['goals'] != attempt['goals'] or again['seconds'] != attempt['goal_seconds']:
            raise RuntimeError(f'the recording of {spec["id"]} scores {again}, not {attempt}')
        sources.append(source)
    teaser = OUT / f'{spec["id"]}.mp4'
    for quality in ('standard', 'draft'):
        parts = []
        for number, (attempt, source) in enumerate(zip(attempts, sources, strict=True)):
            part = work / f'{spec["id"]}-{number}.mp4'
            span = (attempt['start'], attempt['end'])
            export(args.chrome, source, part, *span, quality, args.software)
            parts.append(part)
        join(args.ffmpeg, parts, teaser, work)
        size = teaser.stat().st_size
        if size <= MAX_BYTES:
            break
    clip = work / f'{spec["id"]}-still.mp4'
    export(args.chrome, sources[0], clip, 0.0, STILL, 'high', args.software)
    picture = OUT / f'{spec["id"]}.webp'
    still_size = still(args.ffmpeg, clip, picture)
    seconds = round(sum(attempt['end'] - attempt['start'] for attempt in attempts), 2)
    chosen = ', '.join(f'{attempt["policy"]} seed {attempt["seed"]}' for attempt in attempts)
    log(
        f'{spec["id"]}: {chosen}, {seconds} s, teaser {size} bytes at {quality}, '
        f'still {still_size} bytes'
    )
    if size > MAX_BYTES or still_size > STILL_BYTES:
        log(f'{spec["id"]}: above the size aimed at')
    return {
        'teaser': teaser.name,
        'teaser_sha256': digest(teaser),
        'teaser_bytes': size,
        'still': picture.name,
        'still_sha256': digest(picture),
        'still_bytes': still_size,
        'seconds': seconds,
        'quality': quality,
        'still_seconds': STILL,
        'attempts': attempts,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--chrome', help='the Chrome or Edge that draws and encodes the videos')
    parser.add_argument('--ffmpeg', default=shutil.which('ffmpeg'), help='the ffmpeg program')
    parser.add_argument('--only', nargs='+', help='make these challenges alone')
    parser.add_argument('--search', type=int, default=SEARCH, help='the seeds to try')
    parser.add_argument('--software', action='store_true', help='draw without the GPU')
    args = parser.parse_args()
    if not args.ffmpeg:
        sys.exit('ffmpeg joins the teasers and writes the stills, name it with --ffmpeg')
    work = Path(tempfile.mkdtemp(prefix='cuju-teasers-'))
    # The attempts go to a home of their own, which leaves the person's library alone.
    os.environ['CUJU_RENDER_HOME'] = str(work / 'home')
    from cuju import __version__ as cuju_version
    from cuju.render._playing import challenges as _challenges

    def log(text):
        print(text, flush=True)

    manifest_path = OUT / 'manifest.json'
    entries = {}
    if manifest_path.is_file():
        entries = json.loads(manifest_path.read_text(encoding='utf-8')).get('challenges', {})
    catalog = _challenges.challenges()
    known = [spec['id'] for spec in catalog]
    if args.only and set(args.only) - set(known):
        sys.exit(f'unknown challenges {sorted(set(args.only) - set(known))}')
    OUT.mkdir(parents=True, exist_ok=True)
    try:
        for spec in catalog:
            if not args.only or spec['id'] in args.only:
                entries[spec['id']] = make(spec, choose(spec, args.search, log), args, work, log)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    manifest = {
        'version': 1,
        'generator': 'ci/make_challenge_teasers.py',
        'cuju': cuju_version,
        'size': list(SIZE),
        'fps': FPS,
        'camera': 'broadcast',
        'search': args.search,
        'challenges': {name: entries[name] for name in known if name in entries},
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8', newline='\n')
    total = sum(e['teaser_bytes'] + e['still_bytes'] for e in manifest['challenges'].values())
    log(f'wrote {len(manifest["challenges"])} teasers and stills, {total} bytes in all')


if __name__ == '__main__':
    main()
