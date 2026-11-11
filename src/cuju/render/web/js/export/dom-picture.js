// Copyright 2026 The cuju Authors
// SPDX-License-Identifier: Apache-2.0

// The graphics of a page as a picture, for the video export of the browser. The scoreboard, the
// banners, the captions and every other part of the page over the view are HTML, which a canvas
// cannot draw by itself, so each frame writes the shown part of the page as XHTML with the page's
// own styles into an SVG image, which the browser lays out and draws as it lays out the page. The
// view's own canvas stays empty in the picture and is drawn beneath it, so the backgrounds behind
// the view turn clear. CSS animations show at the moment they have reached, each animated value
// written onto its element. Pictures of the page become data addresses, since an SVG image loads
// nothing of its own.

const XHTML = 'http://www.w3.org/1999/xhtml';
const SVG = 'http://www.w3.org/2000/svg';
// Elements that never show or that the styles already hold.
const SKIPPED = new Set(['script', 'style', 'link', 'meta', 'title', 'template', 'noscript', 'head', 'iframe', 'audio', 'video']);
// Properties of an animation's keyframes that name no style.
const NOT_STYLES = new Set(['offset', 'easing', 'composite', 'computedOffset']);

const escapeText = (value) => value.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
const escapeAttribute = (value) => escapeText(value).replace(/"/g, '&quot;').replace(/\n/g, '&#10;');
// Characters that XML refuses, which an attribute or a text may still hold.
// eslint-disable-next-line no-control-regex
const clean = (value) => value.replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f￾￿]/g, '');

// Reads a blob as a data address.
function dataAddress(blob) {
    return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve(reader.result);
        reader.onerror = () => reject(reader.error);
        reader.readAsDataURL(blob);
    });
}

// Whether this browser draws an SVG image with HTML inside into a canvas that it can still read,
// which the export needs. Some browsers mark such a canvas as unreadable.
export async function readableHtmlPictures() {
    try {
        const svg = `<svg xmlns="${SVG}" width="4" height="4"><foreignObject width="4" height="4"><div xmlns="${XHTML}" style="width:4px;height:4px;background:#f00"></div></foreignObject></svg>`;
        const image = new Image();
        image.src = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
        await image.decode();
        const canvas = document.createElement('canvas');
        canvas.width = 4;
        canvas.height = 4;
        const context = canvas.getContext('2d');
        context.drawImage(image, 0, 0);
        return context.getImageData(1, 1, 1, 1).data[0] > 128;
    } catch {
        return false;
    }
}

export class DomPicture {
    // win is the window of the page, view the canvas that is drawn beneath the picture, width and
    // height the size of the page's layout in CSS pixels.
    constructor(win, view, width, height) {
        this.win = win;
        this.doc = win.document;
        this.view = view;
        this.width = width;
        this.height = height;
        this.urls = new Map();
        this.stylesKey = '';
        this.styles = '';
        this.markup = '';
        this.image = null;
    }

    // The text of every style sheet of the page, gathered again whenever a sheet or rule changes.
    async gatherStyles() {
        const sheets = [...this.doc.styleSheets];
        let key = `${sheets.length}`;
        for (const sheet of sheets) {
            try {
                key += `,${sheet.cssRules.length}`;
            } catch {
                key += ',x';
            }
        }
        if (key === this.stylesKey) {
            return;
        }
        const texts = [];
        for (const sheet of sheets) {
            if (sheet.disabled) {
                continue;
            }
            let rules;
            try {
                rules = [...sheet.cssRules];
            } catch {
                continue;
            }
            const base = sheet.href || this.doc.baseURI;
            let text = rules.map((rule) => rule.cssText).join('\n');
            text = await this.inlineUrls(text, base);
            const media = sheet.media && sheet.media.mediaText;
            texts.push(media ? `@media ${media} {\n${text}\n}` : text);
        }
        this.styles = texts.join('\n');
        this.stylesKey = key;
    }

    // The data address of a file of the page, fetched once.
    async dataOf(address) {
        if (!address || address.startsWith('data:')) {
            return address;
        }
        let url;
        try {
            url = new URL(address, this.doc.baseURI).href;
        } catch {
            return '';
        }
        if (!this.urls.has(url)) {
            this.urls.set(url, (async () => {
                try {
                    const response = await this.win.fetch(url);
                    return response.ok ? await dataAddress(await response.blob()) : '';
                } catch {
                    return '';
                }
            })());
        }
        return this.urls.get(url);
    }

