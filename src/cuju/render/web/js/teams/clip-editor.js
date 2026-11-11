// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// The team editor's part for celebration clips, the list of a team's clips under Celebrations,
// their upload and removal, which save at once as sounds do, and the joint mapping of each clip.
// The animations of the clips join the moves of the section, where Play previews them on the
// team's model, and the roster, where a player may take one as his own.

import { api, formatBytes } from '../core/api.js';
import {
    MAX_CLIPS, MAX_CLIP_BYTES, MAX_TEAM_CLIP_BYTES, clipNameOf, loadTeamClips, qualify, readClip,
    uploadMoveLabel, uploadMoves,
} from '../players/clips.js';
import { NODE_NAMES } from '../recording/format.js';
import { h } from './library.js';
import { uploadDuration } from '../players/retarget.js';
import { t, tn } from '../core/i18n.js';
import { icon, symbolOnly } from '../core/icons.js';

// The moves a team's clips add, by their names in the style.
export function clipMoves(editor) {
    return uploadMoves(editor.team).map(([value]) => value);
}

// The animation's name of a move of a clip, or null for another move.
export function clipMoveLabel(editor, value) {
    return uploadMoveLabel(editor.team, value);
}

// What the preview plays for a move, the loaded clip's own name for a move of a clip, and how long
// it plays, a clip at least once up to 15 seconds.
export function previewMove(editor, value) {
    const pose = qualify(value, editor.clipTag);
    const span = uploadDuration(pose);
    return { pose, length: span > 0 ? Math.min(15, Math.max(5, span)) : 5 };
}

// Loads the clips of the team that the editor opened, then shows their moves.
export async function openClips(editor, token = editor.token) {
    editor.clipTag = null;
    const team = editor.team;
    if (!team || !Array.isArray(team.clips) || !team.clips.length) {
        return;
    }
    const tag = await loadTeamClips(team);
    if (token === editor.token && editor.team === team) {
        editor.clipTag = tag;
        refresh(editor);
    }
}

function refresh(editor) {
    const clean = !editor.dirty;
    editor.invalidate('celebrations', 'roster');
    // A clip saves at once, so the editor's own changes stay as they were.
    if (clean) {
        editor.initial = editor.snapshot();
        editor.markDirty();
    }
}

function message(editor, text, kind = 'info') {
    const el = editor.dialog.querySelector('.clip-message');
    if (el) {
        el.textContent = text;
        el.dataset.kind = kind;
    }
}

// Uploads a clip from a file the user picked or dropped, a new clip or one of the same name.
export async function uploadClip(editor, file) {
    if (!file) {
        return false;
    }
    const team = editor.team;
    const token = editor.token;
    const clips = Array.isArray(team.clips) ? team.clips : [];
    const name = clipNameOf(file.name);
    const others = clips.filter((c) => c.name !== name);
    const fail = (text) => {
        message(editor, text, 'error');
        editor.app.hud.toast(text, 'error', 7000);
        return false;
    };
    if (!/\.glb$/i.test(file.name)) {
        return fail(t('clip-editor.wrongType'));
    }
    if (file.size > MAX_CLIP_BYTES) {
        return fail(t('clip-editor.tooLarge', { size: formatBytes(file.size) }));
    }
    if (others.length >= MAX_CLIPS) {
        return fail(t('clip-editor.tooMany', { max: MAX_CLIPS }));
    }
    if (others.reduce((sum, c) => sum + c.bytes, 0) + file.size > MAX_TEAM_CLIP_BYTES) {
        return fail(t('clip-editor.tooMuch'));
    }
    let read;
    let bytes;
    try {
        bytes = await file.arrayBuffer();
        read = await readClip(bytes);
    } catch (err) {
        return fail(t('clip-editor.unusable', { reason: String(err.message || err).replace(/\.$/, '') }));
    }
    try {
        const entry = await api.putClip(team.id, name, read.guess, bytes);
        if (token !== editor.token) {
            return false;
        }
        team.clips = entry.clips;
        editor.clipTag = await loadTeamClips(team);
    } catch (err) {
        return fail(err.message || String(err));
    }
    if (token !== editor.token) {
        return false;
    }
    refresh(editor);
    const count = read.gltf.animations.length;
    const text = read.guess.body
        ? t('clip-editor.saved', { file: file.name, count })
        : t('clip-editor.savedUnmapped', { file: file.name });
    message(editor, text, read.guess.body ? 'info' : 'error');
    editor.app.hud.toast(text);
    if (read.guess.body) {
        editor.playCelebration(`upload:${name}.0`);
    }
    return true;
}

// Removes a clip after asking, with the team's choices of its animations.
export async function removeClip(editor, name) {
    if (!confirm(t('clip-editor.removeConfirm', { name }))) {
        return;
    }
    const team = editor.team;
    const token = editor.token;
    try {
        await api.deleteClip(team.id, name);
    } catch (err) {
        editor.app.hud.toast(err.message || String(err), 'error');
        return;
    }
    if (token !== editor.token) {
        return;
    }
    const clean = !editor.dirty;
    // The server took the clip's moves out of the saved style, the editor's copy follows.
    const gone = (v) => typeof v === 'string' && v.startsWith(`upload:${name}.`);
    const s = editor.style;
    s.celebrations = s.celebrations.filter((v) => !gone(v));
    for (const p of s.players) {
        if (gone(p.celebration)) {
            p.celebration = 'team';
        }
    }
    if (team.style) {
        team.style.celebrations = (team.style.celebrations || []).filter((v) => !gone(v));
    }
    team.clips = (team.clips || []).filter((c) => c.name !== name);
    editor.clipTag = await loadTeamClips(team);
    if (token !== editor.token) {
        return;
    }
    editor.invalidate('celebrations', 'roster');
    if (clean) {
        editor.initial = editor.snapshot();
        editor.markDirty();
    }
    editor.app.hud.toast(t('clip-editor.removed', { name }));
}

