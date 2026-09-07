# Project Zomboid Mod Translation Mod

Translations for Project Zomboid mods, with a configurable multilingual workflow.

This repository finds missing translations in the base game and installed Workshop mods, stores
translation work durably and generates one standalone local translation mod.
English (`EN`) is always the source language. Workshop content and the game
installation are read only. The tooling uses only the Python standard library.

## Supported catalogue and local sources

The durable files in `translations/` define the supported mod catalogue. Local
Workshop installation is only source evidence for updating and checking it.
If drafts for A, B and C are complete, build/export include A, B and C even when
only A and C are currently installed. This applies independently to every target
language. Missing local sources never retire entries or discard target text.

`scan` and `status` inventory installed mods, including unknown candidates.
`draft --all` refreshes **only existing drafts**. To deliberately adopt a new mod,
first analyse its source, then select it explicitly:

```bash
./pzgt scan
./pzgt status --language DE
./pzgt draft MOD-ID
```

That new draft becomes part of the catalogue and is included in subsequent
`draft --all` refreshes. An unknown installed mod has no effect on normal build,
verify or export. Verify inventories only known source identities and does not
parse unknown mods' translation files.

### Base game translations

Normal `scan` also inventories `game/projectzomboid/media/lua/shared/Translate`
using a single effective `game` layer. The Translate root and its `EN/` directory
must exist; otherwise scan fails with a configuration error. Scan and status keep
the base game separate from Workshop mods in `base_game`.

For the base game, only a completely absent target key with nonempty English text
is needed. Existing blank target values and missing keys with empty English text
are ignored and counted separately in status. Workshop needs still include both
missing and blank target values.

Adoption is explicit, after scan and status:

```bash
./pzgt scan
./pzgt status --language DE
./pzgt draft "Project Zomboid"
./pzgt progress "Project Zomboid" --language DE
./pzgt work "Project Zomboid" --language DE --limit 25
# Fill translation fields in the work package, then:
./pzgt apply data/work/__project_zomboid.DE.work.json
```

This creates `translations/__project_zomboid.json` with `source_type: "game"`,
`name`, `game_version` and the same multilingual entries as other drafts, without
Workshop or mod IDs. Subsequent `draft --all` refreshes include it. Source changes
mark all stored languages for review; official target additions and removed
English keys retire the selected language's need while preserving stored text.

The same builder combines completed game and mod drafts in the runtime language
directories, with the existing shared-key conflict rules. An unfinished game
draft is excluded just like an unfinished mod draft. Verify reads the game only
when a game draft exists; its installation is then required and version, source
text and translation needs must match. A missing game source is an error.

## Configuration

Copy the example and set your local paths:

```bash
cp pzgt.example.json pzgt.local.json
```

```json
{
  "game": "/path/to/steam/steamapps/common/ProjectZomboid",
  "workshop": "/path/to/steam/steamapps/workshop/content/108600",
  "zomboid_home": "/path/to/Zomboid",
  "languages": ["DE", "FR", "ES"]
}
```

`zomboid_home/console.txt` supplies the last recorded game version. Start the game
once if this file is missing. Local configuration is ignored by Git.

Use native PZ language directory names such as `DE`, `FR` and `ES`; no ISO alias
conversion is performed. Values must be nonempty, without surrounding whitespace,
path separators, colons or control characters, and cannot be `.` or `..`.
Case-insensitive duplicates are rejected. Explicit language selection uses the
configured spelling.

An older configuration without `languages` defaults to `["DE"]`. With exactly
one configured target, language arguments may be omitted. With several targets,
`status`, `progress` and `work` require `--language`. `build`, `verify` and
`export` default to all configured languages.

## Single-language workflow

With `"languages": ["DE"]`:

```bash
./pzgt scan
./pzgt status
./pzgt draft --all       # Refresh the existing catalogue
# ./pzgt draft MOD-ID    # Explicitly adopt an additional mod
./pzgt progress
./pzgt work --next --limit 25

# Edit only the "translation" fields in the generated work package.
./pzgt apply data/work/WORKSHOP__MOD.DE.work.json

./pzgt build
./pzgt verify
./pzgt export
./pzgt export --zip
./pzgt install
```

