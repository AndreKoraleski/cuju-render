// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// The installable page. On the loopback address of the server, in a window of its own rather than
// a notebook's frame, the page registers its service worker, sw.js, with the build of the page
// that the server names, and Chrome and Edge then offer to install it as an app. The Help page
// shows whether the page is installed and offers Install where the browser allows it, Update once
// the server holds a newer build, and the removal of the copy that the worker keeps. Safari on a
// Mac adds the page to the Dock from its File menu, which Help then names, and every browser
// reaches an app window through the command cuju render app, which Help names as well. The
// browser's offer comes from install-state.js, which the card on Home shares. Scripts reach it as
// window.cuju.install.

import { t, tn } from '../core/i18n.js';
import { icon } from '../core/icons.js';
import { heldPrompt, installRoute, installedNow, onInstallChange, promptInstall, runsAsApp } from './install-state.js';

const LOOPBACK = ['127.0.0.1', 'localhost', '[::1]'];
const PREFIX = 'cuju-page-';

function h(tag, attributes = {}, ...children) {
    const node = document.createElement(tag);
    for (const [key, value] of Object.entries(attributes)) {
        if (key.startsWith('on') && typeof value === 'function') {
            node.addEventListener(key.slice(2), value);
        } else if (value !== null && value !== undefined && value !== false) {
            node.setAttribute(key, value === true ? '' : value);
        }
    }
    node.append(...children.flat().filter((child) => child !== null && child !== undefined));
    return node;
}

// Whether this page may register its worker, on http at a loopback host and at the top.
export function installable(where = location, framed = null) {
    let top = framed;
    if (top === null) {
        try {
            top = window.top !== window;
        } catch {
            top = true;
        }
    }
    return where.protocol === 'http:' && LOOPBACK.includes(where.hostname) && !top
        && typeof navigator !== 'undefined' && 'serviceWorker' in navigator;
}

// The build of a worker, from its address.
export function workerBuild(scriptURL) {
    try {
        return new URL(scriptURL).searchParams.get('build');
    } catch {
        return null;
    }
}

async function serverBuild() {
    const res = await fetch('/api/help/app', { cache: 'no-store' });
    if (!res.ok) {
        throw new Error(t('pwa.error.status', { status: res.status }));
    }
    return (await res.json()).build;
}

export class AppInstall {
    constructor(app, host) {
        this.app = app;
        this.host = host;
        this.supported = installable();
        this.registration = null;
        this.build = null;
        this.latest = null;
        this.error = null;
        this.route = installRoute({
            hasEvent: 'onbeforeinstallprompt' in window, userAgent: navigator.userAgent, vendor: navigator.vendor,
        });
        this.status = h('p', { class: 'muted small', role: 'status', 'aria-live': 'polite' });
        this.installButton = h('button', { type: 'button', class: 'btn primary', hidden: true, onclick: () => this.install() }, icon('download'), t('pwa.install'));
        this.updateButton = h('button', { type: 'button', class: 'btn', hidden: true, onclick: () => this.update(true) }, icon('refresh'), t('pwa.update'));
        this.forgetButton = h('button', { type: 'button', class: 'btn', hidden: true, onclick: () => this.unregister() }, icon('trash'), t('pwa.remove'));
        const code = (text) => h('code', {}, text);
        host.replaceChildren(
            h('h2', { id: 'help-install-title' }, t('pwa.title')),
            h('p', {}, ...tn('pwa.text')),
            h('div', { class: 'help-row' }, this.installButton, this.updateButton, this.forgetButton),
            this.status,
            // The command that opens cuju in a window of its own shows the symbol of a terminal.
            h('p', { id: 'help-install-command' }, icon('terminal', 'icon text-symbol'), tn('pwa.command.text', {
                command: code('cuju render app'), install: code('cuju render app --install'),
            })));
        onInstallChange(() => this.render());
        if (this.supported) {
            navigator.serviceWorker.addEventListener('controllerchange', () => this.render());
        }
        const page = document.getElementById('page-help');
        if (page) {
            new MutationObserver(() => {
                if (!page.hidden) {
                    this.check();
                }
            }).observe(page, { attributes: true, attributeFilter: ['hidden'] });
        }
        this.ready = this.register();
    }

