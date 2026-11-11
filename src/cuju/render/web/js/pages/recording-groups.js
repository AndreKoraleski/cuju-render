// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// The groups of the Recordings page. The recordings of one run of a challenge share a group, which
// the table shows as one row that names the challenge, the competitor and the run's result, and
// which opens to the rows of its attempts. This module reads summaries alone, so Node tests it.

// The group of a summary, or null for a recording outside any group.
export function groupOf(summary) {
    const group = summary && summary.group;
    return group && typeof group === 'object' && typeof group.id === 'string' && group.id ? group : null;
}

function attemptOf(summary) {
    const attempt = groupOf(summary).attempt;
    return Number.isInteger(attempt) ? attempt : 0;
}

// The items of the table for rows already filtered and sorted. A recording outside a group is
// { kind: 'recording', recording }, and a group is { kind: 'group', id, group, members } at the
// place of its first row, with its members in the order of their attempts.
export function groupRows(rows) {
    const items = [];
    const groups = new Map();
    for (const summary of rows) {
        const group = groupOf(summary);
        if (!group) {
            items.push({ kind: 'recording', recording: summary });
            continue;
        }
        let item = groups.get(group.id);
        if (!item) {
            item = { kind: 'group', id: group.id, group, members: [] };
            groups.set(group.id, item);
            items.push(item);
        }
        item.members.push(summary);
    }
    for (const item of groups.values()) {
        item.members.sort((a, b) => attemptOf(a) - attemptOf(b));
    }
    return items;
}

// The totals of a group's members, their steps and bytes added up and the newest date.
export function groupTotals(members) {
    let steps = 0;
    let bytes = 0;
    let created = null;
    let newest = -Infinity;
    for (const summary of members) {
        steps += Number(summary.steps) || 0;
        bytes += Number(summary.bytes) || 0;
        const time = Date.parse(summary.created);
        if (!Number.isNaN(time) && time > newest) {
            newest = time;
            created = summary.created;
        }
    }
    return { steps, bytes, created };
}

// The rows that the keyboard and the selection walk, in the order of the table. A group is one row
// that selects all its members, and the rows of its members follow while it is open.
export function navigationRows(items, open) {
    const rows = [];
    for (const item of items) {
        if (item.kind === 'recording') {
            rows.push({ key: item.recording.id, ids: [item.recording.id], recording: item.recording, group: null });
            continue;
        }
        rows.push({ key: `group:${item.id}`, ids: item.members.map((m) => m.id), recording: null, group: item });
        if (open.has(item.id)) {
            for (const member of item.members) {
                rows.push({ key: member.id, ids: [member.id], recording: member, group: null, parent: item.id });
            }
        }
    }
    return rows;
}