`work` without arguments also selects the smallest unfinished draft.
`--offset N` selects a later range of open entries. A new package for the same
draft and language replaces the previous disposable work file.

## Multilingual workflow

Each target language needs its own analysis:

```bash
./pzgt scan
./pzgt status --language DE
./pzgt draft --all

./pzgt status --language FR
./pzgt draft --all

./pzgt progress --language DE
./pzgt progress AutoTailoring --language FR
./pzgt work --language DE --next --limit 25
./pzgt work AutoTailoring --language FR
```

The language saved in `data/status.json` determines which `needed` states
`draft --all` updates. A French refresh preserves German requirements and text.
The current status is a single replaceable snapshot, not a permanent language
state database. Durable states live in `translations/`.

Adding a language does not invent translations or mark unanalysed entries as
unneeded. Refreshes add its empty state with `needed=null` until that language
is analysed. A source first discovered during another language's refresh can
also introduce an unknown state; analyse that language again to classify it.
Removing a language from configuration does not delete its draft state.

```bash
./pzgt build                 # All configured languages
./pzgt build --language DE   # Only DE
./pzgt verify               # All configured languages
./pzgt verify --language FR
./pzgt export --language DE
```

A selected-language build preserves the other runtime languages. Runtime
languages outside the selected set are also outside that verify/export scope.
An export includes only its selected configured languages.

## Commands

| Command | Purpose |
| --- | --- |
| `./pzgt scan` | Inventory base game, Workshop mods, effective layers, EN and configured targets |
| `./pzgt status [--language CODE]` | Compare English and target content from the scan |
| `./pzgt draft MOD-ID` | Explicitly adopt or refresh one mod using the current status language |
| `./pzgt draft --all` | Migrate/refresh existing catalogue drafts only |
| `./pzgt progress [MOD-ID] [--language CODE]` | Count needed, translated, open, review and unknown entries |
| `./pzgt work [MOD-ID\|--next] [--language CODE] [--limit N] [--offset N]` | Create a language-specific work package |
| `./pzgt apply WORK-FILE` | Validate and atomically apply the package's target language |
| `./pzgt build [MOD-ID] [--language CODE]` | Generate deterministic runtime output |
| `./pzgt verify [--language CODE]` | Verify drafts, live adopted sources and exact runtime files |
| `./pzgt export [--language CODE] [--zip]` | Package an already current runtime |
| `./pzgt install` | Safely link this one mod into the local user mod directory |

Mod selectors match a unique mod ID, directory or name, without case sensitivity.
The optional legacy `build MOD-ID` form additionally requires that selected
draft to be complete for the selected language(s); the build still includes
all completed drafts.

## Durable draft model

Each English source and its `(category, key)` identity are stored once:

```json
{
  "category": "ContextMenu",
  "key": "ContextMenu_AutoTailoring",
  "english": "Train Tailoring",
  "translations": {
    "DE": {
      "text": "Schneidern trainieren",
      "needed": true,
      "review": false
    },
    "FR": {
      "text": "",
      "needed": null,
      "review": false
    }
  },
  "source_file": "ContextMenu_EN.txt",
  "source_layer": "common",
  "source_format": "legacy-txt"
}
```

Draft metadata retains Workshop/mod identity, game version and effective layers.
`translations/` is authoritative; generated runtime files must not be edited.

Each language state has:

- `text`: the exact saved target text.
- `needed=true`: English exists and the Workshop target is missing or blank.
- `needed=false`: analysis for this language confirms that the entry is no longer
  required, because the upstream target exists or the English key disappeared.
- `needed=null`: no reliable analysis has classified this language's requirement.
- `review`: whether an English source change requires checking this state.
- Optional `previous_english`: the source text before the pending review began.

