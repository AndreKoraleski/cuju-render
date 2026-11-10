// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// The installable page. On the loopback address of the server, in a window of its own rather than
// a notebook's frame, the page registers its service worker, sw.js, with the build of the page
// that the server names, and Chrome and Edge then offer to install it as an app. The Help page
// shows whether the page is installed and offers Install where the browser allows it, Update once
// the server holds a newer build, and the removal of the copy that the worker keeps. Scripts reach
// it as window.cuju.install.

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
        throw new Error(`The server answered ${res.status}.`);
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
        this.deferred = null;
        this.error = null;
        this.installed = false;
        this.status = h('p', { class: 'muted small', role: 'status', 'aria-live': 'polite' });
        this.installButton = h('button', { type: 'button', class: 'btn primary', hidden: true, onclick: () => this.install() }, 'Install the app');
        this.updateButton = h('button', { type: 'button', class: 'btn', hidden: true, onclick: () => this.update(true) }, 'Update');
        this.forgetButton = h('button', { type: 'button', class: 'btn', hidden: true, onclick: () => this.unregister() }, 'Remove the offline copy');
        host.replaceChildren(
            h('h3', { id: 'help-install-title' }, 'Install the app'),
            h('p', {}, 'Chrome and Edge install this page as an app with a window and an icon of its own. The app keeps a copy of the page, so it starts fast and opens even when the server is stopped, then says so. Recordings, teams and live matches always come from the server.'),
            h('div', { class: 'help-row' }, this.installButton, this.updateButton, this.forgetButton),
            this.status);
        window.addEventListener('beforeinstallprompt', (e) => {
            e.preventDefault();
            this.deferred = e;
            this.render();
        });
        window.addEventListener('appinstalled', () => {
            this.deferred = null;
            this.installed = true;
            this.render();
        });
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
        if (!this.deferred) {
            this.status.textContent = 'The browser offers no install right now. Its menu installs the page, as the guide describes.';
            return { outcome: 'unavailable' };
        }
        const prompt = this.deferred;
        this.deferred = null;
        await prompt.prompt();
        const choice = await prompt.userChoice;
        this.render();
        return { outcome: choice.outcome };
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
        this.status.textContent = 'The offline copy is removed. The next start of the page keeps it again.';
        return removed;
    }

    state() {
        const controller = this.supported ? navigator.serviceWorker.controller : null;
        const standalone = !!(window.matchMedia && window.matchMedia('(display-mode: standalone)').matches);
        return {
            supported: this.supported,
            registered: !!this.registration,
            build: this.build,
            latest: this.latest,
            controlled: !!controller,
            controllerBuild: controller ? workerBuild(controller.scriptURL) : null,
            waiting: !!(this.registration && (this.registration.waiting || this.registration.installing)),
            updateReady: !!(this.latest && this.build && this.latest !== this.build),
            installable: !!this.deferred,
            installed: this.installed || standalone,
            standalone,
            error: this.error,
        };
    }

    render() {
        const state = this.state();
        this.installButton.hidden = !state.installable;
        this.updateButton.hidden = !state.updateReady;
        this.forgetButton.hidden = !state.registered;
        let text;
        if (!this.supported) {
            text = 'This address keeps no offline copy. The app installs from the page at http://127.0.0.1 with the port of the server, opened in a window of its own.';
        } else if (state.error) {
            text = `The offline copy is off, ${state.error}`;
        } else if (state.standalone) {
            text = 'The page runs as an installed app.';
        } else if (state.installable) {
            text = 'The browser offers to install the page.';
        } else if (state.installed) {
            text = 'The app is installed.';
        } else {
            text = 'The browser menu installs the page, as the guide describes, once the offline copy is kept.';
        }
        if (state.updateReady) {
            text += ' A new version of the page is ready, Update shows it.';
        } else if (state.controlled) {
            text += ' The offline copy of this version is kept.';
        }
        this.status.textContent = text;
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
