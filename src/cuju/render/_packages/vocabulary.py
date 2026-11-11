# Copyright 2026 The cuju Authors
# SPDX-License-Identifier: Apache-2.0

"""The vocabulary of team presentation packages, events, reflexes, effects, sound and features.

Section 4 of the contract lists the events a package reacts to, section 11 the reflexes and
commands that answer them. Effects, lights, shaders, post, sound, music, environment moments,
camera and time suggestions and overlay slots grow with later renderer work, so their names and
shapes live here, apart from the stable core of `_presentation`, and the page keeps the same lists
in `web/js/presentation/commands.js` and `catalog.js`.
"""

from __future__ import annotations

import difflib
import re
from typing import Any

from cuju.errors import ArgumentError

# The events of the catalog, read from frames, inferred, of the show and of the transport.
FRAME_EVENTS = (
    'touch',
    'action.begin',
    'action.end',
    'possession',
    'goal',
    'restart.begin',
    'restart.taken',
    'foul',
    'card',
    'sentOff',
    'onPitch',
    'offside',
    'control',
    'episode.begin',
    'episode.end',
    'halftime',
    'fulltime',
)
INFERRED_EVENTS = (
    'pass',
    'shot',
    'header',
    'volley',
    'slide',
    'save',
    'catch',
    'deflection',
    'block',
    'woodwork',
    'nearMiss',
    'sprint.begin',
    'sprint.end',
    'dribble.begin',
    'dribble.end',
)
PRESENTATION_EVENTS = (
    'lineup.begin',
    'lineup.end',
    'celebration.begin',
    'celebration.end',
    'reaction.begin',
    'reaction.end',
    'replay.begin',
    'replay.end',
    'mvp.reveal',
    'winner.reveal',
    'appearance',
    'entity.remove',
)
TRANSPORT_EVENTS = ('seek', 'pause', 'play', 'speed', 'reverse', 'reducedMotion')
EVENTS = FRAME_EVENTS + INFERRED_EVENTS + PRESENTATION_EVENTS + TRANSPORT_EVENTS
PHASES = ('forecast', 'occur', 'resolve')
TEAMS = ('self', 'opponent', 'any')

# The features a package may require or prefer, those this renderer implements first.
FEATURES = (
    'drivers.grf',
    'drivers.team',
    'drivers.worker',
    'lookahead',
    'lookahead.outcomes',
    'inference.pass/1',
    'inference.shot/1',
    'inference.header/1',
    'inference.volley/1',
    'inference.slide/1',
    'inference.save/1',
    'inference.goal/1',
    'inference.sprint/1',
    'inference.dribble/1',
    'clips.markers',
    'drivers.grf+layers',
    'bend.ball',
    'ik.fabrik',
    'shader.custom',
    'shader.sceneColor',
    'post.layer',
    'post.fullscreen',
    'geometry.worker',
    'overlay.offscreen',
    'audio.worklet',
    'audio.music',
    'camera.suggest',
    'time.suggest',
    'environment.sky',
    'environment.lightning',
    'fans.tifo',
)
# Features of the contract still to come, none since contract 1.1.
PLANNED: tuple[str, ...] = ()
# The features a worker alone uses, whose lack drops the worker and keeps the manifest.
WORKER_FEATURES = ('drivers.worker', 'geometry.worker', 'overlay.offscreen')
_FEATURE = re.compile(r'[a-z][a-z0-9]*(\.[A-Za-z0-9_+/]+)*')

ACTIONS = (
    'audio',
    'effect',
    'clip',
    'behaviour',
    'claim',
    'camera',
    'time',
    'overlay',
    'environment',
    'music',
)
CLASSES = ('moment', 'action', 'bed')
BUSES = ('effects', 'fans', 'music', 'voice')
REPLAY = ('repeat', 'quiet', 'skip')
CLAIMS = ('ball', 'goal', 'sky', 'floodlights', 'fans')
SLOTS = ('badge', 'lowerThird', 'sting', 'card', 'lineup')
SHOTS = ('closeup', 'orbit', 'low', 'behindBall', 'path')
_ATTACH = re.compile(r'ball|path|world|self|socket:[A-Za-z0-9_]{1,40}')
_NAME = re.compile(r'[A-Za-z0-9_.-]{1,40}')

MAXIMUM_REFLEXES = 64
MAXIMUM_ACTIONS = 8