A missing state is treated as unknown. `work` and `build` reject unknown needs
for the selected language. Run `scan`, `status --language CODE`, then
`draft --all` first. Progress reports unknown counts and does not mark them
complete. A draft without any needed entries is not counted as build-ready.

Refresh preserves entries and target texts even when they become unneeded.
An unavailable Workshop mod provides no reliable retirement evidence, so refresh
preserves its existing requirements and reports its absence. Verify labels its
source as not locally available / not currently checkable, without treating that
as a synchronization failure. New states on such drafts remain unknown.

## Source changes and migration

When known English text changes, **all existing target states** are marked
`review=true`, including unconfigured languages and entries now translated by
the Workshop itself. Existing target text remains untouched. Repeated source
changes preserve the first `previous_english` until that language is accepted
through `apply`.

To migrate the historical German format:

```bash
./pzgt scan
./pzgt status --language DE
./pzgt draft --all
```

Only the draft workflow accepts the old format. It moves:

| Old entry field | New field |
| --- | --- |
| `german` | `translations.DE.text` |
| `needed` | `translations.DE.needed` |
| `review` | `translations.DE.review` |
| `previous_english` | `translations.DE.previous_english` |

German states are preserved even if DE is no longer configured. Mixed fields,
mixed entry formats within a draft and ambiguous identities fail instead of
being guessed. All selected drafts are validated before any is written; each
file is replaced atomically. Legacy work packages must be regenerated.

The migration from `2297097` preserved all 41 drafts, the same 39 completed DE
drafts, 1915 translated and 2557 open entries, with zero reviews. All 127 German
runtime translation files remained byte-identical. Only the display name and
description in the two `mod.info` files became generic; mod ID and install link
remain unchanged.

## Work packages and apply

Packages can coexist at:

```text
data/work/3388183573__AutoTailoring.DE.work.json
data/work/3388183573__AutoTailoring.FR.work.json
```

The package records `language`, `draft_file`, mod metadata and entries containing:

```json
{
  "category": "ContextMenu",
  "key": "ContextMenu_AutoTailoring",
  "english": "Train Tailoring",
  "translation": "",
  "original_translation": "",
  "review": false
}
```

Edit `translation`; retain `original_translation` as the concurrency check.
`apply` reads the language from the package and validates the whole package:
configured language, correct draft/mod, unique existing identity, `needed=true`,
unchanged English, unchanged original target, string type and exact placeholders.
An older package cannot overwrite a newer durable translation. Empty target
fields are skipped, but identity/source/concurrency checks still apply.

After successful acceptance, only that language's `text` changes, `review`
becomes false and `previous_english` is removed. A validation error writes
nothing, including when an earlier item was valid.

## Project Zomboid source handling

B42 uses `common` plus the highest compatible version layer with the same major
version that is not newer than the detected game. For 42.20.4, `common`, `42`,
`42.14`, `42.18`, `42.21` resolves to `common + 42.18`. Legacy root content is
inventoried but is not an effective B42 fallback.

Later effective layers override earlier entries by normalized identity, even
when the source filename or format changes. Supported input formats remain:

- B42 JSON objects. Trailing commas are tolerated when reading Workshop files;
  generated JSON is strict.
- Legacy translation tables, including `IG_UI_EN = { ... }` and
  `RecipesEN { ... }`. Language suffixes are normalized to the category.
- Plain `title.txt` and `description.txt` files, represented by `__plain__`
  entries with a relative path as key.

Metadata keys beginning with `HEADER_` are ignored. Existing parser diagnostics
remain in status: tolerant JSON, non-string values, unparsed legacy assignments
and same-layer source duplicates. The established ordering of duplicate source
files remains unchanged. Parse errors block refresh for the affected draft and
fail its verification. Warnings remain diagnostics; they do not redefine the
existing source parser's accepted subset.

`data/scan.json` stores layer/file inventory and the configured target languages.
`data/status.json` stores its explicit language, the full parsed English source,
missing/blank targets, counts and parser diagnostics. Keeping all English
sources allows updates to known entries that are no longer needed. Neither
analysis file stores the durable target text.

