// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// Reads a live stream into a growing frame store, like a DVR, keeping the newest frames. A source
// opens the stream with up to ten seconds of frames it captured before the viewer joined, which
// arrive at once and land in the store like any other frames. The page asks for numbered frames,
// so a lost connection reconnects, the history that the source sends again drops, and the frames
// lost in between mark a cut.

import { api } from '../core/api.js';
import { FormatError, NODES_FLOAT, PLAYER_FLOATS, StreamParser } from './format.js';
import { t } from '../core/i18n.js';
import { FrameStore } from './timeline.js';

// A stream keeps its newest frames within this memory, which holds 15 minutes of 11 against 11
// and longer for smaller teams, up to LIVE_KEEP_MINUTES.
export const LIVE_KEEP_MINUTES = 30;
const LIVE_BUDGET_BYTES = 80 * 1024 * 1024;

// Frames a live store keeps, from the size of one decoded frame. The budget bounds the store
// whatever the header says, so a header of a great many players or steps keeps fewer frames, and
// always at least one.
export function liveLimit(header) {
    const players = header.players.length;
    const frameBytes = (NODES_FLOAT + players * PLAYER_FLOATS) * 4 + 3 * players + 160;
    const given = header.steps_per_second;
    const sps = Number.isFinite(given) && given > 0 ? given : 10;
    const kept = Math.min(LIVE_KEEP_MINUTES * 60 * sps, Math.floor(LIVE_BUDGET_BYTES / frameBytes));
    return Math.max(1, Math.floor(kept));
}
// A lost connection retries this many times in each outage, after a delay that doubles from the
// first up to the last.
export const RECONNECT_ATTEMPTS = 3;
const RECONNECT_DELAY_MS = 1000;
const RECONNECT_MAX_DELAY_MS = 4000;
// The backlog arrives within this long after the header, frames after it come at real time.
const BACKLOG_SETTLE_MS = 700;
// Frames that may run ahead of real time from network jitter alone.
const JITTER_FRAMES = 2;

export class LiveSource {
    // A full URL reaches a stream on another server, a tunnel for example. The caller only passes
    // one that the user typed, never one from a shared link.
    // open, when given, opens the stream in place of the live source's own, as a game does.
    constructor(id, { onHeader, onFrame, onEnd, onError, onState = null, open = null }) {
        this.id = id;
        this.open = open;
        this.url = /^https?:\/\//i.test(id) ? id : null;
        this.abort = new AbortController();
        this.store = null;
        this.ended = false;
        this.callbacks = { onHeader, onFrame, onEnd, onError, onState };
        this.received = 0;
        this.headerAt = 0;
        this.backlog = 0;
        // The connection, idle, connecting, connected, reconnecting, held, ended or failed.
        this.state = 'idle';
        // Whether the stream numbers its frames, so that a lost connection may resume.
        this.resumable = false;
        // The attempts to reconnect in the current outage, and whether the next new frame
        // follows an outage.
        this.attempts = 0;
        this.resumed = false;
        this.lastSequence = -1;
        // The frames that the stream lost while it reconnected, which the store marks as cuts.
        this.gaps = 0;
        // A held stream lets its connection go until it is released, see hold. link stops the
        // connection alone, and wake ends the wait of a held stream.
        this.held = false;
        this.link = null;
        this.wake = null;
    }

    // Lets the connection go while the page is out of sight, so a tab behind others holds none of
    // the few connections that a browser keeps to one server. Only a stream that numbers its frames
    // holds, and release reconnects it as a lost connection does, the frames in between marked as a
    // cut. Returns whether the stream holds.
    hold() {
        if (!this.resumable || this.ended || this.abort.signal.aborted) {
            return false;
        }
        if (!this.held) {
            this.held = true;
            this.link?.abort();
        }
        return true;
    }

    release() {
        if (this.held) {
            this.held = false;
            this.wake?.();
        }
    }

