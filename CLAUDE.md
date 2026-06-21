# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**stella** (配信サポートツール) is a streaming support tool for IRIAM (イリアム) live streamers. It is a **single-file, no-build, client-side-only** HTML5 web application. All HTML, CSS, and JavaScript live in `index.txt` (~807 lines).

## Running the App

There is no build step. Open `index.txt` directly in a browser, or serve it with any static HTTP server:

```bash
python3 -m http.server 8000
# then visit http://localhost:8000/index.txt
```

There are no tests, no linter, no package manager, and no CI configuration.

## Architecture

Everything is in a single `App` object defined at the bottom of `index.txt` inside a `<script>` tag. The structure is:

```
App
├── state                  # Single source of truth (persisted to localStorage)
├── init()                 # Entry point — loads state, renders UI, wires events
├── loadState()            # Deserializes from localStorage; includes migration logic
├── saveState()            # Serializes state to localStorage (key: `liverCopilotState`)
├── fillContent()          # Injects all panel HTML via template literals
├── renderAll()            # Re-renders all panels from current state
├── navigate(panelId)      # Switches the active panel
├── attachEventListeners() # Wires all button/input handlers after fillContent()
└── workflow               # Sub-object with timer/counter init and tick logic
```

**Data flow:** User action → event listener → mutate `App.state` → `App.saveState()` → call relevant render method.

**`fillContent()` is critical** — it dynamically injects inner HTML for all 5 panels using JS template literals. DOM elements only exist after `fillContent()` runs, so `attachEventListeners()` must always be called after it.

## State Schema

Stored under localStorage key `liverCopilotState`:

```javascript
{
  listeners: [{
    id, name, nickname, tags: string[],
    infoMemos: [{ id, tag, text, date }]   // tag: '趣味'|'好物'|'苦手'|'悩み'|'夢'|'交流'|'その他'
  }],
  roulettePresets: { presetName: string[] },
  gachaDecks: { deckName: string[] },
  originalGachas: { name: [{ item: string, weight: number }] },
  workflow: {
    duration: { started, elapsed, intervalId },   // intervalId is NOT persisted
    countdown: { endTime, intervalId },            // intervalId is NOT persisted
    counters: { counterName: number }
  },
  resources: { urls: [{ id, name, url }] },
  theme: 'dark' | 'light'
}
```

`saveState()` strips `intervalId` fields before serializing to avoid persisting timer handles.

## Data Migration

`loadState()` includes migration logic for old data formats. When adding new state fields, add a guard in `loadState()` (e.g., `if (!this.state.newField) this.state.newField = defaultValue`).

## Theme System

Theming is done entirely via CSS custom properties on `:root` (dark, default) and `html.light` (overrides). The `<html>` element's class is toggled between `'dark'` and `'light'`. All custom styles use `var(--*)` variables; Tailwind is used for layout utilities only.

Key CSS classes: `.card`, `.btn-accent`, `.btn-danger`, `.input-field`, `.textarea-field`, `.select-field`, `.nav-link`, `.tab-button`.

## Key Browser APIs Used

- **localStorage** — all persistence (`liverCopilotState`)
- **Canvas API** — roulette wheel rendering and animation
- **Web Audio API** — drumroll sound during roulette spin
- **FileReader / Blob** — JSON import/export
- **setInterval** — workflow timers (duration + countdown)

## Conventions

- The app is Japanese-language; all UI strings, comments, and user-facing text are in Japanese.
- `generateId()` produces collision-resistant IDs via `Date.now().toString(36) + Math.random().toString(36).substr(2)`.
- New panels or features follow the same pattern: add HTML in `fillContent()`, add render logic in `renderAll()`, wire events in `attachEventListeners()`.
- `App.state` is the only place data lives — never cache copies in DOM attributes or module-level variables.
