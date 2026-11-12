// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// The viewer application, which wires the scene, playback, controls, sound and panels together.

import * as THREE from 'three';
import { onLanguageChange } from './core/i18n.js';
import { t } from './core/i18n.js';
import './core/keys.js';
import { LanguageSettings } from './core/language-ui.js';
import { api, formatBytes } from './core/api.js';
import { PlayerTools } from './watch/player-tools.js';
import { AnnotationOverlay } from './watch/annotations.js';
import { AccessibilityControls } from './core/accessibility.js';
import { OWN_KEYS, keepsKey, openPanel } from './core/comfort.js';
import { PageStructure } from './core/page-structure.js';
import { Sound } from './broadcast/audio.js';
import { Ball } from './world/ball.js';
import { CAMERA_MODES, CameraRig, PLAYER_VIEWS } from './world/cameras.js';
import { TeamEditor, loadShippedRig } from './teams/editor.js';
import { ACTION, EPISODE_START, FormatError, PLAYER_FLOATS, TOUCH, isCut } from './recording/format.js';
import { decodeRecording } from './recording/decode.js';
import { Hud, formatSeconds } from './broadcast/hud.js';
import { modelChoice, normalizeStyle, separateKeepers } from './players/kits.js';
import { loadTeamArt } from './teams/art.js';
import { TeamsPage } from './teams/library.js';
import { surpriseFor } from './teams/surprise-ui.js';
import { RecordingsPage } from './pages/recordings.js';
import { FieldPage } from './pages/fieldpage.js';
import { loadField, loadImages } from './world/field.js';
import { LiveSource } from './recording/live.js';
import { MatchesPage } from './pages/matches.js';
import { TournamentsPage } from './play/tournament.js';
import { PlayPage } from './play/play.js';
import { bindTopMenus } from './core/menu.js';
import { GOAL_DEPTH, GOAL_HALF_WIDTH, GOAL_HEIGHT, HALF_W, Pitch } from './world/pitch.js';
import { Players, loadAssets, loadTeamRig, playerModel } from './players/players.js';
import { loadTeamClips, qualifyStyle } from './players/clips.js';
import { Pose } from './recording/pose.js';
import { Presentation } from './presentation/index.js';
import { SideChoices } from './presentation/assign.js';
import { Preview } from './presentation/preview.js';
import { Director, Podium, PostMatch, Spotlight, playerInfo, scorerAt } from './broadcast/show.js';
import { Environment, View, defaultQuality } from './world/scene.js';
import { Stadium } from './world/stadium.js';
import { FrameStore, Timeline } from './recording/timeline.js';
import { Transitions } from './broadcast/transition.js';
import { Decisions } from './broadcast/decisions.js';
import { fullMatch } from './recording/episodes.js';
import { recordingTitle, teamName } from './core/names.js';
import { hidesOutcome } from './core/spoilers.js';
import { CommandPalette } from './help/palette.js';
import { SettingsPresets } from './watch/presets.js';
import { FirstRun } from './help/firstrun.js';
import { TouchControls } from './play/touch.js';
import { FlatMode, headlessView } from './watch/flat.js';
import { EnvironmentGrid } from './watch/grid.js';
import { VideoExport } from './export/video-export.js';
import { CaptionsOverlay } from './recording/captions.js';
import { MomentSearch } from './pages/moments-ui.js';
import { FeedDialog } from './export/feed-dialog.js';

const $ = (id) => document.getElementById(id);
const SPEEDS = [0.25, 0.5, 1, 2, 4];
const HALF_TIME_MS = 45 * 60 * 1000;
// How long a page stays out of sight before it lets its live stream go.
const HIDDEN_HOLD_MS = 30 * 1000;
// The cameras a new visit opens on, the wide views of the whole pitch.
const REMEMBERED_CAMERAS = new Set(['broadcast', 'tactical', 'goal']);

function load(key, fallback) {
    try {
        const v = localStorage.getItem(`cuju.${key}`);
        return v === null ? fallback : JSON.parse(v);
    } catch {
        return fallback;
    }
}

function save(key, value) {
    try {
        localStorage.setItem(`cuju.${key}`, JSON.stringify(value));
    } catch {
        // Storage can be unavailable, settings then last for this visit only.
    }
}

// Whether keyboard focus rests inside an element, which keeps it in view. A browser without :has
// counts any focus inside.
function keyboardFocusIn(selector) {
    try {
        return document.querySelector(`${selector}:has(:focus-visible)`);
    } catch {
        return document.querySelector(`${selector}:focus-within`);
    }
}

// The theme of the page, system to follow the operating system, or dark or light.
function applyTheme(theme) {
    if (theme === 'dark' || theme === 'light') {
        document.documentElement.dataset.theme = theme;
    } else {
        delete document.documentElement.dataset.theme;
    }
}

class App {
    constructor() {
        this.hud = new Hud();
        try {
            this.view = new View($('stage'));
        } catch (err) {
            // A browser without WebGL 2 watches matches in the 2D view.
            this.noWebGL = err.message || 'no WebGL';
            this.view = headlessView($('stage'), View);
        }
        this.settings = {
            quality: load('quality', defaultQuality()),
            volume: load('volume', 0.5),
            muted: load('muted', true),
            camera: REMEMBERED_CAMERAS.has(load('camera', 'broadcast')) ? load('camera', 'broadcast') : 'broadcast',
            idleReturn: load('idleReturn', true),
            idleSeconds: load('idleSeconds', 20),
            trail: load('trail', true),
            savedStyle: load('savedStyle', false),
            classic: load('classic', false),
            replays: load('replays', true),
            transitions: load('transitions', true),
            decisionReplays: load('decisionReplays', true),
            slowmo: load('slowmo', '0.5'),
            podium: load('podium', true),
            pointerLock: load('pointerLock', false),
            tvMode: load('tvMode', false),
            theme: load('theme', 'system'),
        };
        applyTheme(this.settings.theme);
        this.view.setQuality(this.settings.quality);
        this.field = loadField();
        this.pitch = new Pitch(this.view.scene, this.view.renderer, this.settings.quality);
        this.stadium = new Stadium(this.view.scene);
        this.stadium.setQuality(this.settings.quality);
        // Sky, light and weather for the hour of the field settings.
        this.environment = new Environment(this);
        this.ball = new Ball(this.view.scene);
        this.ball.setTrail(this.settings.trail);
        this.cameras = new CameraRig(this.view.camera, this.view.renderer.domElement);
        this.cameras.allowLock = this.settings.pointerLock;
        this.cameras.setMode(this.settings.camera);
        // The free camera drifts back to the broadcast view after a while without input.
        this.cameras.onIdle = () => {
            this.setCamera('broadcast');
            this.hud.toast(t('main.camera.idleBack'), 'info', 1500);
        };
        this.sound = new Sound();
        this.sound.setVolume(this.settings.volume);
        this.sound.setMuted(this.settings.muted);
        this.library = new TeamsPage(this);
        this.recordings = new RecordingsPage(this);
        this.matches = new MatchesPage(this);
        this.tournaments = new TournamentsPage(this);
        this.play = null;
        this.fieldPage = new FieldPage(this);
        this.editor = new TeamEditor(this);
        this.assets = { manifest: null, rig: null, hair: [] };
        this.source = null;
        this.timeline = null;
        this.players = null;
        this.pose = null;
        this.lastIndex = -1;
        this.excitement = 0.3;
        this.goalBoost = 0;
        this.director = new Director(this);
        this.podium = new Podium(this);
        this.spotlight = new Spotlight(this);
        this.postMatch = new PostMatch(this);
        // Team presentation packages, see presentation/index.js.
        this.presentation = new Presentation(this);
        this.view.afterRender = (renderer, scene, camera) => this.presentation.afterRender(renderer, scene, camera);
        this.cameras.adjust = () => this.presentation.moments.cameraAdjust();
        this.lastTime = performance.now();
        this.poseHooks = [];
        // Restarts, half time and the referee's decisions, presented as on television.
        this.transition = new Transitions(this);
        this.decisions = new Decisions(this, this.transition);
        this.playerTools = new PlayerTools(this);
        this.annotationOverlay = new AnnotationOverlay(this);
        this.captions = new CaptionsOverlay(this);
        this.moments = new MomentSearch(this);
        this.accessibility = new AccessibilityControls(this);
        this.sideChoices = new SideChoices(this);
        this.presentation.preview = new Preview(this);
        this.palette = new CommandPalette(this, { CAMERA_MODES, api });
        this.videoExport = new VideoExport(this);
        this.feedDialog = new FeedDialog(this);
        this.clock = 0;
        this.idleTimer = null;
        this.hashTimer = null;
        this.loadToken = 0;
        this.tvMode = false;
        // The Home page is its own module, a failure there leaves the other pages working.
        this.home = null;
        import('./pages/home.js').then((m) => {
            this.home = new m.HomePage(this);
            if (this.page === 'home') {
                this.home.show();
            }
            // The offer to install the page as an app, a card of Home and its own module, reached
            // by scripts as cuju.installOffer.
            import('./help/install-offer.js').then((offer) => {
                this.installOffer = new offer.InstallOffer(this).script();
            }).catch((err) => console.warn('install offer not loaded', err));
        }).catch((err) => console.warn('home page not loaded', err));
        // Photo mode, its own module as well, reached by scripts as cuju.photo.
        this.photo = null;
        import('./export/photo.js').then((m) => {
            this.photo = new m.PhotoMode(this);
        }).catch((err) => console.warn('photo mode not loaded', err));
        this.bindControls();
        this.bindPages();
        this.bindAddress();
        this.bindKeys();
        this.bindDrop();
        this.bindIdle();
        this.bindPointerRelease();
        this.bindTv();
        this.syncSettingsUi();
        // The 2D view, which reads the presentations that need 3D as off while it draws.
        this.flat = new FlatMode(this, this.noWebGL || null);
        this.settings = this.flat.gate(this.settings);
        this.grid = new EnvironmentGrid(this);
        this.presets = new SettingsPresets(this);
        // The language of the page, whose change reloads the page at its address in the new one.
        this.language = new LanguageSettings(this);
        onLanguageChange(() => {
            this.updateHash(true);
            location.reload();
        });
        this.firstRun = new FirstRun(this);
        this.structure = new PageStructure(this);
        // The tour, the lessons, the samples, the report and the installable page of Help, which
        // scripts reach as cuju.tour, cuju.tutorial, cuju.samples, cuju.doctor and cuju.install.
        this.helpCenter = null;
        import('./help/help-center.js').then((m) => {
            this.helpCenter = new m.HelpCenter(this);
        }).catch((err) => console.warn('help center not loaded', err));
        this.touch = new TouchControls(this);
        this.showEmpty(true);
        this.applyField(this.field);
        // The art loads beside the first recording, which waits for it to build its players once.
        this.assetsReady = loadAssets(undefined, (done, asked) => {
            this.assetProgress = done / Math.max(1, asked);
        }).then((assets) => {
            this.assets = assets;
            if (assets.ball) {
                this.ball.useModel(assets.ball);
            }
            if (assets.goals) {
                this.pitch.useGoals(assets.goals);
            }
            if (assets.pitch) {
                this.pitch.setClassic(this.settings.classic, assets.pitch);
            }
            if (assets.crowd || assets.adboards.length) {
                this.stadium.dispose();
                this.stadium = new Stadium(this.view.scene, assets.crowd, assets.adboards);
                this.stadium.setQuality(this.settings.quality);
                this.stadium.setCrowd(this.field);
                this.environment.apply();
                if (this.styles) {
                    this.stadium.setFans(this.styles[0].fans, this.styles[1].fans);
                }
                this.applyBoards();
            }
            if (this.source) {
                this.rebuildPlayers();
            }
            if (this.editor.isOpen) {
                this.editor.refreshPreview();
            }
        });
        // Frames stop while the page is hidden, so the sound is silenced here rather than by tick.
        document.addEventListener('visibilitychange', () => {
            if (document.hidden) {
                this.sound.setActive(false);
            }
            this.holdHiddenStream();
        });
        window.addEventListener('hashchange', () => this.openFromHash());
        this.openFromHash();
        requestAnimationFrame((t) => this.tick(t));
    }

