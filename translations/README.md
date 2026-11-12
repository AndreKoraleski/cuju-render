# Translations

cuju-render ships its page in English. This folder holds drafts of other languages, outside the
package, until they are ready to ship.

## Layout

Each language has a folder of its own, named after its language code of BCP 47, the language
first and then the region or the script where they matter. Brazilian Portuguese is `pt-BR`, and
a later German would be `de`, Portuguese of Portugal `pt-PT` and Chinese in traditional script
`zh-Hant`. A folder holds three files.

- `<code>.json` holds the messages of the page and of the server, with the header `@language`
  whose `code` is the name of the folder. The file takes the name of its code, since the language
  check reads the code that a file must hold from its name.
- `style.md` is the style guide of the language, the voice, the forms of address and the
  punctuation of the interface.
- `glossary.json` fixes one term for each recurring concept of the page.

Today the folder holds `pt-BR/`, the Brazilian Portuguese draft, with `pt-BR/pt-BR.json`,
`pt-BR/style.md` and `pt-BR/glossary.json`. The style guide and the glossary are written for the
translators of that language, so the guide reads in Portuguese.

A new language starts from English. Run in a new folder `translations/de`, the command
`cuju render language new de --name Deutsch` writes `de.json` with every English message, the
header and the plural forms of the language, ready to translate in place.

## Loading a translation

A translation loads through the language import, as any language of a person's own. On the
settings panel of the page, Import a language file sends the file to the server, which checks it
and keeps it in the folder `languages` of the renderer's home, and the page then reloads in it.
From a terminal, `cuju render language add translations/pt-BR/pt-BR.json` does the same, and
`cuju render language remove pt-BR` takes it away again. A code names the same language whatever
its case, as BCP 47 has it, so `pt-br` finds the draft too.

## Checking a translation

`cuju render language check translations/pt-BR/pt-BR.json` names each message the file lacks,
each one English lacks and each malformed one. A draft may lack messages, which the page shows in
English. The header must hold the code of the file name and the plural categories of its base
language, the part of the code before the first hyphen, so `pt-BR` takes the categories of `pt`,
`one`, `many` and `other`. Each message the file has must keep the placeholders of its English
message, take the plural forms of its language, with `=0` beside them where zero reads apart, and
carry the marks of the English, the same code spans in backticks and strong words in double
asterisks where the English has them. A translation uses its own language's punctuation for an
interface, rather than the plain commas and periods of the English.

## Testing a translation

The tests that need a second language read `pt-BR/pt-BR.json` from here, through `_translation`
and `_install_translation` of `tests/support/common.py`. Among them are `tests/test_languages.py`,
which checks the draft and its folder, `tests/web/plurals.mjs`, `tests/web/keys.mjs`,
`tests/web/i18n.mjs` and the language check of `ci/page_check.py` in `ci/page_language.py`, which
imports the draft into the page in Chrome and removes it at the end. They run as
`CONTRIBUTING.md` describes, such as `python -m pytest tests/test_languages.py` and
`node tests/web/plurals.mjs` from the root of the repository.