    // A signal that aborts with the source or with the connection alone.
    connectionSignal() {
        this.link = new AbortController();
        const both = new AbortController();
        for (const signal of [this.abort.signal, this.link.signal]) {
            if (signal.aborted) {
                both.abort();
            }
            signal.addEventListener('abort', () => both.abort(), { once: true });
        }
        return both.signal;
    }

    // Whether the connection ended because the stream holds rather than for good.
    letGo() {
        return this.held && !this.abort.signal.aborted;
    }

    // Resolves with the whole seconds of history the stream opened with, once they have arrived.
    async backlogSeconds() {
        if (!this.headerAt) {
            return 0;
        }
        const wait = this.headerAt + BACKLOG_SETTLE_MS - performance.now();
        if (wait > 0) {
            await new Promise((resolve) => setTimeout(resolve, wait));
        }
        const sps = (this.store && this.store.header.steps_per_second) || 10;
        return Math.round(this.backlog / sps);
    }

    // Reads the stream until it ends, is stopped or fails. A stream that numbers its frames
    // survives a lost connection, see connect, and any other loss ends with onError.
    async start() {
        this.setState('connecting');
        let outage = null;
        while (!this.abort.signal.aborted) {
            let outcome;
            try {
                outcome = await this.connect();
            } catch (err) {
                if (this.abort.signal.aborted || err.name === 'AbortError') {
                    return;
                }
                if (!this.resumable || err.terminal) {
                    this.fail(err);
                    return;
                }
                outcome = 'lost';
                outage = err;
            }
            if (this.abort.signal.aborted) {
                return;
            }
            if (outcome === 'held') {
                this.setState('held');
                await new Promise((resolve) => {
                    const stop = () => resolve();
                    this.wake = () => {
                        this.abort.signal.removeEventListener('abort', stop);
                        resolve();
                    };
                    if (!this.held) {
                        resolve();
                    }
                    this.abort.signal.addEventListener('abort', stop, { once: true });
                });
                this.wake = null;
                if (this.abort.signal.aborted) {
                    return;
                }
                this.setState('reconnecting');
                this.resumed = true;
                continue;
            }
            if (outcome === 'ended') {
                this.ended = true;
                this.setState('ended');
                this.callbacks.onEnd();
                return;
            }
            // A connection that delivered its header ends an outage, so every outage has the
            // whole number of attempts.
            if (this.state === 'connected') {
                this.attempts = 0;
                outage = null;
            }
            if (this.attempts >= RECONNECT_ATTEMPTS) {
                const text = outage ? outage.message.replace(/\.$/, '') : '';
                const reason = text ? `${text[0].toLowerCase()}${text.slice(1)}` : '';
                this.fail(new Error(reason
                    ? t('live.error.lost_reason', { count: RECONNECT_ATTEMPTS, reason })
                    : t('live.error.lost', { count: RECONNECT_ATTEMPTS })));
                return;
            }
            this.setState('reconnecting');
            this.resumed = true;
            const delay = Math.min(RECONNECT_MAX_DELAY_MS, RECONNECT_DELAY_MS * 2 ** this.attempts);
            this.attempts++;
            await new Promise((resolve) => {
                const stop = () => {
                    clearTimeout(timer);
                    resolve();
                };
                const timer = setTimeout(() => {
                    this.abort.signal.removeEventListener('abort', stop);
                    resolve();
                }, delay);
                this.abort.signal.addEventListener('abort', stop, { once: true });
            });
        }
    }

    // onState, when given, hears every change of the connection's state.
    setState(state) {
        if (this.state !== state) {
            this.state = state;
            this.callbacks.onState?.(state);
        }
    }

    fail(err) {
        this.setState('failed');
        this.callbacks.onError(err);
    }