    // A page out of sight for a while lets its live stream go, so tabs behind others hold none of
    // the six connections that a browser keeps to one server, and the stream resumes as the page
    // shows again. A clean feed keeps its stream, since a streaming program shows it unseen.
    holdHiddenStream() {
        clearTimeout(this.holdTimer);
        const live = this.source && this.source.live;
        if (!live || window.cujuFeed) {
            return;
        }
        if (!document.hidden) {
            live.release();
            return;
        }
        this.holdTimer = setTimeout(() => {
            if (document.hidden && this.source && this.source.live === live) {
                live.hold();
            }
        }, HIDDEN_HOLD_MS);
    }

    fatal(text) {
        const el = $('fatal');
        el.textContent = text;
        el.hidden = false;
    }

    // Sources.

    openMatchInWatch(id) {
        this.showPage('watch');
        this.openMatch(id);
    }

    // The address bar takes a live source id, a full stream URL, or a recording id.
    async openAddress(text) {
        const value = text.trim();
        if (!value) {
            return;
        }
        if (/^https?:\/\//i.test(value)) {
            const m = value.match(/\/api\/matches\/([^/?#]+)/);
            if (m && !/\/stream/.test(value)) {
                this.openMatch(decodeURIComponent(m[1]));
            } else {
                this.openLive(value, true);
            }
            return;
        }
        let live = [];
        try {
            live = await api.live();
        } catch {
            // Without the list, a known recording id still opens below.
        }
        if (live.some((s) => s.id === value)) {
            this.openLive(value);
        } else {
            this.openMatch(value);
        }
    }

    // Stops a live source that is still connecting, a later choice wins over it.
    dropPendingLive() {
        if (this.pendingLive && (!this.source || this.source.live !== this.pendingLive)) {
            this.pendingLive.stop();
            this.setWaiting(null);
        }
        this.pendingLive = null;
    }

    async openMatch(id, seekSeconds = null) {
        const token = ++this.loadToken;
        this.dropPendingLive();
        this.showPage('watch');
        this.showLoading(t('main.loading.download'), 0);
        try {
            const bytes = await api.matchBytes(id, (got, total) => {
                if (token === this.loadToken) {
                    this.showLoading(total ? t('main.loading.downloadOf', { got: formatBytes(got), total: formatBytes(total) }) : t('main.loading.downloadGot', { got: formatBytes(got) }), total ? got / total : null);
                }
            });
            if (token !== this.loadToken) {
                return;
            }
            this.showLoading(t('main.loading.frames', { size: formatBytes(bytes.length) }), null);
            const rec = await decodeRecording(bytes);
            if (token !== this.loadToken || !(await this.waitForAssets(token))) {
                return;
            }
            await this.setSource({ kind: 'match', id, header: rec.header, store: new FrameStore(rec.header, rec.frames, Infinity, rec.annotations) });
            if (seekSeconds != null) {
                this.timeline.seek(this.timeline.first + seekSeconds * this.timeline.sps);
                this.afterSeek();
            }
            this.timeline.play(1);
            // Team sheets before kick-off when the match opens at its start.
            this.director.showLineups();
        } catch (err) {
            const missing = err.status === 404;
            this.hud.toast(err instanceof FormatError ? err.message : missing ? t('main.match.missing', { id }) : t('main.match.failed', { reason: err.message }), 'error', 8000);
            if (!this.source) {
                this.showEmpty(true);
            }
        } finally {
            if (token === this.loadToken) {
                this.hideLoading();
            }
        }
    }

    // Waits for the art that is still loading, with its share on the bar, so the players of a
    // recording are built once with their models. Returns whether the load of `token` goes on.
    async waitForAssets(token) {
        let done = false;
        const settled = this.assetsReady.catch(() => {}).then(() => {
            done = true;
        });
        while (!done && token === this.loadToken) {
            this.showLoading(t('main.loading.assets'), this.assetProgress || 0);
            await Promise.race([settled, new Promise((resolve) => setTimeout(resolve, 100))]);
        }
        return token === this.loadToken;
    }

    async openFile(file) {
        this.showPage('watch');
        const token = ++this.loadToken;
        this.dropPendingLive();
        this.showLoading(t('main.loading.file', { name: file.name }));
        try {
            const rec = await decodeRecording(new Uint8Array(await file.arrayBuffer()));
            if (token !== this.loadToken || !(await this.waitForAssets(token))) {
                return;
            }
            await this.setSource({ kind: 'file', id: file.name, header: rec.header, store: new FrameStore(rec.header, rec.frames, Infinity, rec.annotations) });
            this.timeline.play(1);
            this.director.showLineups();
            this.updateHash(true);
        } catch (err) {
            this.hud.toast(err instanceof FormatError ? err.message : t('main.file.failed', { name: file.name, reason: err.message }), 'error', 8000);
        } finally {
            if (token === this.loadToken) {
                this.hideLoading();
            }
        }
    }

    // A full URL reaches a stream on another server, so it opens only when the user typed it,
    // never from a link someone shared. A source that switched its environment opens again on
    // the page that the viewer is on.
    openLive(id, typed = false, switched = false) {
        if (/^https?:\/\//i.test(id) && !typed) {
            this.hud.toast(t('main.live.remoteTyped'), 'error', 8000);
            return;
        }
        const token = ++this.loadToken;
        this.dropPendingLive();
        if (!switched) {
            this.showPage('watch');
        }
        this.setWaiting(t('main.live.waiting'));
        const live = new LiveSource(id, {
            onHeader: async (header, store) => {
                if (token !== this.loadToken) {
                    live.stop();
                    return;
                }
                this.setWaiting(t('main.live.connected'), 900);
                await this.setSource({ kind: 'live', id, header, store, live });
                if (this.source.live !== live) {
                    return;
                }
                if (switched) {
                    this.hud.toast(t('main.live.switched', { environment: (header.provenance && header.provenance.environment) || 0 }), 'info', 4000);
                }
                this.timeline.goLive();
                // A source sends what it already captured first, so the viewer can rewind at once.
                // The history is what the store spans once that backlog has arrived.
                await live.backlogSeconds();
                if (this.source && this.source.live === live && store.size > 1) {
                    const sps = header.steps_per_second || 10;
                    const seconds = Math.floor((store.last - store.first) / sps);
                    if (seconds >= 1) {
                        this.hud.toast(t('main.live.joined', { count: seconds }), 'info', 3500);
                    }
                }
            },
            onFrame: () => {},
            onState: () => {
                if (this.source && this.source.live === live) {
                    this.updateLiveUi();
                }
            },
            onEnd: async () => {
                if (await this.followSwitch(live)) {
                    return;
                }
                // A source that closes before its first frame leaves nothing to watch.
                if (this.pendingLive === live && !live.store) {
                    this.setWaiting(null);
                    this.pendingLive = null;
                    if (token === this.loadToken) {
                        this.hud.toast(t('main.live.endedEmpty'), 'info');
                    }
                }
                if (this.source && this.source.live === live) {
                    this.hud.toast(t('main.live.ended'), 'info', 6000);
                    this.updateLiveUi();
                }
            },
            onError: (err) => {
                live.stop();
                live.failed = true;
                // A source whose process ended answers 404 or 502 through the server, which the
                // status of the error says in every language.
                if (err.status === 404 || err.status === 502 || /answered (404|502)|no such live source|did not answer/i.test(err.message)) {
                    err = new Error(t('main.live.stopped'));
                }
                if (this.pendingLive === live) {
                    this.setWaiting(null);
                    this.pendingLive = null;
                }
                if (this.source && this.source.live === live) {
                    this.hud.toast(t('main.live.failedKept', { reason: err.message }), 'error', 8000);
                    this.updateLiveUi();
                } else if (token === this.loadToken) {
                    this.hud.toast(err.message, 'error', 8000);
                }
            },
        });
        this.pendingLive = live;
        live.start();
    }

    // A source that switches its environment ends its streams and stays listed, while a source
    // that closes leaves the list first, so a stream that ends on a listed source gives way to
    // the stream of the new environment.
    async followSwitch(live) {
        const watched = () => this.pendingLive === live || (this.source && this.source.live === live);
        if (live.url || live.open || !watched()) {
            return false;
        }
        let entry;
        try {
            entry = (await api.live()).find((s) => s.id === live.id);
        } catch {
            return false;
        }
        if (!entry || !watched()) {
            return false;
        }
        this.openLive(live.id, false, true);
        return true;
    }

    // Asks the live source to show another environment of its batch. The source switches after
    // the next step of the batch and ends this stream, and followSwitch opens the new one.
    async switchEnvironment() {
        const source = this.source;
        const live = source && source.kind === 'live' ? source.live : null;
        if (!live) {
            return;
        }
        const count = source.header.environment_count || 1;
        const current = (source.header.provenance && source.header.provenance.environment) || 0;
        const environment = Number($('live-env-index').value);
        if (!Number.isInteger(environment) || environment < 0 || environment >= count) {
            this.hud.toast(t('main.environment.range', { last: count - 1 }), 'error');
            return;
        }
        if (environment === current) {
            this.hud.toast(t('main.environment.already', { environment }), 'info');
            return;
        }
        $('live-env-go').disabled = true;
        try {
            await api.selectEnvironment(source.id, environment);
            this.switchingLive = live;
            this.hud.toast(t('main.environment.pending', { environment }), 'info');
        } catch (err) {
            this.hud.toast(t('main.environment.failed', { reason: err.message }), 'error', 8000);
        } finally {
            $('live-env-go').disabled = false;
        }
    }

    async setSource(source) {
        if (this.source && this.source.live && this.source.live !== source.live) {
            this.source.live.stop();
        }
        this.director.stop(false);
        if (this.postMatch.running) {
            this.postMatch.end();
        }
        // A podium that stands on its own, as the trophy ceremony of a tournament raises it, goes
        // with the source it stood over.
        if (this.podium.showing) {
            this.podium.hide();
        }
        this.sound.stopEvents();
        clearTimeout(this.fullTimeTimer);
        $('post-show').hidden = true;
        if (this.endCard) {
            this.endCard = false;
            this.transition.title.hide();
        }
        this.source = source;
        this.cameras.focusIndex = 0;
        this.cameras.followIndex = 0;
        this.lastGoal = null;
        this.timeline = new Timeline(source.store, source.kind === 'live');
        this.userPaused = false;
        this.timeline.onEnd = () => {
            this.updatePlayUi();
            // The frames of the last step still sound, the final whistle among them, before the
            // show takes the timeline.
            const tl = this.timeline;
            if (this.lastIndex >= 0 && this.lastIndex < tl.index) {
                this.endReached = true;
                this.onFrameChange(this.lastIndex, tl.index, true);
                this.lastIndex = tl.index;
            }
            // A recording that plays to its end tells the page, so a tournament watched without
            // spoilers marks its match watched.
            if (source.kind === 'match') {
                document.dispatchEvent(new CustomEvent('cuju:recording-ended', { detail: { id: source.id, provenance: source.header.provenance || null } }));
            }
            if (!this.director.running) {
                const f = source.store.get(source.store.last);
                const h = source.header;
                const ended = f && !!(f.flags & 1);
                // An episode that ended plays the show, under the card of full time for a full
                // match and under the card of the end of an episode otherwise, as for an older
                // recording without timing. A recording saved before its episode ended shows its
                // own card alone.
                if (ended && fullMatch(h)) {
                    clearTimeout(this.fullTimeTimer);
                    this.transition.fullTime();
                    this.postMatch.start();
                } else if (ended) {
                    this.transition.title.show(t('main.end.episode'), h, this.styles, f, '',
                        this.settings.podium ? [] : [this.postMatch.statsButton()]);
                    clearTimeout(this.fullTimeTimer);
                    this.fullTimeTimer = setTimeout(() => this.transition.title.hide(), 4500);
                    this.postMatch.start();
                } else {
                    this.transition.title.show(t('main.end.recording'), h, this.styles, f, '', [this.postMatch.statsButton()]);
                    this.endCard = true;
                }
            }
        };
        this.speedIndex = 2;
        this.timeline.speed = 1;
        this.pose = new Pose(source.header.players.length);
        this.lastIndex = -1;
        $('address-input').value = source.kind === 'file' ? '' : source.id;
        $('address-input').placeholder = source.kind === 'file' ? source.id : $('address-input').placeholder;
        this.structure?.setWatchTitle(recordingTitle(source.header, source.kind === 'match' ? source.id : null) || t('main.title.match'));
        this.showEmpty(false);
        await this.rebuildPlayers();
        this.applyBoards();
        this.updateHash(true);
        this.updateLiveUi();
        this.renderMarkers();
        this.cameras.jump();
        this.ball.reset();
        this.updatePlayUi();
        $('app').classList.toggle('is-live', source.kind === 'live');
    }

    // Kit styles, the team's current registry style when the header names a known team, unless
    // the viewer asked for the style saved in the match.
    async resolveTeams(header) {
        let registry = this.library.teams;
        try {
            registry = await this.library.loadTeams();
        } catch {
            // Offline or no server, the header alone decides.
        }
        const styles = [];
        const rigs = [];
        const sponsors = [];
        const entries = [];
        for (let side = 0; side < 2; side++) {
            const team = header.teams[side] || {};
            const known = team.id != null ? registry.find((t) => t.id === team.id) : null;
            entries.push(known || null);
            const useRegistry = known && !this.settings.savedStyle;
            const raw = (useRegistry ? known.style : team.style) || {};
            const style = normalizeStyle(useRegistry ? { ...team, style: known.style } : team, side);
            // The fans wear the team's crowd colors, else its kit colors.
            const fans = raw.crowd && Array.isArray(raw.crowd.colors) && raw.crowd.colors.length
                ? raw.crowd.colors : [style.kit.primary, style.kit.secondary];
            style.fans = fans.slice(0, 4);
            const model = modelChoice(useRegistry ? known.style : team.style);
            style.model = model;
            const art = known ? await loadTeamArt(known) : { front: null, back: null, sponsors: [] };
            // Artwork belongs to GRF's own model, which any player of the roster may wear.
            style.art = art;
            sponsors.push(art.sponsors);
            // The team's own celebration clips play under names of their own while it plays.
            if (known) {
                qualifyStyle(style, await loadTeamClips(known));
            }
            styles.push(style);
            // A rig for every model the players of this side use, by model, shared by players.
            const wanted = new Set([model]);
            for (const p of header.players) {
                if (p.team === side) {
                    wanted.add(playerModel(style, p.index));
                }
            }
            const table = new Map();
            await Promise.all([...wanted].map(async (m) => {
                let rig = null;
                if (m === 'custom' && known && known.model) {
                    rig = await loadTeamRig(known);
                } else if (m !== 'grf' && m !== 'custom') {
                    rig = await loadShippedRig(m);
                }
                if (rig) {
                    table.set(m, rig);
                }
            }));
            await this.presentation.prepare(side, known, style, table);
            rigs.push(table);
        }
        this.sponsors = sponsors;
        separateKeepers(styles, header.teams);
        // A team's own sounds play for its players, the registry entry lists them.
        this.sound.setTeams(entries);
        return { styles, rigs };
    }

    async rebuildPlayers() {
        if (!this.source) {
            return;
        }
        const source = this.source;
        const { styles, rigs } = await this.resolveTeams(source.header);
        if (this.source !== source) {
            return;
        }
        if (this.players) {
            this.players.dispose();
        }
        this.styles = styles;
        this.teamRigs = rigs;
        this.players = new Players(this.view.scene, source.header, styles, this.assets, rigs, { presentation: this.presentation });
        this.presentation.attach(this.players, source.header, styles);
        this.hud.setTeams(source.header, styles);
        this.applyBoards();
        this.stadium.setFans(styles[0].fans, styles[1].fans);
    }

    // Field settings from the Field page, applied to the pitch, stands, light and boards.
    applyField(field) {
        const old = this.field || {};
        this.field = field;
        this.pitch.setField(field);
        this.environment.setField(field);
        this.stadium.setCrowd(field);
        const boardsChanged = !old.customBoards || old.customBoards.length !== field.customBoards.length
            || old.customBoards.some((b, i) => b !== field.customBoards[i]);
        if (boardsChanged || !this.customBoards) {
            loadImages(field.customBoards).then((images) => {
                this.customBoards = images;
                this.applyBoards();
            });
        }
        this.applyBoards();
    }

    applyBoards() {
        const mode = this.field ? this.field.boards : 'sponsors';
        if (mode === 'custom' && this.customBoards && this.customBoards.length) {
            this.stadium.setTeams(['', ''], ['#202124', '#202124'], this.customBoards);
            return;
        }
        if (!this.source || !this.styles) {
            this.stadium.setTeams(['Cuju', 'Cuju'], ['#202124', '#ff6f00'], []);
            return;
        }
        const names = this.source.header.teams.map((team) => teamName(team));
        const colors = this.styles.map((s) => `rgb(${s.kit.primary.join(',')})`);
        if (mode === 'shipped') {
            this.stadium.setTeams(names, colors, []);
            return;
        }
        // Sponsors of both teams alternate around the ground.
        const [a, b] = this.sponsors || [[], []];
        const boards = [];
        for (let i = 0; i < Math.max(a.length, b.length); i++) {
            if (a[i]) {
                boards.push(a[i]);
            }
            if (b[i]) {
                boards.push(b[i]);
            }
        }
        this.stadium.setTeams(names, colors, boards);
    }

    teamsChanged() {
        this.library.refresh();
        if (this.page === 'matches') {
            this.matches.refresh();
        }
        this.rebuildPlayers();
    }

    editTeam(team) {
        this.editor.open(team);
    }

    // Surprise me for scripts, a seeded team from surprise.js, which apply also gives the open
    // team editor as unsaved changes.
    surprise(options = {}) {
        return surpriseFor(this, options);
    }

    // Pages, as tabs in the top bar, with the logo at its left for the Home page.
    bindPages() {
        for (const b of document.querySelectorAll('#home-btn, .menu [data-page], #page-menu [data-page]')) {
            b.addEventListener('click', () => this.showPage(b.dataset.page));
        }
    }

    showPage(name) {
        if (this.page === name) {
            return;
        }
        const previous = this.page;
        if (name === 'help') {
            this.helpReturn = previous;
        }
        const contentFocus = $('pages').contains(document.activeElement);
        this.page = name;
        this.updateHash(true);
        for (const b of document.querySelectorAll('#home-btn, .menu [data-page], #page-menu [data-page]')) {
            const on = b.dataset.page === name;
            b.classList.toggle('active', on);
            b.setAttribute('aria-current', on ? 'page' : 'false');
        }
        // The dropdown of a narrow screen names every page, Home among them.
        const item = document.querySelector(`#page-menu [data-page="${name}"] .dd-label`);
        $('page-menu-label').textContent = item ? item.textContent : name;
        for (const el of document.querySelectorAll('.page')) {
            el.hidden = el.id !== `page-${name}`;
        }
        $('app').dataset.page = name;
        if (name !== 'watch') {
            this.releasePointer();
            $('app').classList.remove('tv-peek', 'tv-hint');
        }
        // Home is a page to read and click, so it leaves fullscreen, as the end of a show does.
        if (name === 'home' && document.fullscreenElement) {
            document.exitFullscreen().catch(() => {});
        }
        if (previous === 'home' && this.home) {
            this.home.hide();
        }
        if (name === 'home' && this.home) {
            this.home.show();
        }
        if (previous === 'field') {
            this.fieldPage.hide();
        }
        if (previous === 'play' && this.play) {
            this.play.hide();
        }
        if (name === 'play') {
            this.play = this.play || new PlayPage(this);
            this.play.show();
        }
        if (name === 'recordings') {
            this.recordings.refresh();
        } else if (name === 'matches') {
            this.matches.refresh();
        } else if (name === 'tournaments') {
            this.tournaments.refresh();
        } else if (name === 'teams') {
            this.library.refresh();
        } else if (name === 'field') {
            this.fieldPage.show();
        }
        this.structure?.update(name);
        if (contentFocus) {
            $('pages').focus();
        }
        if (previous === 'teams' && this.editor.isOpen) {
            this.editor.stopPreview();
        } else if (name === 'teams' && this.editor.isOpen) {
            this.editor.startPreview();
        }
    }

    bindAddress() {
        const form = $('address');
        const input = $('address-input');
        form.addEventListener('submit', (e) => {
            e.preventDefault();
            this.sound.unlock();
            this.openAddress(input.value);
            input.blur();
        });
        const fill = async () => {
            let list = [];
            try {
                list = await api.live();
                this.library.setOffline(false);
            } catch (err) {
                if (err.status === 0) {
                    this.library.setOffline(true);
                }
            }
            // The Match menu lists the sources, its button shows how many stream now.
            const count = $('live-count');
            count.hidden = !list.length;
            count.textContent = list.length ? String(list.length) : '';
            count.title = list.length ? t('main.live.count', { count: list.length }) : '';
        };
        fill();
        setInterval(() => {
            if (this.page === 'watch' && !document.hidden) {
                fill();
            }
        }, 8000);
    }

    // A spinner in the watch window while a live source has not sent its header yet.
    setWaiting(text, hideAfter = 0) {
        const el = $('waiting');
        clearTimeout(this.waitingTimer);
        if (!text) {
            el.hidden = true;
            return;
        }
        $('waiting-text').textContent = text;
        el.classList.toggle('done', !!hideAfter);
        el.hidden = false;
        if (hideAfter) {
            this.waitingTimer = setTimeout(() => {
                el.hidden = true;
            }, hideAfter);
        }
    }

    // The player to follow in owner mode at frame index i, decided from the frames alone so it
    // works the same when scrubbing backwards. The owner, else the last owner within 1.5 s,
    // else the player nearest the ball.
    ownerAt(i) {
        const store = this.timeline.store;
        const sps = this.timeline.sps;
        let f = store.get(i);
        if (!f) {
            return -1;
        }
        if (f.ownedPlayer >= 0) {
            return f.ownedPlayer;
        }
        for (let j = i - 1; j >= Math.max(store.first, i - Math.round(1.5 * sps)); j--) {
            const g = store.get(j);
            if (!g || isCut(g, f)) {
                break;
            }
            if (g.ownedPlayer >= 0) {
                return g.ownedPlayer;
            }
            f = g;
        }
        const now = store.get(i);
        const bx = now.data[8];
        const by = now.data[9];
        let best = -1;
        let bestD = Infinity;
        for (let k = 0; k < this.source.header.players.length; k++) {
            if (!(now.playerFlags[k] & 1)) {
                continue;
            }
            const o = 15 + k * PLAYER_FLOATS;
            const d = Math.hypot(now.data[o] - bx, now.data[o + 1] - by);
            if (d < bestD) {
                bestD = d;
                best = k;
            }
        }
        return best;
    }

    playerLabel(k) {
        const p = this.source.header.players[k];
        const team = this.source.header.teams[p.team] || {};
        const roster = this.styles && this.styles[p.team] && this.styles[p.team].players
            ? this.styles[p.team].players[p.index] : null;
        const number = roster ? roster.number : (p.goalkeeper ? 1 : p.index + 1);
        const name = roster && roster.name ? roster.name : (p.goalkeeper ? t('main.player.goalkeeper') : t('main.player.numbered', { number: p.index + 1 }));
        return t('main.player.label', { number, name, team: teamName(team) });
    }

    // Frame loop.

    tick(now) {
        requestAnimationFrame((t) => this.tick(t));
        // A feed with a frame rate of its own skips the frames between, at an even pace.
        if (this.frameGate && !this.frameGate(now)) {
            return;
        }
        const dt = Math.min(0.1, (now - this.lastTime) / 1000);
        // Playback takes the whole time step up to a second, so a slow device still plays in real
        // time, while the cameras and the easing take the short one and stay steady.
        this.playDt = Math.min(1, Math.max(0, (now - this.lastTime) / 1000));
        this.lastTime = now;
        // Photo mode holds the moment and draws the view itself.
        if (this.photo && this.photo.isOpen && this.photo.frame(dt)) {
            return;
        }
        this.clock += dt;
        const tl = this.timeline;
        let ballPos = this.ballFocus || (this.ballFocus = new THREE.Vector3(0, 0, 0));
        if (tl && tl.store.size > 0 && this.players) {
            const before = tl.t;
            // A team's time suggestion freezes or slows play for a moment.
            tl.update(this.playDt * this.presentation.timeScale(this.playDt));
            // The card at the end of a recording goes once the view leaves the last frame, by a
            // seek, a step back or playing backwards.
            if (this.endCard && tl.t < tl.store.last - 0.5) {
                this.endCard = false;
                this.transition.title.hide();
            }
            this.director.update();
            this.transition.update(this.playDt);
            const s = tl.sample();
            if (s.index !== this.lastIndex) {
                this.onFrameChange(this.lastIndex, s.index, tl.t >= before);
                this.lastIndex = s.index;
            }
            this.pose.compute(s.a, s.b, s.w);
            // Hooks dress the pose before it is drawn, restarts walk players to their spots,
            // celebrations dance and the ball flies on after it leaves the pitch. Each takes the
            // pose, the sample and the time step and may change the pose in place.
            for (const hook of this.poseHooks) {
                hook(this.pose, s, dt);
            }
            this.presentation.update(dt, s);
            this.players.update(this.pose, s.a);
            this.ball.update(this.pose, dt * (tl.playing ? tl.speed : 1));
            this.presentation.afterPose(dt);
            this.hud.update(s.a);
            ballPos = this.ball.mesh.position;
            this.updateExcitement(s.a, dt);
            this.updateTimelineUi();
        }
        this.podium.update(dt);
        this.spotlight.update(dt);
        let follow = null;
        const label = $('follow-label');
        if (this.cameras.mode === 'orbit' && this.pose) {
            follow = this.director.focusPoint(this.pose);
        }
        if (this.cameras.mode === 'fpp' && this.source) {
            const k = this.cameras.focusIndex;
            const key = `${k}:${this.cameras.playerView}`;
            if (key !== this.followShown) {
                this.followShown = key;
                this.hud.followLabel(playerInfo(this, k), PLAYER_VIEWS[this.cameras.playerView]);
            }
            label.hidden = false;
        }
        if (this.cameras.mode === 'owner' && tl && tl.store.size > 0 && this.players) {
            const k = this.ownerAt(tl.index);
            if (k >= 0) {
                follow = this.players.position(this.pose, k, this.followPos || (this.followPos = new THREE.Vector3()));
                if (k !== this.followShown) {
                    this.followShown = k;
                    this.hud.followLabel(playerInfo(this, k), t('main.follow.onBall'));
                }
            }
            label.hidden = k < 0;
        } else if (!label.hidden && this.cameras.mode !== 'fpp') {
            label.hidden = true;
            this.followShown = -1;
        }
        this.cameras.idleSeconds = this.page === 'watch' && this.settings.idleReturn ? this.settings.idleSeconds : 0;
        this.cameras.update(dt, ballPos, this.players, this.pose || { players: 1 }, this.view.aspect, follow);
        this.sound.setListener(this.view.camera);
        this.playerTools.update();
        this.annotationOverlay.update();
        this.captions.update();
        // Sound plays on the pages that show a match, while it plays or while a show runs that the
        // viewer has not paused, and stops on every other page.
        const onStage = this.page === 'watch' || this.page === 'play';
        const showing = (this.director.running || this.postMatch.running) && !this.userPaused;
        const audible = !document.hidden && onStage && ((tl && tl.playing) || showing
            || this.clock < (this.soundHold || 0));
        this.sound.setActive(audible);
        this.stadium.update(this.clock, this.excitement, Math.min(1, this.goalBoost * 1.6));
        this.environment.update(dt);
        // Recordings and Teams cover the view, so it need not draw.
        // The 2D view draws the Watch page in place of the 3D picture when it is on.
        if ((this.page === 'watch' || this.page === 'field' || this.page === 'play') && !this.flat.draw(this.page)) {
            this.view.render();
        }
    }

    // Sounds and banners follow the frames crossed while playing forward at a normal pace. A
    // seek, a reverse or a cut only resets them.
    onFrameChange(from, to, forward) {
        const store = this.timeline.store;
        const steps = to - from;
        // A slow device plays several frames per draw, which is still play rather than a seek.
        const played = this.timeline.playing ? Math.ceil((this.playDt || 0) * this.timeline.speed * this.timeline.sps) + 2 : 0;
        const leap = Math.max(6, played);
        // Play that just stopped on the last frame still sounds the frames it crossed, the
        // final whistle among them.
        const ending = this.endReached;
        this.endReached = false;
        if (from < 0 || !forward || steps <= 0 || steps > leap || this.timeline.speed > 2.5 || !(this.timeline.playing || ending)) {
            if (from >= 0 && Math.abs(steps) > leap) {
                this.afterSeek();
            }
            return;
        }
        for (let j = from + 1; j <= to; j++) {
            const a = store.get(j - 1);
            const b = store.get(j);
            if (!a || !b) {
                continue;
            }
            if (isCut(a, b)) {
                if ((b.flags & EPISODE_START) && !(a.flags & 1)) {
                    this.fullTime(a, store.get(j - 2));
                }
                this.ball.reset();
                this.cameras.jump();
                continue;
            }
            if (b.scoreLeft > a.scoreLeft || b.scoreRight > a.scoreRight) {
                const team = b.scoreLeft > a.scoreLeft ? 0 : 1;
                if (!this.director.running) {
                    // A restart transition announces the goal as the ball crosses the line.
                    if (!this.transition.suppress(j, 'goal')) {
                        this.sound.goal(team);
                        this.goalBoost = 1;
                        this.hud.showGoal(team, true);
                    }
                    this.lastGoal = { index: j, team };
                    this.director.goalScored(j, team);
                }
            }
            const last = (b.flags & 1) && !(a.flags & 1);
            if (b.gameMode !== a.gameMode && b.gameMode > 0 && !last && !this.transition.suppress(j, 'whistle')) {
                this.sound.whistle([0.32]);
            }
            if (a.timeMs < HALF_TIME_MS && b.timeMs >= HALF_TIME_MS && this.transition.isHalfTime(j) && !this.transition.suppress(j, 'half')) {
                this.sound.whistle([0.45, 0.9]);
            }
            if (last) {
                this.fullTime(b, a);
            }
            // The engine's move of the ball to a restart is no kick.
            if (!this.transition.suppress(j, 'kick')) {
                this.detectKick(j);
                this.nearMiss(a, b);
                this.netTouch(a, b);
            }
            this.actionSounds(a, b);
        }
    }

    // The final whistle. A full match ends on three blasts. Any other episode ends on one long
    // blast where the referee stops play, at a goal or a restart, and quietly when it ends in
    // open play. The sound stays on while the whistle sounds, even with the timeline stopped.
    // A recording goes on to the show after the match, a live stream keeps playing and offers
    // the show on a button instead.
    fullTime(end = null, before = null) {
        const full = !!this.source && fullMatch(this.source.header);
        const goal = end && before && (end.scoreLeft !== before.scoreLeft || end.scoreRight !== before.scoreRight);
        const stopped = end && before && end.gameMode > 0 && end.gameMode !== before.gameMode;
        if (full || goal || stopped) {
            this.sound.whistle(full ? [0.4, 0.4, 1.3] : [0.9]);
            this.soundHold = this.clock + 4.5;
        }
        this.transition.fullTime();
        if (this.director.running || this.postMatch.running) {
            return;
        }
        if (this.source.kind === 'live') {
            $('post-show').hidden = !this.settings.podium;
            return;
        }
        const source = this.source;
        clearTimeout(this.fullTimeTimer);
        this.fullTimeTimer = setTimeout(() => {
            if (this.source === source) {
                this.postMatch.start();
            }
        }, 1500);
    }

    // The net bulges when the ball reaches it in play. The ball is in the goal when it is behind
    // the line, between the posts and under the bar, and it meets the net once it comes near the
    // back, a side or the roof, with the pace it carried in. A restart transition moves the ball
    // itself and bulges the net on its own.
    netTouch(a, b) {
        const x = Math.abs(b.data[8]);
        const y = Math.abs(b.data[9]);
        const z = b.data[10];
        if (x <= HALF_W || y >= GOAL_HALF_WIDTH || z >= GOAL_HEIGHT || this.transition.active || isCut(a, b)) {
            this.netEntry = null;
            return;
        }
        const sps = this.timeline.sps;
        const speed = Math.hypot(b.data[8] - a.data[8], b.data[9] - a.data[9], b.data[10] - a.data[10]) * sps;
        const entry = this.netEntry || (this.netEntry = { pace: 0, done: false });
        entry.pace = Math.max(entry.pace, speed);
        const near = x > HALF_W + GOAL_DEPTH - 0.8 || y > GOAL_HALF_WIDTH - 0.5 || z > GOAL_HEIGHT - 0.5;
        // A ball that slows sharply inside the goal has met the net too.
        if (entry.done || (!near && speed > entry.pace * 0.5) || entry.pace < 2) {
            return;
        }
        entry.done = true;
        const sx = Math.sign(b.data[8]);
        const at = new THREE.Vector3(sx * Math.min(x, HALF_W + GOAL_DEPTH), Math.max(0.1, z), -b.data[9]);
        try {
            this.pitch.netImpact(sx > 0 ? 1 : 0, at, Math.min(1, Math.max(0.1, entry.pace / 22)));
        } catch {
            // The net is a nicety.
        }
    }

    detectKick(j) {
        const store = this.timeline.store;
        const c = store.get(j);
        const b = store.get(j - 1);
        const a = store.get(j - 2);
        if (!a || !b || !c || isCut(a, b)) {
            return;
        }
        const sps = this.timeline.sps;
        const v1x = (b.data[8] - a.data[8]) * sps;
        const v1y = (b.data[9] - a.data[9]) * sps;
        const v2x = (c.data[8] - b.data[8]) * sps;
        const v2y = (c.data[9] - b.data[9]) * sps;
        const jump = Math.hypot(v2x - v1x, v2y - v1y);
        // A sudden change of the horizontal velocity near a player's height is a touch, a bounce
        // only flips the vertical part.
        // Near a post or the bar the change is the frame of the goal ringing.
        const bx = Math.abs(b.data[8]);
        const by = Math.abs(b.data[9]);
        const nearPost = Math.abs(bx - HALF_W) < 0.6 && b.data[10] < 2.7
            && (Math.abs(by - 3.7) < 0.6 || (by < 3.9 && b.data[10] > 2.1));
        if (jump > 4.5 && nearPost) {
            this.sound.ooh();
            return;
        }
        if (jump > 4.5 && b.data[10] < 2.4) {
            const p = new THREE.Vector3(b.data[8], b.data[10], -b.data[9]);
            const kicker = this.toucher(c) >= 0 ? this.toucher(c) : this.toucher(b);
            const team = kicker >= 0 ? this.source.header.players[kicker].team : -1;
            this.sound.teamSound(team, 'kick', p);
        }
    }

    // The player who kicked the ball during a frame's step, or -1.
    toucher(frame) {
        const touches = frame.touches;
        for (let k = 0; k < touches.length; k++) {
            if (touches[k] === TOUCH.kicked) {
                return k;
            }
        }
        return -1;
    }

    // A team's own sounds for what its players start doing on this step, a shot, a pass, a
    // tackle or a save, played where the player stands.
    actionSounds(a, b) {
        const players = this.source.header.players;
        for (let k = 0; k < players.length; k++) {
            const act = b.actions[k];
            if (act === a.actions[k] || !(b.playerFlags[k] & 1)) {
                continue;
            }
            let slot = null;
            if (act === ACTION.shot) {
                slot = 'shot';
            } else if (act === ACTION.shortPass || act === ACTION.longPass || act === ACTION.highPass) {
                slot = 'pass';
            } else if (act === ACTION.sliding) {
                slot = 'tackle';
            } else if ((act === ACTION.catch || act === ACTION.deflect) && players[k].goalkeeper) {
                slot = 'save';
            }
            if (slot) {
                const o = 15 + k * PLAYER_FLOATS;
                const p = new THREE.Vector3(b.data[o], 1, -b.data[o + 1]);
                this.sound.teamSound(players[k].team, slot, p);
            }
            // A save of a ball flying at the goal draws a groan from the arena.
            if (slot === 'save') {
                const toward = (b.data[8] - a.data[8]) * this.timeline.sps * (players[k].team === 0 ? -1 : 1);
                if (toward > 6) {
                    this.sound.ooh();
                }
            }
        }
    }

    // A ball crossing the goal line just wide of a post or just over the bar is a near miss.
    nearMiss(a, b) {
        const ax = Math.abs(a.data[8]);
        const bx = Math.abs(b.data[8]);
        const speed = Math.abs(b.data[8] - a.data[8]) * this.timeline.sps;
        if (ax > HALF_W || bx <= HALF_W || speed < 8 || speed > 60 || Math.sign(a.data[8]) !== Math.sign(b.data[8])) {
            return;
        }
        const k = (HALF_W - ax) / Math.max(1e-6, bx - ax);
        const y = Math.abs(a.data[9] + (b.data[9] - a.data[9]) * k);
        const z = a.data[10] + (b.data[10] - a.data[10]) * k;
        if ((y > 3.9 && y < 7 && z < 3.5) || (y <= 3.9 && z > 2.6 && z < 4.5)) {
            this.sound.ooh();
        }
    }

    updateExcitement(frame, dt) {
        const x = frame.data[8];
        const y = frame.data[9];
        const near = Math.max(0, 1 - (HALF_W - Math.abs(x)) / 35) * (1 - Math.min(1, Math.abs(y) / 40) * 0.5);
        let attack = 0;
        if (frame.ownedTeam >= 0) {
            const goalSide = frame.ownedTeam === 0 ? 1 : -1;
            attack = Math.max(0, (x * goalSide) / HALF_W);
        }
        const want = Math.min(1, 0.18 + 0.55 * near ** 1.5 + 0.25 * attack + this.goalBoost * 0.6);
        this.goalBoost = Math.max(0, this.goalBoost - dt / 8);
        this.excitement += (want - this.excitement) * (1 - Math.exp(-dt * 1.5));
        this.sound.setIntensity(this.timeline.playing ? this.excitement : this.excitement * 0.6);
    }

    afterSeek() {
        this.lastTransport = performance.now();
        this.sound.stopEvents();
        this.presentation.reset('seek');
        this.captions?.seeked();
        this.ball.reset();
        this.cameras.jump();
        this.hud.hideGoal();
        this.transition.afterSeek();
    }

    // Replays on request, the last goal from one camera chosen at random.
    replayGoal(goal) {
        const tl = this.timeline;
        if (!tl) {
            return;
        }
        goal = goal || this.lastGoal || tl.goalNear(-1);
        if (!goal) {
            this.hud.toast(t('main.replay.none'));
            return;
        }
        this.director.start(goal, 1);
        this.updatePlayUi();
    }

    endReplay(restore) {
        this.director.stop(restore);
    }

    // Transport.

    act(action) {
        const tl = this.timeline;
        if (!tl) {
            return;
        }
        if (this.director.running && action !== 'replay') {
            this.director.stop(false);
        }
        const jumpTo = (t) => {
            tl.seek(t);
            this.afterSeek();
        };
        switch (action) {
        case 'toggle':
            tl.toggle();
            this.userPaused = !tl.playing;
            break;
        case 'play':
            this.userPaused = false;
            tl.play(1);
            break;
        case 'reverse':
            this.userPaused = false;
            tl.play(-1);
            break;
        case 'pause':
            this.userPaused = true;
            tl.pause();
            break;
        case 'frame-back':
            tl.stepFrames(-1);
            this.afterSeek();
            break;
        case 'frame-forward':
            tl.stepFrames(1);
            this.afterSeek();
            break;
        case 'back-5':
            tl.skipSeconds(-5);
            this.afterSeek();
            break;
        case 'forward-5':
            tl.skipSeconds(5);
            this.afterSeek();
            break;
        case 'back-30':
            tl.skipSeconds(-30);
            this.afterSeek();
            break;
        case 'forward-30':
            tl.skipSeconds(30);
            this.afterSeek();
            break;
        case 'restart':
            jumpTo(tl.first);
            break;
        case 'end':
            if (tl.live) {
                tl.goLive();
                this.afterSeek();
            } else {
                jumpTo(tl.last);
                tl.pause();
            }
            break;
        case 'live':
            tl.goLive();
            this.afterSeek();
            break;
        case 'post-show':
            $('post-show').hidden = true;
            this.postMatch.start();
            break;
        case 'next-goal':
        case 'prev-goal': {
            const g = tl.goalNear(action === 'next-goal' ? 1 : -1, 6 * tl.sps);
            if (!g) {
                this.hud.toast(action === 'next-goal' ? t('main.goal.noLater') : t('main.goal.noEarlier'));
                break;
            }
            // Land a few seconds before the goal to see the move.
            jumpTo(Math.max(tl.first, g.index - 6 * tl.sps));
            this.lastGoal = g;
            break;
        }
        case 'replay':
            this.replayGoal();
            break;
        default:
            break;
        }
        this.updatePlayUi();
        this.updateHash();
    }

    setSpeed(index) {
        this.speedIndex = Math.max(0, Math.min(SPEEDS.length - 1, index));
        if (this.timeline) {
            this.timeline.speed = SPEEDS[this.speedIndex];
            if (this.timeline.live && this.timeline.following && this.timeline.speed !== 1) {
                this.timeline.following = false;
            }
        }
        $('speed').value = String(SPEEDS[this.speedIndex]);
    }

    // J, K and L like video editors, repeated presses speed up in that direction.
    shuttle(direction) {
        const tl = this.timeline;
        if (!tl) {
            return;
        }
        if (tl.playing && tl.direction === direction) {
            this.setSpeed((this.speedIndex ?? 2) + 1);
        } else {
            this.setSpeed(2);
            this.act(direction > 0 ? 'play' : 'reverse');
        }
        this.updatePlayUi();
    }

    // UI.

    bindControls() {
        for (const b of document.querySelectorAll('[data-act]')) {
            b.addEventListener('click', () => {
                this.sound.unlock();
                this.act(b.dataset.act);
            });
        }
        $('speed').addEventListener('change', () => this.setSpeed(SPEEDS.indexOf(Number($('speed').value))));
        $('live-env').addEventListener('submit', (e) => {
            e.preventDefault();
            this.switchEnvironment();
        });
        // Camera, quality and theme live in the View menu, the rest of the settings and the
        // help open from the bar, each as a dropdown.
        this.menus = bindTopMenus(this, { CAMERA_MODES, api, scorerAt });
        $('idle-return').addEventListener('change', () => {
            this.settings.idleReturn = $('idle-return').checked;
            save('idleReturn', this.settings.idleReturn);
        });
        $('idle-seconds').addEventListener('change', () => {
            const s = Math.round(Number($('idle-seconds').value));
            this.settings.idleSeconds = Number.isFinite(s) ? Math.min(300, Math.max(5, s)) : 20;
            $('idle-seconds').value = String(this.settings.idleSeconds);
            save('idleSeconds', this.settings.idleSeconds);
        });
        $('volume').addEventListener('input', () => {
            this.settings.volume = Number($('volume').value);
            this.sound.setVolume(this.settings.volume);
            if (this.settings.muted && this.settings.volume > 0) {
                this.setMuted(false);
            }
            save('volume', this.settings.volume);
        });
        $('mute').addEventListener('click', () => {
            this.sound.unlock();
            this.setMuted(!this.settings.muted);
        });
        $('trail').addEventListener('change', () => this.setTrail($('trail').checked));
        $('theme').value = this.settings.theme;
        $('theme').addEventListener('change', () => {
            this.settings.theme = $('theme').value;
            save('theme', this.settings.theme);
            applyTheme(this.settings.theme);
        });
        $('pointer-lock').checked = this.settings.pointerLock;
        $('pointer-lock').addEventListener('change', () => {
            this.settings.pointerLock = $('pointer-lock').checked;
            save('pointerLock', this.settings.pointerLock);
            this.cameras.allowLock = this.settings.pointerLock;
            if (!this.settings.pointerLock) {
                this.releasePointer();
            }
        });
        $('saved-style').addEventListener('change', () => {
            this.settings.savedStyle = $('saved-style').checked;
            save('savedStyle', this.settings.savedStyle);
            this.rebuildPlayers();
        });
        $('replays').addEventListener('change', () => {
            this.settings.replays = $('replays').checked;
            save('replays', this.settings.replays);
        });
        for (const [id, key] of [['restart-transitions', 'transitions'], ['decision-replays', 'decisionReplays']]) {
            const box = $(id);
            if (box) {
                box.addEventListener('change', () => {
                    this.settings[key] = box.checked;
                    save(key, box.checked);
                });
            }
        }
        $('slowmo').addEventListener('change', () => {
            this.settings.slowmo = $('slowmo').value;
            save('slowmo', this.settings.slowmo);
        });
        $('podium-on').addEventListener('change', () => {
            this.settings.podium = $('podium-on').checked;
            save('podium', this.settings.podium);
        });
        $('classic').addEventListener('change', () => {
            this.settings.classic = $('classic').checked;
            save('classic', this.settings.classic);
            this.pitch.setClassic(this.settings.classic, null);
            this.rebuildPlayers();
        });
        $('fullscreen').addEventListener('click', () => this.toggleFullscreen());
        $('help-close').addEventListener('click', () => this.showPage(this.helpReturn || 'home'));
        $('open-help').addEventListener('click', () => this.showPage('help'));
        $('open-file').addEventListener('click', () => $('file-input').click());
        $('file-input').addEventListener('change', () => {
            const f = $('file-input').files[0];
            if (f) {
                this.openFile(f);
            }
            $('file-input').value = '';
        });
        $('goal-replay').addEventListener('click', () => this.act('replay'));
        document.addEventListener('fullscreenchange', () => {
            $('app').classList.toggle('fullscreen', !!document.fullscreenElement);
        });
        this.bindScrubber();
        window.addEventListener('pointerdown', () => this.sound.unlock(), { once: false, passive: true });
    }

    bindScrubber() {
        const track = $('timeline');
        let dragging = false;
        let wasPlaying = false;
        const seekAt = (clientX) => {
            const tl = this.timeline;
            if (!tl) {
                return;
            }
            const r = track.getBoundingClientRect();
            const f = Math.max(0, Math.min(1, (clientX - r.left) / r.width));
            tl.seek(tl.first + f * (tl.last - tl.first));
            this.afterSeek();
        };
        // The viewer's own use of the transport, which a team's camera and time suggestions yield to.
        for (const type of ['pointerdown', 'keydown']) {
            $('controls').addEventListener(type, () => {
                this.lastTransport = performance.now();
            }, true);
        }
        track.addEventListener('pointerdown', (e) => {
            if (!this.timeline) {
                return;
            }
            dragging = true;
            wasPlaying = this.timeline.playing && !this.timeline.following;
            this.timeline.playing = false;
            this.timeline.following = false;
            track.setPointerCapture(e.pointerId);
            seekAt(e.clientX);
        });
        track.addEventListener('pointermove', (e) => {
            const r = track.getBoundingClientRect();
            const f = Math.max(0, Math.min(1, (e.clientX - r.left) / r.width));
            const tip = $('timeline-tip');
            if (this.timeline) {
                const tl = this.timeline;
                tip.textContent = formatSeconds((f * (tl.last - tl.first)) / tl.sps);
                tip.style.left = `${f * 100}%`;
            }
            if (dragging) {
                seekAt(e.clientX);
            }
        });
        const end = () => {
            if (dragging) {
                dragging = false;
                if (wasPlaying && this.timeline) {
                    this.timeline.playing = true;
                }
                this.updateHash();
                this.updatePlayUi();
            }
        };
        track.addEventListener('pointerup', end);
        track.addEventListener('pointercancel', end);
        track.addEventListener('keydown', (e) => {
            if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
                e.stopPropagation();
                e.preventDefault();
                this.act(e.key === 'ArrowLeft' ? (e.shiftKey ? 'back-30' : 'back-5') : (e.shiftKey ? 'forward-30' : 'forward-5'));
            }
        });
    }

    bindKeys() {
        window.addEventListener('keydown', (e) => {
            this.sound.unlock();
            const textField = e.target.closest('input, select, textarea, [contenteditable]');
            const control = e.target.closest(OWN_KEYS);
            if (e.defaultPrevented || textField || keepsKey(control, e.key, e)) {
                return;
            }
            const picture = e.target.closest('#stage, #field-preview');
            const look = ['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(e.key);
            if (picture && ['watch', 'field'].includes(this.page) &&
                ((look && (this.page === 'field' || e.altKey)) || ['+', '=', '-'].includes(e.key))) {
                e.preventDefault();
                if (this.page === 'field') {
                    this.fieldPage.stopFlight();
                }
                this.cameras.setMode('free');
                this.cameras.flight = null;
                const amount = e.shiftKey ? 0.15 : 0.05;
                if (look) {
                    this.cameras.yaw += e.key === 'ArrowLeft' ? amount :
                        e.key === 'ArrowRight' ? -amount : 0;
                    this.cameras.pitch = Math.max(-1.4, Math.min(1.4, this.cameras.pitch +
                        (e.key === 'ArrowUp' ? amount : e.key === 'ArrowDown' ? -amount : 0)));
                } else {
                    this.cameras.fov = Math.max(15, Math.min(100,
                        this.cameras.fov + (e.key === '-' ? 3 : -3)));
                }
                return;
            }
            const flyKey = e.key.length === 1 && 'wasdqec'.includes(e.key.toLowerCase());
            if (this.page === 'field' && flyKey && !e.ctrlKey && !e.metaKey && !e.altKey && !document.querySelector('dialog[open]')) {
                // The preview of the Field page flies the free camera.
                if (this.cameras.mode !== 'free') {
                    this.cameras.setMode('free');
                }
                this.cameras.press(e.key.toLowerCase(), true, e.shiftKey);
                e.preventDefault();
                return;
            }
            if (['h', 'H', '?'].includes(e.key) && !e.ctrlKey && !e.metaKey && !e.altKey) {
                e.preventDefault();
                this.showPage('help');
                return;
            }
            if (this.page === 'help' && e.key === 'Escape') {
                e.preventDefault();
                this.showPage(this.helpReturn || 'home');
                return;
            }
            if (this.page !== 'watch' || document.querySelector('dialog[open]')) {
                return;
            }
            if (e.ctrlKey || e.metaKey || e.altKey) {
                return;
            }
            const tl = this.timeline;
            const k = e.key;
            const lower = k.length === 1 ? k.toLowerCase() : k;
            let handled = true;
            if ('wasdqec'.includes(lower) && lower.length === 1) {
                // Moving starts the free camera from the current view, unless a follow camera
                // is on, where the keys move its offset instead.
                if (!['free', 'ball', 'owner'].includes(this.cameras.mode)) {
                    this.setCamera('free');
                }
                this.cameras.press(lower, true, e.shiftKey);
            } else if (lower === 'b') {
                this.setCamera('ball');
            } else if (lower === 'p') {
                this.setCamera('owner');
            } else if (k === ' ') {
                this.act('toggle');
            } else if (k === 'k' || k === 'K') {
                this.act('pause');
            } else if (k === 'l' || k === 'L') {
                this.shuttle(1);
            } else if (k === 'j' || k === 'J') {
                this.shuttle(-1);
            } else if (k === 'ArrowLeft' || k === 'ArrowRight') {
                const back = k === 'ArrowLeft';
                if (e.shiftKey) {
                    this.act(back ? 'back-30' : 'forward-30');
                } else if (tl && !tl.playing) {
                    this.act(back ? 'frame-back' : 'frame-forward');
                } else {
                    this.act(back ? 'back-5' : 'forward-5');
                }
            } else if (k === ',' || k === '<') {
                this.act('frame-back');
            } else if (k === '.' || k === '>') {
                this.act('frame-forward');
            } else if (k === 'ArrowUp') {
                this.setSpeed((this.speedIndex ?? 2) + 1);
            } else if (k === 'ArrowDown') {
                this.setSpeed((this.speedIndex ?? 2) - 1);
            } else if (k === 'Home') {
                this.act('restart');
            } else if (k === 'End') {
                this.act('end');
            } else if (lower === 'n') {
                this.act(e.shiftKey ? 'prev-goal' : 'next-goal');
            } else if ((k === 'r' || k === 'R') && e.shiftKey) {
                // More angles of the goal just replayed, or of the last goal.
                this.director.moreAngles();
            } else if (k === 'r' || k === 'R') {
                this.act('replay');
            } else if (/^Digit[0-9]$/.test(e.code)) {
                // Player views. 1 to 9 and 0 pick the left team's outfield players from the back
                // line forward, with Shift the right team's.
                const digit = Number(e.code.slice(5));
                this.firstPerson(e.shiftKey ? 1 : 0, digit === 0 ? 10 : digit);
            } else if (lower === 'g') {
                this.firstPerson(e.shiftKey ? 1 : 0, 0);
            } else if (lower === 'v') {
                const order = ['broadcast', 'tactical', 'goal', 'player', 'free'];
                this.setCamera(order[(order.indexOf(this.cameras.mode) + 1) % order.length]);
                this.hud.toast(CAMERA_MODES.find((m) => m.id === this.cameras.mode).label, 'info', 1200);
            } else if (k === 'Escape' && this.tvMode && !this.tvPeeking() && (this.transition.skippable || this.postMatch.running || this.director.running)) {
                // In broadcast mode Esc first brings the controls back, a second press goes on.
                this.peekControls();
            } else if ((k === 'Enter' || k === 'Escape') && this.transition.skippable) {
                this.transition.skip();
            } else if (k === 'Enter' && this.postMatch.running) {
                this.postMatch.skip();
            } else if (k === 'Enter' && this.director.running) {
                this.director.skip();
            } else if (k === '[' || k === ']') {
                this.cameras.followIndex += k === ']' ? 1 : -1;
                if (this.cameras.mode !== 'player') {
                    this.setCamera('player');
                }
                this.announcePlayer();
            } else if (k === 'f' || k === 'F') {
                this.toggleFullscreen();
            } else if (k === 'm' || k === 'M') {
                this.setMuted(!this.settings.muted);
            } else if (k === 't' || k === 'T') {
                this.setTvMode(!this.tvMode);
            } else if (k === 'h' || k === 'H' || k === '?') {
                this.toggleHelp();
            } else if (k === 'Escape') {
                if (this.postMatch.running) {
                    this.postMatch.end();
                } else if (this.director.running) {
                    this.director.stop(true);
                } else if (this.tvMode && this.cameras.mode !== 'fpp') {
                    // The controls show at the first press, the second leaves broadcast mode.
                    if (this.tvPeeking()) {
                        this.setTvMode(false);
                    } else {
                        this.peekControls();
                    }
                } else {
                    this.leavePlayerCamera();
                }
                this.toggleHelp(false);
                $('settings').classList.remove('open');
                if (document.pointerLockElement) {
                    document.exitPointerLock();
                }
            } else {
                handled = false;
            }
            if (handled) {
                e.preventDefault();
                this.poke();
            }
        });
        window.addEventListener('keyup', (e) => {
            const lower = e.key.length === 1 ? e.key.toLowerCase() : e.key;
            if ('wasdqec'.includes(lower) && lower.length === 1) {
                this.cameras.press(lower, false, e.shiftKey);
            } else if (e.key === 'Shift') {
                this.cameras.fast = false;
            }
        });
        window.addEventListener('blur', () => this.cameras.releaseAll());
    }

    announcePlayer() {
        if (!this.source) {
            return;
        }
        const n = this.source.header.players.length;
        const k = ((this.cameras.followIndex % n) + n) % n;
        const p = this.source.header.players[k];
        this.hud.toast(t('main.follow.player', { player: this.playerLabel(k) }), 'info', 1800);
        void p;
    }

    // Player cameras. Slot 0 is the keeper, slots 1 to 10 the outfield players in roster order.
    // Pressing the same player's key again cycles first person, over the shoulder, side and
    // face, and the view is kept when switching to another player.
    firstPerson(team, slot) {
        if (!this.source) {
            return;
        }
        const players = this.source.header.players;
        const keeper = players.findIndex((p) => p.team === team && p.goalkeeper);
        const outfield = this.lineup(team);
        const k = slot === 0 ? keeper : (outfield[slot - 1] !== undefined ? outfield[slot - 1] : -1);
        if (k < 0) {
            const size = players.filter((p) => p.team === team).length;
            const words = [t('main.teamSize.0'), t('main.teamSize.1'), t('main.teamSize.2'), t('main.teamSize.3'), t('main.teamSize.4'), t('main.teamSize.5'),
                t('main.teamSize.6'), t('main.teamSize.7'), t('main.teamSize.8'), t('main.teamSize.9'), t('main.teamSize.10'), t('main.teamSize.11')];
            const sized = words[size] || size;
            this.hud.toast(slot === 0 ? t('main.firstPerson.noGoalkeeper', { team: sized }) : t('main.firstPerson.noPlayer', { player: slot % 10, team: sized }), 'info', 1800);
            return;
        }
        const cams = this.cameras;
        if (cams.mode === 'fpp' && cams.focusIndex === k) {
            cams.playerView = (cams.playerView + 1) % PLAYER_VIEWS.length;
        } else if (cams.mode !== 'fpp') {
            this.beforeFirstPerson = cams.mode;
        }
        cams.focusIndex = k;
        cams.setMode('fpp');
        this.followShown = -1;
    }

    // Outfield players as lineups list them, from the back line forward, each line from the
    // team's left to its right. GRF lines every team up at its formation spots for each kickoff,
    // so the places come from such a frame, one where the team does not take the kickoff when
    // there is one, since its kickers stand on the spot. Without a kickoff in the frames, as in a
    // live stream joined late, the places are averaged over open play. The order is kept per
    // match until a live store has doubled.
    lineup(team) {
        const store = this.timeline ? this.timeline.store : null;
        const size = store ? store.size : 0;
        const c = this.lineups;
        if (c && c.source === this.source && size < c.size * 2 + 10) {
            return c.teams[team];
        }
        const kickoffs = store && size ? this.kickoffFrames(store) : [];
        this.lineups = { source: this.source, size, teams: [0, 1].map((t) => this.orderTeam(t, store, kickoffs)) };
        return this.lineups.teams[team];
    }

    // Frames with both teams at their kickoff places, the ball on the center spot and every
    // player in their own half, looked for at the start, after cuts and after goals.
    kickoffFrames(store) {
        const players = this.source.header.players;
        const lined = (f) => Math.abs(f.data[8]) < 1 && Math.abs(f.data[9]) < 1 && players.every((p, k) => {
            const x = f.data[15 + k * PLAYER_FLOATS] * (p.team === 0 ? 1 : -1);
            return !(f.playerFlags[k] & 1) || x < 0.6;
        });
        const out = [];
        let prev = null;
        let look = 0;
        for (let i = store.first; i <= store.last; i++) {
            const f = store.get(i);
            if (!f) {
                continue;
            }
            if (!prev || isCut(prev, f) || f.scoreLeft !== prev.scoreLeft || f.scoreRight !== prev.scoreRight) {
                look = 3;
            }
            if (look > 0) {
                look--;
                if (lined(f)) {
                    out.push(f);
                    look = 0;
                }
            }
            prev = f;
        }
        return out;
    }

    orderTeam(team, store, kickoffs) {
        const players = this.source.header.players;
        const attack = team === 0 ? 1 : -1;
        const list = players.map((p, k) => ({ p, k })).filter((x) => x.p.team === team && !x.p.goalkeeper)
            .map((x) => ({ k: x.k, depth: 0, side: 0, n: 0, fallback: x.p.index }));
        // The kickers of a kickoff stand within about two meters of the center spot.
        const kicking = (f) => list.some((x) => Math.hypot(f.data[15 + x.k * PLAYER_FLOATS], f.data[16 + x.k * PLAYER_FLOATS]) < 2.2);
        const lineupFrame = kickoffs.find((f) => !kicking(f)) || kickoffs[0];
        let frames = lineupFrame ? [lineupFrame] : [];
        if (!lineupFrame && store && store.size) {
            const count = Math.min(160, store.size);
            for (let i = 0; i < count; i++) {
                const f = store.get(store.first + Math.floor((i * (store.size - 1)) / Math.max(1, count - 1)));
                if (f) {
                    frames.push(f);
                }
            }
            const play = frames.filter((f) => f.gameMode === 0);
            frames = play.length >= 5 ? play : frames;
        }
        for (const f of frames) {
            for (const x of list) {
                if (!(f.playerFlags[x.k] & 1)) {
                    continue;
                }
                const o = 15 + x.k * PLAYER_FLOATS;
                x.depth += f.data[o] * attack;
                x.side += f.data[o + 1] * attack;
                x.n++;
            }
        }
        for (const x of list) {
            if (x.n) {
                x.depth /= x.n;
                x.side /= x.n;
            } else {
                x.depth = x.fallback;
            }
        }
        list.sort((a, b) => a.depth - b.depth);
        // A new line starts at a gap in depth that is large for this team, a fifth of the depth
        // from the deepest to the most advanced player and at least 2.5 meters, so the close
        // lines of five a side split as well as the wide ones of eleven.
        const spread = list.length > 1 ? list[list.length - 1].depth - list[0].depth : 0;
        const gap = Math.max(2.5, spread * 0.2);
        const lines = [];
        for (const x of list) {
            const line = lines[lines.length - 1];
            if (line && x.depth - line[line.length - 1].depth < gap) {
                line.push(x);
            } else {
                lines.push([x]);
            }
        }
        return lines.flatMap((line) => line.sort((a, b) => b.side - a.side)).map((x) => x.k);
    }

    leavePlayerCamera() {
        if (this.cameras.mode === 'fpp') {
            this.setCamera(this.beforeFirstPerson || 'broadcast');
        }
    }

    bindDrop() {
        const hint = $('drop-hint');
        let depth = 0;
        window.addEventListener('dragenter', (e) => {
            if (e.dataTransfer && Array.from(e.dataTransfer.types).includes('Files')) {
                depth++;
                hint.classList.add('show');
            }
        });
        window.addEventListener('dragleave', () => {
            depth = Math.max(0, depth - 1);
            if (depth === 0) {
                hint.classList.remove('show');
            }
        });
        window.addEventListener('dragover', (e) => e.preventDefault());
        window.addEventListener('drop', (e) => {
            e.preventDefault();
            depth = 0;
            hint.classList.remove('show');
            const file = e.dataTransfer && e.dataTransfer.files[0];
            if (!file) {
                return;
            }
            if (/\.glb$/i.test(file.name)) {
                this.hud.toast(t('main.drop.model'), 'info', 6000);
                return;
            }
            this.openFile(file);
        });
    }

    // The interface fades while playing or in fullscreen once the pointer rests.
    bindIdle() {
        const wake = () => this.poke();
        for (const ev of ['pointermove', 'pointerdown', 'wheel', 'touchstart', 'focusin']) {
            window.addEventListener(ev, wake, { passive: true });
        }
        this.poke();
    }

    poke() {
        const app = $('app');
        app.classList.remove('idle');
        clearTimeout(this.idleTimer);
        this.idleTimer = setTimeout(() => {
            const playing = this.timeline && this.timeline.playing;
            const busy = this.postMatch.running || this.page !== 'watch' || $('help').classList.contains('open') || $('settings').classList.contains('open')
                || document.querySelector('#controls:hover, #topbar:hover, #watch-bar:focus-within, .dd-panel.open')
                || keyboardFocusIn('#controls');
            if ((playing || document.fullscreenElement) && !busy) {
                app.classList.add('idle');
            }
        }, 2600);
    }

    // Gives the mouse back, the pointer free and the cursor shown. Locking again is left to the
    // user, a right click in the free camera.
    releasePointer() {
        if (document.pointerLockElement) {
            document.exitPointerLock();
        }
        $('app').classList.remove('idle');
    }

    // Whatever asks for a click or a key releases the pointer, a menu, a dialog, a details panel,
    // the panel of an expanded button, a confirm or a prompt, the editor, the lineups, the cards
    // after the match, any element marked with data-prompt, and focus on a control. The check
    // runs only while the pointer is locked, so it costs nothing else.
    bindPointerRelease() {
        let queued = false;
        const check = () => {
            queued = false;
            // Only what shows counts, the editor on a hidden page does not.
            if (document.pointerLockElement && openPanel()) {
                this.releasePointer();
            }
        };
        new MutationObserver(() => {
            if (document.pointerLockElement && !queued) {
                queued = true;
                setTimeout(check, 0);
            }
        }).observe(document.body, {
            subtree: true, childList: true, attributes: true,
            attributeFilter: ['class', 'hidden', 'open', 'style', 'aria-expanded'],
        });
        // Focus that moves to a control, by Tab or by script, wants the pointer as well.
        document.addEventListener('focusin', (e) => {
            const locked = document.pointerLockElement;
            if (locked && e.target instanceof Element && !e.target.contains(locked)) {
                this.releasePointer();
            }
        });
        // Something that opened while the pointer was free is caught when the lock begins.
        document.addEventListener('pointerlockchange', () => {
            if (document.pointerLockElement) {
                setTimeout(check, 0);
            }
        });
        // A pointer captured by a page that is not in front confines the cursor of the whole
        // desktop, so losing focus, hiding or closing the page always releases it.
        const release = () => this.releasePointer();
        window.addEventListener('blur', release);
        window.addEventListener('pagehide', release);
        window.addEventListener('beforeunload', release);
        document.addEventListener('visibilitychange', () => {
            if (document.hidden) {
                release();
            }
        });
        setInterval(() => {
            if (document.pointerLockElement && (!document.hasFocus() || !this.settings.pointerLock)) {
                release();
            }
        }, 500);
        for (const name of ['confirm', 'prompt', 'alert']) {
            const native = window[name].bind(window);
            window[name] = (...args) => {
                this.releasePointer();
                return native(...args);
            };
        }
    }

    // Broadcast mode, the Watch page with the picture and its own graphics alone, full window.
    setTvMode(on, quiet = false) {
        this.tvMode = !!on;
        this.settings.tvMode = this.tvMode;
        save('tvMode', this.tvMode);
        const app = $('app');
        app.classList.toggle('tv', this.tvMode);
        app.classList.remove('tv-peek');
        clearTimeout(this.tvPeekTimer);
        clearTimeout(this.tvHintTimer);
        if ($('tv-mode')) {
            $('tv-mode').checked = this.tvMode;
        }
        if (this.menus) {
            for (const m of Object.values(this.menus)) {
                if (m && typeof m.close === 'function' && this.tvMode) {
                    m.close();
                }
            }
        }
        app.classList.toggle('tv-hint', this.tvMode && !quiet);
        if (this.tvMode && !quiet) {
            this.tvHintTimer = setTimeout(() => app.classList.remove('tv-hint'), 3200);
        }
        if (!this.tvMode) {
            this.hud.toast(t('main.tv.off'), 'info', 1200);
        }
        this.poke();
    }

    tvPeeking() {
        return $('app').classList.contains('tv-peek');
    }

    // The controls for a moment, kept while the pointer is over them or a menu of theirs is open.
    peekControls(seconds = 3) {
        if (!this.tvMode) {
            return;
        }
        const app = $('app');
        app.classList.add('tv-peek');
        app.classList.remove('tv-hint');
        clearTimeout(this.tvPeekTimer);
        const hide = () => {
            if (document.querySelector('#controls:hover, #controls:focus-within, .dd-panel.open')) {
                this.tvPeekTimer = setTimeout(hide, 800);
                return;
            }
            app.classList.remove('tv-peek');
        };
        this.tvPeekTimer = setTimeout(hide, seconds * 1000);
    }

    bindTv() {
        const box = $('tv-mode');
        if (box) {
            box.addEventListener('change', () => this.setTvMode(box.checked));
        }
        // The bottom edge of the window brings the controls back.
        window.addEventListener('pointermove', (e) => {
            if (this.tvMode && this.page === 'watch' && e.clientY > window.innerHeight - 56) {
                this.peekControls(2.5);
            }
        }, { passive: true });
        if (this.settings.tvMode) {
            this.setTvMode(true, true);
        }
    }

    toggleHelp(force) {
        if (force === false) {
            return;
        }
        this.showPage('help');
    }

    toggleFullscreen() {
        if (document.fullscreenElement) {
            document.exitFullscreen().catch(() => {});
        } else {
            $('app').requestFullscreen().catch((err) => this.hud.toast(t('main.fullscreen.failed', { reason: err.message }), 'error'));
        }
    }

    // Only the wide views are remembered, so a match always opens on the whole pitch rather than
    // locked to a player, the ball or a free camera left somewhere from an earlier visit.
    setCamera(mode) {
        this.cameras.setMode(mode);
        if (REMEMBERED_CAMERAS.has(mode)) {
            this.settings.camera = mode;
            save('camera', mode);
        }
    }

    setQuality(q) {
        this.settings.quality = q;
        save('quality', q);
        this.view.setQuality(q);
        this.pitch.setQuality(q);
        this.stadium.setQuality(q);
        this.environment.setQuality(q);
    }

    setMuted(m) {
        this.settings.muted = m;
        save('muted', m);
        this.sound.setMuted(m);
        $('mute').setAttribute('aria-pressed', m ? 'true' : 'false');
        $('mute').classList.toggle('muted', m);
        $('mute').title = m ? t('main.mute.off') : t('main.mute.on');
    }

    setTrail(on) {
        this.settings.trail = on;
        save('trail', on);
        this.ball.setTrail(on && !this.reducedMotion);
        $('trail').checked = on;
    }

    syncSettingsUi() {
        $('idle-return').checked = this.settings.idleReturn;
        $('idle-seconds').value = String(this.settings.idleSeconds);
        $('volume').value = String(this.settings.volume);
        $('trail').checked = this.settings.trail;
        $('saved-style').checked = this.settings.savedStyle;
        $('classic').checked = this.settings.classic;
        $('replays').checked = this.settings.replays;
        if ($('restart-transitions')) {
            $('restart-transitions').checked = this.settings.transitions;
            $('decision-replays').checked = this.settings.decisionReplays;
        }
        $('slowmo').value = String(this.settings.slowmo);
        $('podium-on').checked = this.settings.podium;
        $('speed').value = '1';
        this.setMuted(this.settings.muted);
    }

    showEmpty(on) {
        $('watch-empty').hidden = !on;
        $('app').classList.toggle('no-source', on);
        if (on) {
            this.hud.hide();
        }
    }

    // A message and a bar over the view, the bar full width and moving when the share is unknown.
    showLoading(text, fraction = null) {
        $('loading-text').textContent = text;
        const bar = $('loading-bar');
        bar.parentElement.classList.toggle('waiting', fraction == null);
        bar.style.width = fraction == null ? '' : `${Math.round(Math.max(0, Math.min(1, fraction)) * 100)}%`;
        $('loading').hidden = false;
    }

    hideLoading() {
        $('loading').hidden = true;
    }

    updatePlayUi() {
        const tl = this.timeline;
        const playing = tl && tl.playing;
        $('app').classList.toggle('playing', !!playing);
        $('btn-play').classList.toggle('active', !!(playing && tl.direction > 0));
        $('btn-reverse').classList.toggle('active', !!(playing && tl.direction < 0));
        $('btn-pause').classList.toggle('active', !playing);
        if (tl) {
            $('speed').value = String(tl.speed);
        }
        this.poke();
    }

    updateLiveUi() {
        const tl = this.timeline;
        const live = tl && tl.live;
        $('live-box').hidden = !live;
        if (!live) {
            return;
        }
        const ended = this.source.live && (this.source.live.ended || this.source.live.failed);
        const behind = tl.behindLive;
        const atEdge = tl.following || behind < 1;
        $('go-live').hidden = atEdge && !ended;
        $('go-live').disabled = ended;
        $('go-live').title = ended ? t('main.live.goLive.ended') : t('main.live.goLive');
        const connection = this.source.live;
        let state = ended ? t('main.live.state.ended') : atEdge ? t('main.live.state.live') : t('main.live.state.behind', { time: formatSeconds(behind) });
        if (connection && connection.failed) {
            state = t('main.live.state.disconnected');
        } else if (connection && connection.state === 'reconnecting') {
            state = t('main.live.state.reconnecting');
        }
        // Frames lost while the stream reconnected show as cuts, and their count stays here.
        if (connection && connection.gaps) {
            state = t('main.live.state.lost', { state, count: connection.gaps });
        }
        $('live-state').textContent = state;
        // The symbol beside the state shows it at a glance, the text says it in words.
        const symbol = connection && connection.failed ? 'alert' : connection && connection.state === 'reconnecting' ? 'running'
            : ended ? 'stop' : atEdge ? 'live' : 'clock';
        $('live-state-icon')?.querySelector('use')?.setAttribute('href', `#i-${symbol}`);
        // A source on this server with several environments may show another, and the control
        // stays while a switch it asked for ends this stream.
        const header = this.source.header;
        const switchable = !this.source.game && connection && !connection.url
            && (header.environment_count || 1) > 1 && (!ended || this.switchingLive === connection);
        $('live-env').hidden = !switchable;
        if (switchable && this.environmentSource !== this.source) {
            this.environmentSource = this.source;
            $('live-env-index').max = String(header.environment_count - 1);
            $('live-env-index').value = String((header.provenance && header.provenance.environment) || 0);
        }
        $('live-box').classList.toggle('at-edge', atEdge && !ended);
        if (this.grid) {
            this.grid.update();
        }
    }

    renderMarkers() {
        const box = $('timeline-markers');
        box.replaceChildren();
        this.markerCount = -1;
        this.markerBase = -1;
    }

    updateTimelineUi() {
        const tl = this.timeline;
        const span = Math.max(1, tl.last - tl.first);
        const f = (tl.t - tl.first) / span;
        $('timeline-fill').style.width = `${f * 100}%`;
        $('timeline-thumb').style.left = `${f * 100}%`;
        const now = formatSeconds((tl.t - tl.first) / tl.sps);
        const total = formatSeconds(span / tl.sps);
        $('time-now').textContent = now;
        $('time-total').textContent = total;
        // The slider says where it stands, set again only when the second shown changes.
        const position = t('main.timeline.position', { now, total });
        if (this.timelineText !== position) {
            this.timelineText = position;
            const bar = $('timeline');
            bar.setAttribute('aria-valuemin', '0');
            bar.setAttribute('aria-valuemax', String(Math.round(span / tl.sps)));
            bar.setAttribute('aria-valuenow', String(Math.round((tl.t - tl.first) / tl.sps)));
            bar.setAttribute('aria-valuetext', this.timelineText);
        }
        // A match of a tournament watched without spoilers keeps its goals off the timeline.
        const goals = hidesOutcome(this.source.header && this.source.header.provenance) ? [] : tl.store.goals;
        const box = $('timeline-markers');
        if (tl.live && goals.length === this.markerCount && tl.first === this.markerBase) {
            // Live timelines stretch as frames arrive, so their markers slide along.
            goals.forEach((g, i) => {
                box.children[i].style.left = `${((g.index - tl.first) / span) * 100}%`;
            });
        } else if (goals.length !== this.markerCount || tl.first !== this.markerBase) {
            this.markerCount = goals.length;
            this.markerBase = tl.first;
            const nodes = goals.map((g) => {
                const m = document.createElement('button');
                m.className = `marker team-${g.team}`;
                m.style.left = `${((g.index - tl.first) / span) * 100}%`;
                m.title = t('main.timeline.goal', { team: teamName(this.source.header.teams[g.team]) });
                m.addEventListener('pointerdown', (e) => e.stopPropagation());
                m.addEventListener('click', () => {
                    tl.seek(Math.max(tl.first, g.index - 6 * tl.sps));
                    this.lastGoal = g;
                    this.afterSeek();
                });
                return m;
            });
            box.replaceChildren(...nodes);
        }
        if (tl.live) {
            this.updateLiveUi();
        }
        this.updateHash();
    }

    // The URL hash names a match and a time in seconds, or a live source, so a moment can be
    // shared.
    // The page writes the hash only when it changes, at most once a second while a match plays,
    // and leaves a hash that someone else wrote alone until its hashchange has opened it.
    updateHash(force = false) {
        if (!force && location.hash !== (this.ownHash || '') && location.hash !== (this.openedHash || '')) {
            return;
        }
        if (this.page !== 'watch' || !this.source || this.source.kind === 'file' || this.source.game) {
            const hash = `#page=${this.page}`;
            this.ownHash = hash;
            if (location.hash !== hash) {
                history.replaceState(null, '', hash);
            }
            return;
        }
        const now = performance.now();
        if (!force && this.hashTimer && now - this.hashTimer < 1000) {
            return;
        }
        this.hashTimer = now;
        let hash;
        if (this.source.kind === 'live') {
            hash = `#live=${encodeURIComponent(this.source.id)}`;
        } else {
            const t = this.timeline ? ((this.timeline.t - this.timeline.first) / this.timeline.sps).toFixed(1) : '0';
            hash = `#match=${encodeURIComponent(this.source.id)}&t=${t}`;
        }
        if (location.hash !== hash) {
            this.ownHash = hash;
            history.replaceState(null, '', hash);
        }
    }

    openFromHash() {
        this.openedHash = location.hash;
        const raw = location.hash.replace(/^#/, '');
        if (!raw) {
            this.showPage('home');
            return;
        }
        if (`#${raw}` === this.ownHash) {
            return;
        }
        const page = new URLSearchParams(raw).get('page');
        if (page && ['home', 'watch', 'play', 'recordings', 'matches', 'tournaments', 'teams', 'field', 'help'].includes(page)) {
            this.showPage(page);
            return;
        }
        const params = new URLSearchParams(raw);
        const t = params.has('t') ? Number(params.get('t')) : null;
        if (params.get('match')) {
            const id = params.get('match');
            if (this.source && this.source.kind === 'match' && this.source.id === id) {
                this.showPage('watch');
                if (Number.isFinite(t) && this.timeline) {
                    this.timeline.seek(this.timeline.first + t * this.timeline.sps);
                    this.afterSeek();
                    this.updateHash(true);
                }
                return;
            }
            this.openMatch(id, Number.isFinite(t) ? t : null);
        } else if (params.get('live')) {
            this.openLive(params.get('live'));
        }
    }
}

window.cuju = new App();
// A clean feed follows the source of its address, and a feed or a video export keeps the graphics
// inside the safe area of the picture.
if (window.cujuFeed) {
    import('./export/feed.js').then((m) => m.startFeed(window.cuju));
} else if (new URLSearchParams(location.search).has('capture')) {
    import('./export/safe-frame.js').then((m) => m.watchSafeArea($('app'), m.safeMode(location.search)));
}