## Deterministic build and verification

Output uses the native layout:

```text
common/media/lua/shared/Translate/
├── DE/
├── FR/
└── ES/
```

Completion is language-specific. A draft is included only when all required
entries have nonempty text, no review and matching placeholders. Incomplete
drafts are excluded as a whole for that language; DE can be included while FR
is excluded. A language with no finished drafts produces no translation files.
Unknown requirements are errors, not silently excluded drafts.

One shared planner computes the exact expected bytes for build, verify and
export. It retains the existing four-space JSON serialization, sorted categories
and keys, and plain text normalization (`rstrip()` plus one final newline).

Shared identities are checked per language:

- JSON `(category, key)` can be shared across owners only when English **and**
  target text match exactly.
- Plain runtime targets can be shared across owners only when normalized target
  contents match; their English text may differ.
- Duplicate identities within the same owner remain errors, including repeated
  owners after an otherwise valid shared entry.
- Unsafe paths, file/directory collisions and colliding output filenames fail
  before output changes.

Build plans all selected languages before staging any output. It then replaces
the combined translation tree and changed metadata, rolling back already
exchanged paths on a write failure. Byte-identical trees are left in place.
Stale files in selected languages disappear on a successful build.

Verify freshly inventories and reads installed **supported** Workshop sources for
each selected language **without rewriting scan or status**. It checks structure, unknown
needs, source identity, required entries, English changes, game/layer changes,
review, placeholders, shared conflicts and the exact runtime bytes. Missing,
unexpected/stale and changed files fail verification. Incomplete drafts with
empty target texts are valid, while pending required reviews and placeholder
errors are reported. Both `mod.info` files must match the expected metadata.
Source synchronization and local reproducibility are separate results. Per
language, verify reports `geprüft`, `Quelle nicht lokal` and `Abweichend` counts
(number of supported drafts). Missing sources count only as unconfirmed; internal
draft, placeholder, shared-conflict and runtime checks still run. Installed
supported sources remain subject to strict synchronization checks. If none are
installed and no base-game draft exists, verification needs no game-version log; an absent Workshop directory
also counts as unavailable sources. Unreadable existing directories are errors,
not evidence of absence. Returning sources are checked on the next verify.

This is filesystem verification, not confirmation from a running game.

## Distribution export

```bash
./pzgt export
./pzgt export --language DE
./pzgt export --zip
```

Output:

```text
dist/
├── Project-Zomboid-Mod-Translations/
│   ├── LICENSE
│   ├── SUPPORTED-MODS.txt
│   ├── common/
│   │   ├── mod.info
│   │   └── media/lua/shared/Translate/<CODE>/...
│   └── 42/
│       └── mod.info
└── Project-Zomboid-Mod-Translations.zip
```

Export never builds implicitly. It computes expected output from drafts and
requires the selected existing runtime and metadata to match exactly. Any
missing, stale or changed file aborts with an instruction to run `./pzgt build`.
Live Workshop sources or a current status are not required for packaging a
known build.

`SUPPORTED-MODS.txt` is generated deterministically from the durable drafts and
the actual build plan for the selected export languages. It lists only mods
whose translations are complete and therefore present in that export, including
Workshop ID, Workshop URL, mod ID and the included target languages. A known but
incomplete mod is not listed for that language. Local installation state does
not affect the list.

The base game is excluded from `Supported mods` and the Workshop list. If its
draft is included in any exported language, the header adds, for example,
`Base game translations: included (DE, FR)`, listing only those included languages.

The allowlist contains only `LICENSE`, `SUPPORTED-MODS.txt`, the two `mod.info`
files and selected runtime translations. No scripts, drafts, local config, data,
Git metadata or other development files are included. ZIP generation uses the
standard library, with deterministic entry order and timestamps. Directory and
optional ZIP are staged before replacement. An export replaces the prior
directory with exactly the selected languages. Without `--zip`, an existing ZIP
is left untouched; rerun with `--zip` to refresh it. `dist/` is ignored by Git.