    async register() {
        if (!this.supported) {
            this.render();
            return this.state();
        }
        try {
            this.build = await serverBuild();
            this.latest = this.build;
            this.registration = await navigator.serviceWorker.register(`sw.js?build=${encodeURIComponent(this.build)}`, {
                scope: '../', updateViaCache: 'none',
            });
            this.registration.addEventListener('updatefound', () => this.render());
            this.error = null;
        } catch (err) {
            this.error = err.message;
        }
        this.render();
        return this.state();
    }

    // Asks the server for its build, which differs from the page's once a new version is there.
    async check() {
        if (!this.supported) {
            return this.state();
        }
        try {
            this.latest = await serverBuild();
        } catch {
            // The server is away, the page stays as it is.
        }
        this.render();
        return this.state();
    }

    async install() {
        const result = await promptInstall();
        this.render();
        if (result.outcome === 'unavailable') {
            this.status.textContent = t(this.route === 'browser' ? 'pwa.unavailable' : `pwa.route.${this.route}`);
        }
        return result;
    }

    // Takes the newest build, the worker of the server's build, and with reload shows it at once.
    async update(reload = false) {
        await this.check();
        if (this.supported && this.latest && this.latest !== this.build) {
            this.build = this.latest;
            this.registration = await navigator.serviceWorker.register(`sw.js?build=${encodeURIComponent(this.build)}`, {
                scope: '../', updateViaCache: 'none',
            });
            if (reload) {
                location.reload();
            }
        }
        this.render();
        return this.state();
    }

    // Removes the worker and the copy it keeps, until the page registers it again on its next load.
    async unregister() {
        let removed = false;
        if (this.supported) {
            for (const registration of await navigator.serviceWorker.getRegistrations()) {
                removed = (await registration.unregister()) || removed;
            }
        }
        if (typeof caches !== 'undefined') {
            for (const name of await caches.keys()) {
                if (name.startsWith(PREFIX)) {
                    await caches.delete(name);
                }
            }
        }
        this.registration = null;
        this.render();
        this.status.textContent = t('pwa.removed');
        return removed;
    }

    state() {
        const controller = this.supported ? navigator.serviceWorker.controller : null;
        const standalone = runsAsApp();
        return {
            supported: this.supported,
            registered: !!this.registration,
            build: this.build,
            latest: this.latest,
            controlled: !!controller,
            controllerBuild: controller ? workerBuild(controller.scriptURL) : null,
            waiting: !!(this.registration && (this.registration.waiting || this.registration.installing)),
            updateReady: !!(this.latest && this.build && this.latest !== this.build),
            installable: !!heldPrompt(),
            installed: installedNow(),
            standalone,
            route: this.route,
            error: this.error,
        };
    }

    render() {
        const state = this.state();
        this.installButton.hidden = !state.installable || state.standalone;
        this.updateButton.hidden = !state.updateReady;
        this.forgetButton.hidden = !state.registered;
        // The line opens with the symbol of its state where one reads clearly, a ticked circle for
        // an installed app, a warning for an error and a terminal for the command.
        let text;
        let symbol = null;
        if (!this.supported) {
            text = tn('pwa.state.unsupported');
        } else if (state.error) {
            text = tn('pwa.state.error', { error: state.error });
            symbol = 'warning';
        } else if (state.standalone) {
            text = tn('pwa.state.standalone');
            symbol = 'done';
        } else if (state.installable) {
            text = tn('pwa.state.installable');
        } else if (state.installed) {
            text = tn('pwa.state.installed');
            symbol = 'done';
        } else if (this.route !== 'browser') {
            // Safari names its own menu, and another browser the command that makes the app.
            text = tn(`pwa.route.${this.route}`);
            symbol = this.route === 'command' ? 'terminal' : null;
        } else if (state.controlled) {
            text = tn('pwa.state.keptMenu');
        } else {
            text = tn('pwa.state.menu');
        }
        // A second sentence follows the first, as its own message, and each keeps its marks.
        if (state.updateReady) {
            text.push(' ', ...tn('pwa.state.updateReady'));
        } else if (state.controlled && (state.standalone || state.installable || state.installed || this.route !== 'browser')) {
            text.push(' ', ...tn('pwa.state.kept'));
        }
        this.status.replaceChildren(...(symbol ? [icon(symbol, 'icon text-symbol')] : []), ...text);
    }

    // The functions of window.cuju.install.
    script() {
        return {
            state: () => this.state(),
            install: () => this.install(),
            update: () => this.update(false),
            check: () => this.check(),
            unregister: () => this.unregister(),
            ready: () => this.ready,
        };
    }
}
