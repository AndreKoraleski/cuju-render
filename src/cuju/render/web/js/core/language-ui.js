// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// The language of the page on the Settings panel. A list offers Follow the browser, the shipped
// languages and then the languages of the home folder, and a button imports a language file,
// which the server checks and keeps in that folder. A change stores the choice in the browser,
// and the page then reloads at the same address in the new language. Scripts reach the same as
// cuju.language, with list(), choose(code) and importText(text).

import { enhanceSelect, el as h } from './menu.js';
import { listLanguages, setLanguage, storedLanguage, t } from './i18n.js';

const FOLLOW = '';

export class LanguageSettings {
    constructor(app) {
        this.app = app;
        this.languages = [];
        const panel = document.getElementById('settings');
        if (!panel) {
            return;
        }
        this.select = h('select', { id: 'language', 'aria-label': t('language.label') });
        this.file = h('input', { type: 'file', accept: '.json,application/json', hidden: '' });
        this.importButton = h('button', { type: 'button', class: 'btn small', id: 'language-import' }, t('language.import'));
        this.status = h('p', { class: 'muted small', id: 'language-status', role: 'status' });
        this.importButton.addEventListener('click', () => this.file.click());
        this.file.addEventListener('change', () => this.onFile());
        this.select.addEventListener('change', () => this.choose(this.select.value || null));
        const label = h('label', { id: 'language-row' }, t('language.label'), this.select);
        panel.append(label, h('div', { class: 'language-actions' }, this.importButton, this.file), this.status);
        this.fill([]);
        enhanceSelect(this.select, { className: 'in-panel', align: 'right', label: t('language.label') });
        this.refresh();
    }

    // Lists the languages again from the server.
    async refresh() {
        this.languages = await listLanguages();
        this.fill(this.languages);
        return this.languages;
    }

    fill(languages) {
        const stored = storedLanguage();
        const options = [h('option', { value: FOLLOW }, t('language.follow'))];
        const shipped = languages.filter((l) => l.source === 'shipped');
        const own = languages.filter((l) => l.source !== 'shipped');
        const option = (l) => h('option', { value: l.code, disabled: l.usable === false ? '' : null },
            l.usable === false ? t('language.refused', { name: l.name || l.code }) : l.name || l.code);
        if (shipped.length) {
            options.push(h('optgroup', { label: t('language.shipped') }, ...shipped.map(option)));
        }
        if (own.length) {
            options.push(h('optgroup', { label: t('language.own') }, ...own.map(option)));
        }
        this.select.replaceChildren(...options);
        this.select.value = stored && languages.some((l) => l.code === stored) ? stored : FOLLOW;
        const refused = own.filter((l) => l.usable === false);
        this.status.textContent = refused.length
            ? t('language.refusedNote', { count: refused.length, names: refused.map((l) => `${l.code}.json`).join(', ') })
            : '';
    }

    // The languages to choose from, shipped first.
    list() {
        return this.languages.map((l) => ({ ...l }));
    }

    // Chooses a language by code, or null to follow the browser, and reloads the page in it.
    async choose(code) {
        try {
            await setLanguage(code);
        } catch (err) {
            this.status.textContent = t('language.loadFailed', { code, reason: err.message });
            this.fill(this.languages);
            throw err;
        }
    }

    async onFile() {
        const file = this.file.files && this.file.files[0];
        this.file.value = '';
        if (!file) {
            return;
        }
        try {
            await this.importText(await file.text());
        } catch {
            // The status line already says why.
        }
    }

    // Imports a language file from its text. The server refuses a malformed file with the reasons,
    // which the status line shows. A file it takes joins the list and is chosen.
    async importText(text) {
        let body;
        try {
            body = JSON.parse(text);
        } catch (err) {
            this.status.textContent = t('language.notJson', { reason: err.message });
            throw err;
        }
        const { api } = await import('./api.js');
        try {
            const result = await api.importLanguage(body);
            this.status.textContent = t('language.imported', { name: result.name || result.code });
            await this.refresh();
            await this.choose(result.code);
            return result;
        } catch (err) {
            this.status.textContent = t('language.importFailed', { reason: err.message });
            throw err;
        }
    }
}