def features(value: Any, name: str) -> list[str]:
    """Checks a list of feature names, the requires or prefers of a manifest."""
    if not isinstance(value, list) or len(value) > 64:
        raise ArgumentError(f'expected {name} as a list of at most 64 feature names')
    for item in value:
        if not isinstance(item, str) or len(item) > 60 or not _FEATURE.fullmatch(item):
            raise ArgumentError(f'expected a feature name in {name}, found {item!r}')
    return list(value)


def _name(value: Any, what: str) -> str:
    if not isinstance(value, str) or not _NAME.fullmatch(value):
        raise ArgumentError(f'expected {what} of up to 40 letters, digits, dots and underscores')
    return value


_IMAGES = ('.png', '.jpg', '.webp', '.ktx2')
_SOUNDS = ('.ogg', '.mp3', '.wav')
EFFECT_TYPES = ('particles', 'trail', 'decal', 'light', 'mesh', 'post')
PASSES = ('glow', 'outline', 'pixelate', 'tint', 'chromatic', 'blur', 'custom')
BLENDS = ('additive', 'normal')
MAXIMUM_LIGHTS = 16
MAXIMUM_PROCESSORS = 4


def _real(value: Any, low: float, high: float, what: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not low <= value <= high:
        raise ArgumentError(f'expected {what} from {low} to {high}, found {value!r}')
    return float(value)


def _pair(value: Any, low: float, high: float, what: str) -> list[float]:
    """Checks a number or a pair of numbers, a start and an end or a least and a most."""
    items = value if isinstance(value, list) else [value, value]
    if len(items) != 2:
        raise ArgumentError(f'expected {what} as a number or two')
    return [_real(v, low, high, what) for v in items]


def _rgb(value: Any, what: str) -> list[int]:
    if (
        not isinstance(value, list)
        or len(value) != 3
        or not all(isinstance(c, int) and not isinstance(c, bool) and 0 <= c <= 255 for c in value)
    ):
        raise ArgumentError(f'expected {what} as three integers from 0 to 255')
    return list(value)


def _colors(value: Any, what: str) -> list[list[int]]:
    """Checks one colour or a start and an end colour."""
    if isinstance(value, list) and value and isinstance(value[0], list):
        if len(value) != 2:
            raise ArgumentError(f'expected {what} as one colour or two')
        return [_rgb(value[0], what), _rgb(value[1], what)]
    color = _rgb(value, what)
    return [color, list(color)]


# The ranges of the numeric fields of each type of effect, the lowest, the highest and whether a
# field takes a pair, a start and an end or a least and a most.
_RANGES: dict[str, dict[str, tuple[float, float, bool]]] = {
    'particles': {
        'count': (1, 2000, False),
        'rate': (0, 5000, False),
        'life': (0.05, 10, True),
        'speed': (0, 60, True),
        'spread': (0, 3.15, False),
        'gravity': (-30, 30, False),
        'drag': (0, 20, False),
        'size': (0, 2, True),
    },
    'trail': {'length': (0.05, 3, False), 'width': (0, 2, True), 'segments': (4, 64, False)},
    'decal': {'size': (0.1, 3.16, False), 'fade': (0.5, 10, False), 'opacity': (0, 0.7, True)},
    'light': {
        'intensity': (0, 50, False),
        'distance': (0.5, 30, False),
        'decay': (0, 2, False),
        'attack': (0, 5, False),
        'release': (0, 10, False),
        'duration': (0.05, 30, False),
    },
    'mesh': {'scale': (0.01, 10, False), 'spin': (-50, 50, False), 'fade': (0, 10, False)},
    'post': {'strength': (0, 4, False)},
}
_COMMON = {'type', 'file', 'texture', 'shader', 'blend', 'color', 'opacity', 'duration'}
_EXTRA = {
    'particles': {'direction'},
    'decal': {'life', 'rotation'},
    'post': {'pass', 'scope'},
}


def _effect(key: str, spec: dict[str, Any], file: Any) -> tuple[dict[str, Any], set[str]]:
    """Checks one effect of a type of contract 1.1 and returns it with the fields it knows."""
    kind = spec['type']
    what = f'effect {key}'
    out: dict[str, Any] = {'type': kind}
    if 'texture' in spec:
        out['texture'] = file(spec['texture'], f'the texture of {what}', _IMAGES)
    if 'shader' in spec:
        out['shader'] = file(spec['shader'], f'the shader of {what}', ('.glsl',))
    if 'blend' in spec:
        if spec['blend'] not in BLENDS:
            raise ArgumentError(f'expected the blend of {what} among {BLENDS}')
        out['blend'] = spec['blend']
    if 'color' in spec:
        out['color'] = _colors(spec['color'], f'the colour of {what}')
    if 'opacity' in spec:
        out['opacity'] = _pair(spec['opacity'], 0, 1, f'the opacity of {what}')
    if 'duration' in spec:
        out['duration'] = _real(spec['duration'], 0, 30, f'the duration of {what}')
    for name, (low, high, pair) in _RANGES[kind].items():
        if name in spec:
            check = _pair if pair else _real
            out[name] = check(spec[name], low, high, f'the {name} of {what}')
    if kind == 'particles' and 'direction' in spec:
        direction = spec['direction']
        if not isinstance(direction, list) or len(direction) != 3:
            raise ArgumentError(f'expected the direction of {what} as three numbers')
        out['direction'] = [_real(v, -1e3, 1e3, 'a direction') for v in direction]
    elif kind == 'decal':
        life = spec.get('life', 8)
        out['life'] = life if life == 'half' else _real(life, 0.5, 600, f'the life of {what}')
        rotation = spec.get('rotation', 'random')
        out['rotation'] = rotation if rotation == 'random' else _real(rotation, -360, 360, 'a turn')
    elif kind == 'mesh':
        out['file'] = file(spec.get('file'), f'the model of {what}', ('.glb',))
    elif kind == 'post':
        if spec.get('pass') not in PASSES:
            raise ArgumentError(f'expected the pass of {what} among {PASSES}')
        out['pass'] = spec['pass']
        out['scope'] = spec.get('scope', 'layer')
        if out['scope'] not in ('layer', 'fullscreen'):
            raise ArgumentError(f'expected the scope of {what} as layer or fullscreen')
        if out['pass'] == 'custom' and 'shader' not in out:
            raise ArgumentError(f'expected the shader of the custom pass of {what}')
        if out['scope'] == 'fullscreen':
            out['duration'] = min(out.get('duration', 1.5), 3.0)
    return out, _COMMON | set(_RANGES[kind]) | _EXTRA.get(kind, set())


def effects(value: Any, file: Any, warnings: list[str]) -> dict[str, Any]:
    """Checks the effects of a manifest, each a type, its fields and the package files it names.

    The types of contract 1.1 are particles, trail, decal, light, mesh and post. An effect of
    another type stays as it is for a later renderer, which this one counts and leaves undrawn.
    """
    if not isinstance(value, dict) or len(value) > 64:
        raise ArgumentError('expected effects as a mapping of at most 64 names')
    out = {}
    for key, spec in value.items():
        _name(key, 'the name of an effect')
        if not isinstance(spec, dict) or not isinstance(spec.get('type'), str):
            raise ArgumentError(f'expected effect {key} with a type')
        try:
            if spec['type'] not in EFFECT_TYPES:
                item = dict(spec)
                if 'file' in spec:
                    item['file'] = file(spec['file'], f'effect {key}')
                warnings.append(f'effect {key} of type {spec["type"]} waits for a later renderer')
                out[key] = item
                continue
            item, known = _effect(key, spec, file)
            warnings.extend(f'effect {key} ignores {k}' for k in sorted(set(spec) - known))
            out[key] = item
        except ArgumentError as error:
            warnings.append(f'effect {key} left out, {error}')
    return out


def lights(value: Any, sockets: dict[str, Any], warnings: list[str]) -> dict[str, Any]:
    """Checks the lights of a manifest, persistent lights on the sockets of the team's players."""
    if not isinstance(value, dict) or len(value) > MAXIMUM_LIGHTS:
        raise ArgumentError(f'expected lights as a mapping of at most {MAXIMUM_LIGHTS} names')
    out = {}
    known = {'socket', 'offset', 'color', 'intensity', 'distance', 'decay', 'kind', 'when'}
    for key, spec in value.items():
        try:
            _name(key, 'the name of a light')
            if not isinstance(spec, dict):
                raise ArgumentError('expected a description')
            socket = spec.get('socket', 'root')
            if socket != 'root' and socket not in sockets:
                raise ArgumentError('expected a socket of the rig')
            offset = spec.get('offset', [0, 0, 0])
            if not isinstance(offset, list) or len(offset) != 3:
                raise ArgumentError('expected the offset as three numbers')
            kind = spec.get('kind', 'local')
            if kind not in ('pool', 'local'):
                raise ArgumentError('expected the kind of a light as pool or local')
            item = {
                'socket': socket,
                'offset': [_real(v, -10, 10, 'an offset') for v in offset],
                'color': _rgb(spec.get('color', [255, 255, 255]), 'the colour of a light'),
                'intensity': _real(spec.get('intensity', 1), 0, 50, 'the intensity of a light'),
                'distance': _real(spec.get('distance', 4), 0.5, 30, 'the distance of a light'),
                'decay': _real(spec.get('decay', 2), 0, 2, 'the decay of a light'),
                'kind': kind,
            }
            if 'when' in spec:
                item['when'] = spec['when']
            warnings.extend(f'light {key} ignores {k}' for k in sorted(set(spec) - known))
            out[key] = item
        except ArgumentError as error:
            warnings.append(f'light {key} left out, {error}')
    return out


def post(value: Any, file: Any) -> dict[str, Any]:
    """Checks the post section, a persistent pass on the team's own layer."""
    if not isinstance(value, dict) or set(value) - {'layer'}:
        raise ArgumentError('expected post to hold a layer')
    spec = value.get('layer')
    if not isinstance(spec, dict) or spec.get('pass') not in PASSES:
        raise ArgumentError(f'expected the layer pass among {PASSES}')
    out: dict[str, Any] = {'pass': spec['pass']}
    if 'shader' in spec:
        out['shader'] = file(spec['shader'], 'the shader of the layer pass', ('.glsl',))
    elif spec['pass'] == 'custom':
        raise ArgumentError('expected the shader of the custom layer pass')
    if 'color' in spec:
        out['color'] = _rgb(spec['color'], 'the colour of the layer pass')
    out['strength'] = _real(spec.get('strength', 1), 0, 4, 'the strength of the layer pass')
    return {'layer': out}


def overlays(value: Any) -> dict[str, Any]:
    """Checks the overlay slots a worker draws in, each among the renderer's reserved slots."""
    if not isinstance(value, dict) or not set(value) <= set(SLOTS):
        raise ArgumentError(f'expected overlays among the slots {SLOTS}')
    return {slot: {} for slot in value}


def _music(key: str, spec: Any, file: Any) -> dict[str, Any]:
    _name(key, 'the name of music')
    stems = spec.get('stems') if isinstance(spec, dict) else None
    if isinstance(stems, dict):
        raise ArgumentError(
            f'expected the stems of music {key} as a list of files, found a mapping, and a music '
            'action picks stems by their places in that list from 0'
        )
    if not isinstance(stems, list) or not 0 < len(stems) <= 16:
        raise ArgumentError(f'expected music {key} with one to sixteen stems')
    return {
        'stems': [file(s, f'music {key}', _SOUNDS) for s in stems],
        'bpm': _real(spec.get('bpm', 120), 20, 300, f'the bpm of music {key}'),
        'beats': int(_real(spec.get('beats', 4), 1, 16, f'the beats of music {key}')),
        'gain': _real(spec.get('gain', 1), 0, 1, f'the gain of music {key}'),
    }


def _processor(key: str, spec: Any) -> dict[str, Any]:
    _name(key, 'the name of a processor')
    if not isinstance(spec, dict) or not isinstance(spec.get('processor'), str):
        raise ArgumentError(f'expected processor {key} to name a registered processor')
    parameters = spec.get('parameters', {})
    if not isinstance(parameters, dict) or len(parameters) > 32:
        raise ArgumentError(f'expected the parameters of processor {key} as a mapping')
    bus = spec.get('bus', 'effects')
    if bus not in BUSES:
        raise ArgumentError(f'expected the bus of processor {key} among {BUSES}')
    options = spec.get('options', {})
    return {
        'processor': _name(spec['processor'], 'a processor name'),
        'bus': bus,
        'parameters': {
            _name(k, 'a parameter'): _real(v, -1e6, 1e6, 'a parameter')
            for k, v in parameters.items()
        },
        'options': options if isinstance(options, dict) else {},
    }


def audio(value: Any, file: Any, warnings: list[str]) -> dict[str, Any]:
    """Checks the audio of a manifest, its cues, music, worklet and processors."""
    if not isinstance(value, dict):
        raise ArgumentError('expected audio as a mapping')
    out: dict[str, Any] = {}
    cues = value.get('cues', {})
    if not isinstance(cues, dict) or len(cues) > 64:
        raise ArgumentError('expected the cues of audio as a mapping of at most 64 names')
    out['cues'] = {}
    for key, files in cues.items():
        _name(key, 'the name of a cue')
        files = files if isinstance(files, list) else [files]
        if not 0 < len(files) <= 16:
            raise ArgumentError(f'expected one to sixteen files of cue {key}')
        out['cues'][key] = [file(item, f'cue {key}', _SOUNDS) for item in files]
    music = value.get('music', {})
    if not isinstance(music, dict) or len(music) > 16:
        raise ArgumentError('expected music as a mapping of at most 16 names')
    out['music'] = {}
    for key, spec in music.items():
        try:
            out['music'][key] = _music(key, spec, file)
        except ArgumentError as error:
            warnings.append(f'music {key} left out, {error}')
    if 'worklet' in value:
        out['worklet'] = file(value['worklet'], 'the worklet', ('.js',))
    processors = value.get('processors', {})
    if not isinstance(processors, dict) or len(processors) > MAXIMUM_PROCESSORS:
        raise ArgumentError(f'expected at most {MAXIMUM_PROCESSORS} processors')
    out['processors'] = {}
    for key, spec in processors.items():
        try:
            if 'worklet' not in out:
                raise ArgumentError('expected the worklet module of the processors')
            out['processors'][key] = _processor(key, spec)
        except ArgumentError as error:
            warnings.append(f'processor {key} left out, {error}')
    for key in sorted(set(value) - {'cues', 'music', 'worklet', 'processors'}):
        warnings.append(f'audio ignores {key}')
    return out


# The parts of an environment moment and the feature each needs.
ENVIRONMENT = {
    'sky': 'environment.sky',
    'floodlights': 'environment.sky',
    'fog': 'environment.sky',
    'lightning': 'environment.lightning',
    'tifo': 'fans.tifo',
}


def environment(value: Any, what: str) -> dict[str, Any]:
    """Checks an environment moment of a reflex or a worker, brief and on the team's own event."""
    if (
        not isinstance(value, dict)
        or not set(value) <= {*ENVIRONMENT, 'duration'}
        or not set(value) & set(ENVIRONMENT)
    ):
        raise ArgumentError(f'expected the environment of {what} among {tuple(ENVIRONMENT)}')
    out: dict[str, Any] = {'duration': _real(value.get('duration', 4), 0.3, 6, 'a duration')}
    for key in ('sky', 'floodlights', 'fog'):
        if key in value:
            part = value[key]
            if not isinstance(part, dict):
                raise ArgumentError(f'expected the {key} of {what} as a description')
            out[key] = {
                'color': _rgb(part.get('tint', part.get('color', [255, 255, 255])), 'a colour'),
                'amount': _real(part.get('amount', part.get('level', 1)), 0, 1.5, 'an amount'),
            }
    if 'lightning' in value:
        part = value['lightning']
        target = part.get('target', 'goal') if isinstance(part, dict) else 'goal'
        if target not in ('goal', 'ball') and not (isinstance(target, list) and len(target) == 3):
            raise ArgumentError(f'expected the lightning of {what} at the goal or the ball')
        out['lightning'] = {'target': target}
    if 'tifo' in value:
        if not isinstance(value['tifo'], str):
            raise ArgumentError(f'expected the tifo of {what} to name an image of the package')
        out['tifo'] = value['tifo']
    return out


def _time(value: Any, what: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ArgumentError(f'expected the time of {what} as a description')
    out: dict[str, Any] = {'freeze': _real(value.get('freeze', 0), 0, 0.3, 'a freeze')}
    if 'slow' in value:
        slow = value['slow']
        if not isinstance(slow, dict):
            raise ArgumentError(f'expected the slow motion of {what} as a description')
        out['slow'] = {
            'speed': _real(slow.get('speed', 0.5), 0.25, 1, 'a slow motion speed'),
            'seconds': _real(slow.get('seconds', 1), 0, 1.5, 'a slow motion length'),
        }
    return out


def _action(action: Any, index: int, names: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(action, dict) or not any(key in action for key in ACTIONS):
        raise ArgumentError(f'expected action {index} to name one of {ACTIONS}')
    out = dict(action)
    if 'audio' in action and action['audio'] not in names.get('cues', {}):
        raise ArgumentError(
            f'expected action {index} to play a cue of the audio, found {action["audio"]!r}, '
            f'{_among(names.get("cues", {}), "cues")}'
        )
    if 'effect' in action and action['effect'] not in names.get('effects', {}):
        raise ArgumentError(
            f'expected action {index} to start an effect of the manifest, found '
            f'{action["effect"]!r}, {_among(names.get("effects", {}), "effects")}'
        )
    if 'clip' in action and not isinstance(action['clip'], str):
        raise ArgumentError(f'expected action {index} to name a clip role')
    if 'claim' in action and action['claim'] not in CLAIMS:
        raise ArgumentError(f'expected the claim of action {index} among {CLAIMS}')
    if 'attach' in action and not (
        isinstance(action['attach'], str) and _ATTACH.fullmatch(action['attach'])
    ):
        raise ArgumentError(f'expected action {index} to attach to the ball, a socket or self')
    for key, choices in (('class', CLASSES), ('bus', BUSES), ('replay', REPLAY)):
        if key in action and action[key] not in choices:
            raise ArgumentError(f'expected the {key} of action {index} among {choices}')
    if 'overlay' in action and action['overlay'] not in SLOTS:
        raise ArgumentError(f'expected the overlay of action {index} among {SLOTS}')
    if 'camera' in action and (
        not isinstance(action['camera'], dict) or action['camera'].get('shot') not in SHOTS
    ):
        raise ArgumentError(f'expected the camera of action {index} to suggest one of {SHOTS}')
    if 'gain' in action:
        gain = action['gain']
        if isinstance(gain, bool) or not isinstance(gain, (int, float)) or not 0 <= gain <= 1:
            raise ArgumentError(f'expected the gain of action {index} from 0 to 1')
    if 'environment' in action:
        out['environment'] = environment(action['environment'], f'action {index}')
        tifo = out['environment'].get('tifo')
        if tifo is not None and tifo not in names.get('files', ()):
            raise ArgumentError(f'expected the tifo of action {index} to name an image')
    if 'time' in action:
        out['time'] = _time(action['time'], f'action {index}')
    if 'music' in action and action['music'] not in names.get('music', {}):
        raise ArgumentError(
            f'expected action {index} to play music of the audio, found {action["music"]!r}, '
            f'{_among(names.get("music", {}), "music")}'
        )
    return out


def _among(names: Any, what: str) -> str:
    """Returns the end of a message that names what a manifest holds, or that it holds none."""
    names = sorted(str(name) for name in names)
    if not names:
        return f'and the manifest keeps no {what}'
    shown = ', '.join(names[:8]) + (f' and {len(names) - 8} more' if len(names) > 8 else '')
    return f'the {what} are {shown}'


def _event(value: Any) -> str:
    """Returns the end of a message for a reflex on an event outside the catalog."""
    near = difflib.get_close_matches(value, EVENTS, 1, 0.5) if isinstance(value, str) else []
    hint = f', the nearest is {near[0]}' if near else ''
    return f'found {value!r}{hint}, and the section Events of docs/presentation.md lists them'


def reflexes(value: Any, names: dict[str, Any], warnings: list[str]) -> list[dict[str, Any]]:
    """Checks the reflexes of a manifest, each an event, a filter and the actions it starts."""
    if not isinstance(value, list) or len(value) > MAXIMUM_REFLEXES:
        raise ArgumentError(f'expected reflexes as a list of at most {MAXIMUM_REFLEXES}')
    out = []
    # Reflexes and their actions count from 1 in messages, as an author counts them.
    for index, spec in enumerate(value, 1):
        try:
            if not isinstance(spec, dict) or spec.get('on') not in EVENTS:
                found = _event(spec.get('on') if isinstance(spec, dict) else spec)
                raise ArgumentError(f'expected reflex {index} on an event of the catalog, {found}')
            item: dict[str, Any] = {'on': spec['on'], 'phase': spec.get('phase', 'occur')}
            if item['phase'] not in PHASES:
                raise ArgumentError(f'expected the phase of reflex {index} among {PHASES}')
            where = spec.get('where', {})
            if not isinstance(where, dict) or where.get('team', 'self') not in TEAMS:
                raise ArgumentError(f'expected reflex {index} to filter its team among {TEAMS}')
            item['where'] = {'team': where.get('team', 'self')}
            if where.get('role') in ('goalkeeper', 'outfield'):
                item['where']['role'] = where['role']
            if 'player' in where:
                item['where']['player'] = where['player']
            actions = spec.get('do')
            if not isinstance(actions, list) or not 0 < len(actions) <= MAXIMUM_ACTIONS:
                raise ArgumentError(f'expected one to {MAXIMUM_ACTIONS} actions in reflex {index}')
            item['do'] = [_action(action, i, names) for i, action in enumerate(actions, 1)]
            out.append(item)
        except ArgumentError as error:
            warnings.append(f'reflex {index} left out, {error}')
    return out