// The table that maps the joints of GRF's skeleton to the bones of a clip, read when opened.
function mappingTable(editor, clip, host) {
    const token = editor.token;
    host.replaceChildren(h('p', { class: 'muted small' }, t('clip-editor.reading')));
    (async () => {
        let read;
        try {
            read = await readClip(await api.clipBytes(editor.team.id, clip.name));
        } catch (err) {
            host.replaceChildren(h('p', { class: 'muted small' }, t('clip-editor.readFailed', { reason: err.message || err })));
            return;
        }
        if (token !== editor.token || !host.isConnected) {
            return;
        }
        const joints = { ...(clip.joints && clip.joints.body ? clip.joints : read.guess) };
        const status = h('span', { class: 'req' });
        const showStatus = () => {
            status.textContent = ` ${joints.body ? t('editor.joints.required') : t('editor.joints.requiredPelvis')}`;
        };
        showStatus();
        const rows = NODE_NAMES.map((node) => {
            const select = h('select', { 'aria-label': t('clip-editor.boneOf', { node: t(`editor.joints.node.${node}`) }) },
                h('option', { value: '' }, node === 'player' ? t('editor.joints.root') : t('editor.joints.unmapped')),
                read.bones.map((b) => h('option', { value: b, selected: joints[node] === b }, b)));
            select.addEventListener('change', () => {
                if (select.value) {
                    joints[node] = select.value;
                } else {
                    delete joints[node];
                }
                showStatus();
            });
            return h('tr', {}, h('td', {}, t(`editor.joints.node.${node}`), node === 'body' ? status : null), h('td', {}, select));
        });
        const save = async (mapping) => {
            try {
                const entry = await api.clipJoints(editor.team.id, clip.name, mapping);
                if (token !== editor.token) {
                    return;
                }
                editor.team.clips = entry.clips;
                editor.clipTag = await loadTeamClips(editor.team);
                if (token !== editor.token) {
                    return;
                }
                refresh(editor);
                editor.app.hud.toast(t('clip-editor.mappingSaved', { name: clip.name }));
            } catch (err) {
                editor.app.hud.toast(err.message || String(err), 'error', 7000);
            }
        };
        host.replaceChildren(
            h('p', { class: 'muted small' }, tn('clip-editor.mappingNote')),
            h('table', {}, h('tbody', {}, rows)),
            h('div', { class: 'row' },
                h('button', {
                    type: 'button',
                    class: 'btn small',
                    ...symbolOnly(t('clip-editor.saveMapping')),
                    onclick: () => {
                        if (!joints.body) {
                            editor.app.hud.toast(t('clip-editor.needPelvis'), 'error');
                            return;
                        }
                        save(joints);
                    },
                }, icon('save')),
                h('button', { type: 'button', class: 'btn small ghost', onclick: () => save({}) }, t('clip-editor.mapByNames'))));
    })();
}

// The part of the Celebrations section that lists and uploads the team's clips.
export function clipsPanel(editor) {
    const clips = Array.isArray(editor.team.clips) ? editor.team.clips : [];
    const file = h('input', { type: 'file', accept: '.glb,model/gltf-binary', hidden: true, class: 'clip-file' });
    file.addEventListener('change', () => {
        const f = file.files[0];
        file.value = '';
        uploadClip(editor, f);
    });
    const rows = clips.map((clip) => {
        const count = (clip.animations || []).length;
        const mapping = h('div', { class: 'joints' });
        const details = h('details', { class: 'joints-box' }, h('summary', {}, t('editor.joints.summary')), mapping);
        details.addEventListener('toggle', () => {
            if (details.open && !mapping.childNodes.length) {
                mappingTable(editor, clip, mapping);
            }
        });
        const mapped = clip.joints && clip.joints.body ? t('clip-editor.mappedByHand') : t('clip-editor.mappedByNames');
        return h('li', { class: 'sound-row has clip-row', 'data-clip': clip.name },
            h('span', { class: 'sound-text' },
                h('span', { class: 'sound-label' }, clip.name),
                h('span', { class: 'muted small' }, t('clip-editor.rowMeta', { count, size: formatBytes(clip.bytes), mapped }))),
            h('span', { class: 'row sound-actions' },
                h('button', { type: 'button', class: 'btn small ghost danger', ...symbolOnly(t('clip-editor.removeLabel', { name: clip.name })), onclick: () => removeClip(editor, clip.name) }, icon('trash'))),
            details);
    });
    const drop = h('div', { class: 'dropzone small' },
        h('p', {}, t('clip-editor.drop')),
        h('button', { type: 'button', class: 'btn', ...symbolOnly(t('clip-editor.upload')), onclick: () => file.click() }, icon('upload')), file);
    drop.addEventListener('dragover', (e) => {
        e.preventDefault();
        e.stopPropagation();
        drop.classList.add('over');
    });
    drop.addEventListener('dragleave', () => drop.classList.remove('over'));
    drop.addEventListener('drop', (e) => {
        e.preventDefault();
        e.stopPropagation();
        drop.classList.remove('over');
        uploadClip(editor, e.dataTransfer.files[0]);
    });
    return h('section', { class: 'clips' },
        h('h4', {}, t('clip-editor.heading')),
        h('p', { class: 'muted small' }, tn('clip-editor.note')),
        rows.length ? h('ul', { class: 'sound-list clip-list' }, rows) : null,
        drop,
        h('p', { class: 'clip-message muted small', role: 'status', 'data-kind': 'info' }));
}