### Manual installation

The exported directory or ZIP can be installed without the development
repository or any Python tooling.

#### Linux

Extract or copy the `Project-Zomboid-Mod-Translations` directory to:

`~/Zomboid/mods/Project-Zomboid-Mod-Translations/`

The resulting layout should begin with:

```text
~/Zomboid/mods/Project-Zomboid-Mod-Translations/
├── common/
│   └── mod.info
└── 42/
    └── mod.info
```

For the ZIP export:

```bash
mkdir -p ~/Zomboid/mods
unzip Project-Zomboid-Mod-Translations.zip -d ~/Zomboid/mods/
```

#### Windows

Extract or copy the `Project-Zomboid-Mod-Translations` directory to:

`%UserProfile%\Zomboid\mods\Project-Zomboid-Mod-Translations`

For example:

`C:\Users\YourName\Zomboid\mods\Project-Zomboid-Mod-Translations`

The resulting layout should begin with:

```text
Project-Zomboid-Mod-Translations
├── common
│   └── mod.info
└── 42
    └── mod.info
```

After installation, start Project Zomboid and enable **ElHanko Mod Translations** in the Mods menu.

The original supported Workshop mods remain separate. Install and enable
whichever of them you want to use; the translation mod may contain translations
for mods that are not currently installed.

## Local install

```bash
./pzgt install
```

Installation remains one symlink at:

```text
~/Zomboid/mods/ElHanko-German-Translations
```

The historical install directory name deliberately remains stable. The mod ID is
`ElHankoModTranslations`. The visible name is now `ElHanko Mod Translations`. The existing
installation mechanism accepts an already correct link, refuses a wrong link
and refuses to overwrite a real file or directory. Adding languages does not
create additional mods. The existing install location remains `~/Zomboid/mods`;
`zomboid_home` supplies analysis logs, as before.

## Update cycle and safety

After game/Workshop updates or language configuration changes:

```bash
./pzgt scan
./pzgt status --language DE
./pzgt draft --all
./pzgt status --language FR
./pzgt draft --all
./pzgt progress --language DE
./pzgt progress --language FR
# Resolve open translations/reviews through work and apply.
./pzgt build
./pzgt verify
./pzgt export --zip
```

For one language, omit the language flags and the second status/draft pair.

Workshop and game paths are read only. Generated state belongs to this
repository and the standalone translation mod. Draft, runtime and export writes
reject symlink paths; runtime/export trees also reject symlinks within them.
Target texts are never automatically translated or reworded.

Run one writing CLI process at a time. Validation failures write nothing;
filesystem rollback protects exchanged build/export paths during ordinary
exceptions, but is not a transaction across power loss or process termination.
If rollback itself fails, the `.pzgt-stage-*` directory is retained for recovery.
Individual draft refresh writes are atomic, but a filesystem failure can stop a
multi-draft refresh between files; rerun after correcting the error.

## Tests

```bash
python3 -m py_compile scripts/*.py
python3 -m unittest discover -s scripts -p 'test_*.py'
git diff --check
```

Regression fixtures cover configuration, lossless migration, independent and
unknown language states, source reviews, work/apply concurrency and atomicity,
B42/JSON/legacy/plain parsing, shared identities, build staging and rollback,
exact verification, export/ZIP isolation and install symlink behavior. Catalogue
regressions cover explicit adoption, missing/reinstalled sources, unknown mods
and multilingual output independent of the local Workshop selection. A complete
multilingual CLI test uses temporary Workshop data and asserts that the tool did
not modify it.

Existing placeholder tests retain `%1`, `%2`, `%s`, `%d`, `% d`, `%.2f`, `{0}`,
`{name}`, `1%s` and prose percentages such as `25% likely`, `25%-Chance` and
`100%ig`. Counts must match exactly.

## License

MIT. See [LICENSE](LICENSE).
