# Project Zomboid Mod Translation Mod

German translations for Project Zomboid mods.

This repository contains tooling and translation state for finding untranslated
strings in installed Project Zomboid Workshop mods, maintaining German
translations, and generating a separate local translation mod.

Workshop mods are treated as read-only sources and are never modified.

## Goals

- Detect installed Project Zomboid Workshop mods.
- Respect Project Zomboid Build 42 mod version layers.
- Compare effective English and German content by translation key.
- Preserve translations across upstream updates.
- Detect changed English source strings that require review.
- Validate placeholders before building.
- Generate one standalone German translation mod.
- Never modify Workshop content directly.
- Use the Python standard library only.

## Build 42 layer handling

Build 42 mods may contain directories such as:

    common/
    42/
    42.13/
    42.18/
    42.20/

For the detected game version, `pzgt` uses:

1. `common`, if present.
2. The highest compatible version layer with the same major version that is not
   newer than the running game.

For example, with Project Zomboid 42.20.4 and:

    common
    42
    42.14
    42.18
    42.21

the effective payload is:

    common + 42.18

Legacy root content is inventoried but is not part of the effective Build 42
payload.

## Supported translation formats

### Build 42 JSON

Example:

    {
        "ContextMenu_AutoTailoring": "Train Tailoring"
    }

Trailing commas found in Workshop JSON are tolerated while reading source
files. Workshop files are never rewritten. Generated JSON is always strict
valid JSON.

### Legacy translation tables

Both forms below are supported:

    IG_UI_EN = {
        IGUI_VehicleName91range = "'91 RANGE ROVER 4-door",
    }

and:

    RecipesEN {
        Recipe_91rangeMakeTire = "Make 91 Range Rover Tire",
    }

They are normalized internally to translation keys and values.

### Plain translation files

Some mods use files such as:

    EN/Audobon/title.txt
    EN/Audobon/description.txt

These are treated as path-based translation entries.

## Repository layout

    .
    ├── 42/
    │   └── mod.info
    ├── common/
    │   ├── mod.info
    │   └── media/lua/shared/Translate/DE/
    ├── data/
    ├── scripts/
    ├── translations/
    ├── pzgt
    └── pzgt.local.json

### translations/

Durable editable translation state.

Each draft stores, among other things:

- Workshop ID
- mod ID
- effective Build 42 layers
- category and translation key
- English source text
- German translation
- source file and source format
- `needed` state
- `review` state
- previous English text when upstream text changes

These files are the authoritative translation source.

### common/media/lua/shared/Translate/DE/

Generated runtime translation files.

Do not edit these files manually. They are generated from completed drafts.

### data/

Generated local analysis and work files. This directory is ignored by Git
except for `.gitkeep`.

### pzgt.local.json

Machine-local paths for Project Zomboid, Steam Workshop and the Zomboid user
directory. This file is ignored by Git.

## Workflow

### Scan installed Workshop mods

    ./pzgt scan

Creates:

    data/scan.json

The scan detects the game version, inventories Workshop mods and determines
their effective Build 42 layers.

### Find missing German translations

    ./pzgt status

Creates:

    data/status.json

The comparison is performed by translation key, not merely by file count.

### Create or refresh drafts

One mod:

    ./pzgt draft MOD-ID

All currently relevant mods:

    ./pzgt draft --all

Existing German translations are preserved.

If the upstream English text changes, the entry is marked:

    "review": true

If a translation is no longer required, the old entry is preserved with:

    "needed": false

### Show progress

All drafts:

    ./pzgt progress

One mod:

    ./pzgt progress MOD-ID

### Create a work package

Automatically choose the smallest unfinished mod:

    ./pzgt work

or:

    ./pzgt work --next

Specific mod:

    ./pzgt work MOD-ID

Limit package size:

    ./pzgt work MOD-ID --limit 25

Temporary work packages are written below:

    data/work/

The durable translation state remains in `translations/`.

### Apply a work package

After filling the `german` fields:

    ./pzgt apply data/work/FILE.work.json

`apply` checks that:

- the package belongs to the correct draft,
- keys still exist,
- English source text has not changed,
- placeholders are preserved.

### Build

    ./pzgt build MOD-ID

The selected draft must be complete.

The build is global and deterministic: all completed drafts are combined into
the runtime translation mod. Incomplete drafts are excluded.

Generated files are written below:

    common/media/lua/shared/Translate/DE/

The build checks:

- non-empty German translations,
- unresolved reviews,
- placeholder preservation,
- duplicate translation keys.

### Verify

    ./pzgt verify

Verification checks:

- draft structure,
- current Workshop source state,
- effective Build 42 layers,
- English source changes,
- placeholders,
- duplicate keys,
- generated runtime files,
- stale or unexpected generated files,
- mod.info.

Incomplete drafts are a valid repository state and are simply excluded from
the runtime build.

### Install locally

    ./pzgt install

This currently creates a symlink under:

    ~/Zomboid/mods/ElHanko-German-Translations

Workshop mods remain untouched.

## Recommended update cycle

After Project Zomboid or Workshop mods update:

    ./pzgt scan
    ./pzgt status
    ./pzgt draft --all
    ./pzgt progress
    ./pzgt verify

Changed upstream English text must be reviewed before it can be built again.

## Safety principles

`pzgt` must not:

- modify Steam Workshop mods,
- write into the Project Zomboid installation,
- overwrite upstream translations,
- silently discard existing German translations,
- build unresolved source changes,
- build translations with mismatching placeholders.

Generated content belongs only to the standalone local translation mod.

## License

MIT. See `LICENSE`.