    // Opens the stream once and reads it, resolving with 'ended' when the stream ended and 'lost'
    // when a numbered stream lost its connection. A stream that closes before its header ends,
    // as a game that ends early does, and so does one that never numbered its frames.
    async connect() {
        if (this.held) {
            return 'held';
        }
        const signal = this.connectionSignal();
        let res;
        try {
            res = this.open
                ? await this.open(signal)
                : this.url
                    ? await fetch(this.url, { signal, cache: 'no-store' })
                    : await api.liveStream(this.id, signal);
        } catch (err) {
            if (this.letGo()) {
                return 'held';
            }
            if (err.name === 'AbortError') {
                throw err;
            }
            throw new Error(t(this.url ? 'live.error.unreachable_cors' : 'live.error.unreachable', { error: String(err.message) }));
        }
        if (!res.ok || !res.body) {
            const err = new Error(t('live.error.status', { status: res.status, text: res.statusText }));
            // A source that the server no longer lists has stopped, a failed relay may recover.
            err.terminal = res.status < 500;
            err.status = res.status;
            throw err;
        }
        const parser = new StreamParser(
            (header) => {
                if (this.store) {
                    if (header.stream_sequence !== 1 || header.stream_id !== this.store.header.stream_id) {
                        // The source switched its environment while the connection was lost, so
                        // this stream has ended and the source goes on with another.
                        const err = new Error('The live source started another stream.');
                        err.switched = true;
                        throw err;
                    }
                    if (JSON.stringify(header.players) !== JSON.stringify(this.store.header.players)) {
                        throw new FormatError('live.error.players');
                    }
                } else {
                    this.store = new FrameStore(header, [], liveLimit(header), header.stream_annotations === 1 ? [] : null);
                    this.headerAt = performance.now();
                    this.resumable = header.stream_sequence === 1;
                    this.callbacks.onHeader(header, this.store);
                }
                this.setState('connected');
            },
            (frame) => {
                if (frame.sequence !== undefined) {
                    // A reconnected stream sends the history again, the frames already here drop.
                    if (frame.sequence <= this.lastSequence) {
                        return;
                    }
                    if (this.resumed) {
                        const missed = this.lastSequence >= 0 ? frame.sequence - this.lastSequence - 1 : 0;
                        if (missed > 0) {
                            frame.gap = missed;
                            this.gaps += missed;
                        }
                        this.resumed = false;
                    }
                    this.lastSequence = frame.sequence;
                }
                this.received++;
                // The backlog is how far the frames ran ahead of real time just after the header.
                const elapsed = (performance.now() - this.headerAt) / 1000;
                if (elapsed < 3) {
                    const ahead = this.received - elapsed * (this.store.header.steps_per_second || 10) - JITTER_FRAMES;
                    this.backlog = Math.max(this.backlog, ahead);
                }
                this.store.push(frame);
                // The annotations of frames that the store dropped go with them.
                if (this.store.annotations && this.received % 100 === 0) {
                    this.store.annotations.prune(this.store.get(this.store.first).sequence ?? 0);
                }
                this.callbacks.onFrame(frame);
            },
            (records) => {
                if (this.store && this.store.annotations) {
                    this.store.annotations.add(records);
                }
            },
        );
        const reader = res.body.getReader();
        try {
            for (;;) {
                const { done, value } = await reader.read();
                if (done) {
                    break;
                }
                parser.push(value);
                if (parser.ended) {
                    return 'ended';
                }
            }
        } catch (err) {
            if (this.letGo()) {
                return 'held';
            }
            if (err.switched) {
                return 'ended';
            }
            // A malformed stream, or a lost one that cannot resume, stops here, so the
            // connection does not keep the source busy.
            if (err instanceof FormatError || !this.resumable) {
                err.terminal = true;
            }
            throw err;
        } finally {
            reader.cancel().catch(() => {});
        }
        if (this.letGo()) {
            return 'held';
        }
        // Only a numbered stream that delivered its header and lost its connection reconnects.
        return parser.header && parser.header.stream_sequence === 1 ? 'lost' : 'ended';
    }

    stop() {
        this.abort.abort();
    }
}