    // The text with each url() of a file made a data address.
    async inlineUrls(text, base) {
        const found = [...text.matchAll(/url\(\s*(['"]?)([^'")]+)\1\s*\)/g)];
        if (!found.length) {
            return text;
        }
        let out = text;
        for (const match of found) {
            const address = match[2];
            if (address.startsWith('data:') || address.startsWith('#')) {
                continue;
            }
            let url;
            try {
                url = new URL(address, base).href;
            } catch {
                continue;
            }
            const data = await this.dataOf(url);
            out = out.split(match[0]).join(data ? `url("${data}")` : 'none');
        }
        return out;
    }

    // The values that the animations of the page have reached, by element, as styles to write.
    animated() {
        const out = new Map();
        for (const animation of this.doc.getAnimations()) {
            const effect = animation.effect;
            const target = effect && effect.target;
            if (!target || effect.pseudoElement) {
                continue;
            }
            const names = new Set();
            if (typeof animation.transitionProperty === 'string') {
                names.add(animation.transitionProperty);
            } else if (typeof effect.getKeyframes === 'function') {
                for (const frame of effect.getKeyframes()) {
                    for (const name of Object.keys(frame)) {
                        if (!NOT_STYLES.has(name)) {
                            names.add(name.replace(/[A-Z]/g, (c) => `-${c.toLowerCase()}`));
                        }
                    }
                }
            }
            const style = this.win.getComputedStyle(target);
            const list = out.get(target) || [];
            for (const name of names) {
                const value = style.getPropertyValue(name);
                if (value) {
                    list.push(`${name}: ${value} !important`);
                }
            }
            out.set(target, list);
        }
        return out;
    }

    // Writes an element and what it holds as XHTML, leaving out what does not show.
    async write(node, out, context) {
        if (node.nodeType === 3) {
            out.push(escapeText(clean(node.data)));
            return;
        }
        if (node.nodeType !== 1) {
            return;
        }
        const tag = node.localName;
        if (SKIPPED.has(tag) || (tag === 'dialog' && !node.open)) {
            return;
        }
        const svg = node.namespaceURI === SVG;
        if (!svg && node.hidden && node !== this.doc.body) {
            return;
        }
        // The parts of an SVG that only other parts use, its symbols and definitions, never show
        // by themselves, so their own display says nothing.
        const used = context.defs || (svg && (tag === 'defs' || tag === 'symbol'));
        if (!used && this.win.getComputedStyle(node).display === 'none') {
            return;
        }
        let name = tag;
        const attributes = [];
        let extra = context.animated.get(node) || [];
        if (context.clear.has(node)) {
            extra = [...extra, 'background: transparent !important', 'background-image: none !important'];
        }
        let source = null;
        if (tag === 'canvas') {
            if (node !== this.view) {
                // Another canvas shows as a picture of itself.
                try {
                    source = node.toDataURL();
                } catch {
                    source = '';
                }
                name = 'img';
                extra = [...extra, `width: ${node.clientWidth}px`, `height: ${node.clientHeight}px`];
            }
        } else if (tag === 'img') {
            source = await this.dataOf(node.currentSrc || node.getAttribute('src') || '');
        }
        for (const attribute of node.attributes) {
            const key = attribute.name;
            if (key.startsWith('on') || key === 'src' || key === 'srcset' || key === 'xmlns' || key.startsWith('xmlns:')) {
                continue;
            }
            if (tag === 'canvas' && node !== this.view && (key === 'width' || key === 'height')) {
                continue;
            }
            let value = attribute.value;
            if (key === 'style' && value.includes('url(')) {
                value = await this.inlineUrls(value, this.doc.baseURI);
            }
            if (key === 'style' && extra.length) {
                value = `${value};${extra.join(';')}`;
                extra = [];
            }
            if ((key === 'value' || key === 'checked') && tag === 'input') {
                continue;
            }
            attributes.push(` ${key}="${escapeAttribute(clean(value))}"`);
        }
        if (extra.length) {
            attributes.push(` style="${escapeAttribute(extra.join(';'))}"`);
        }
        if (tag === 'input') {
            if (node.type === 'checkbox' || node.type === 'radio') {
                if (node.checked) {
                    attributes.push(' checked="checked"');
                }
            } else {
                attributes.push(` value="${escapeAttribute(clean(String(node.value)))}"`);
            }
        }
        if (source !== null) {
            attributes.push(` src="${escapeAttribute(source)}"`);
        }
        if (svg && node.parentNode && node.parentNode.namespaceURI !== SVG) {
            attributes.push(` xmlns="${SVG}" xmlns:xlink="http://www.w3.org/1999/xlink"`);
        }
        const children = name === 'img' ? [] : node.childNodes;
        if (!children.length) {
            out.push(`<${name}${attributes.join('')}/>`);
            return;
        }
        out.push(`<${name}${attributes.join('')}>`);
        if (tag === 'textarea') {
            out.push(escapeText(clean(node.value)));
        } else {
            const inner = used && !context.defs ? { ...context, defs: true } : context;
            for (const child of children) {
                await this.write(child, out, inner);
            }
        }
        out.push(`</${name}>`);
    }

    // The SVG markup of the page as it shows now.
    async markupNow() {
        await this.gatherStyles();
        const root = this.doc.documentElement;
        const clear = new Set();
        for (let node = this.view; node; node = node.parentElement) {
            clear.add(node);
        }
        const context = { animated: this.animated(), clear };
        const body = [];
        await this.write(this.doc.body, body, context);
        const rootAttributes = [...root.attributes]
            .filter((a) => !a.name.startsWith('xmlns') && a.name !== 'style')
            .map((a) => ` ${a.name}="${escapeAttribute(clean(a.value))}"`).join('');
        const rootStyle = escapeAttribute(clean(root.getAttribute('style') || ''));
        // The root of the image is the SVG element, which the rules for the page's root then match,
        // so it takes the attributes of the page's root as well.
        const overrides = [
            '*, *::before, *::after { animation: none !important; transition: none !important; caret-color: transparent !important; }',
            ':root, html, body { background: transparent !important; overflow: hidden !important; }',
        ].join('\n');
        const { width, height } = this;
        return `<svg xmlns="${SVG}" width="${width}" height="${height}" viewBox="0 0 ${width} ${height}"${rootAttributes} style="${rootStyle}">`
            + `<foreignObject x="0" y="0" width="${width}" height="${height}">`
            + `<html xmlns="${XHTML}"${rootAttributes} style="${rootStyle};width:${width}px;height:${height}px">`
            + `<head><style>${escapeText(this.styles)}\n${overrides}</style></head>`
            + `${body.join('')}</html></foreignObject></svg>`;
    }

    // Draws the graphics of the page over a context of the picture's size.
    async draw(context, width, height) {
        const markup = await this.markupNow();
        if (markup !== this.markup || !this.image) {
            const image = new Image();
            image.decoding = 'sync';
            image.src = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(markup)}`;
            await image.decode();
            this.image = image;
            this.markup = markup;
        }
        context.drawImage(this.image, 0, 0, width, height);
    }
}
