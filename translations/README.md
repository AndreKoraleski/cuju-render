# Translations

cuju-render ships its page in English. This folder holds drafts of other languages, outside the
package, until they are ready to ship.

- `pt.json` is the Brazilian Portuguese draft of the page and of the server's messages.
- `pt-style.md` is its style guide, the voice, the forms of address and the punctuation of the
  interface in Portuguese.
- `pt-glossary.json` fixes one Portuguese term for each recurring concept of the page.

## Loading a translation

A translation loads through the language import, as any language of a person's own. On the
settings panel of the page, Import a language file sends the file to the server, which checks it
and keeps it in the folder `languages` of the renderer's home, and the page then reloads in it.
From a terminal, `cuju render language add translations/pt.json` does the same, and
`cuju render language remove pt` takes it away again.

## Checking a translation

`cuju render language check translations/pt.json` names each message the file lacks, each one
English lacks and each malformed one. A draft may lack messages, which the page shows in English.
Each message it has must keep the placeholders of its English message, take the plural forms of
its language, with `=0` beside them where zero reads apart, and carry the marks of the English,
the same code spans in backticks and strong words in double asterisks where the English has them.
A translation uses its own language's punctuation for an interface, rather than the plain commas
and periods of the English.

The tests that need a second language read `pt.json` from here, among them
`tests/test_languages.py`, `tests/web/plurals.mjs`, `tests/web/keys.mjs`, `tests/web/i18n.mjs`
and the language check of `ci/page_check.py`, which imports the draft into the page.
