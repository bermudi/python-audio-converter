# Design: GUI Redesign for Usability

## Context
The current GUI was designed around exposing all CLI operations through checkboxes. This made sense for power users but creates a confusing experience for the primary use case: keeping a lossy mirror in sync with a FLAC library.

**Primary user workflow (80% of usage):**
1. Open app, point to FLAC library and mirror directory
2. See what's out of sync (missing/outdated files)
3. Click one button to fix it
4. Done

**Current workflow requires:**
1. Set paths
2. Choose "Side-by-Side" view mode
3. Set filter to "Needs Conversion"
4. Check "Update Mirror" operation
5. Select scope (but can only select one file!)
6. Click Run
7. Wonder if it worked

## Goals / Non-Goals

**Goals:**
- One-click conversion of missing files
- Multi-select for batch operations
- Clear visual feedback of library sync status
- Reduce cognitive load for common tasks

**Non-Goals:**
- Remove any functionality (all features remain accessible)
- Change the underlying conversion engine
- Modify CLI behavior

## Decisions

### Decision 1: Action buttons instead of checkboxes
**What:** Replace the operations checkbox panel with task-oriented buttons.
**Why:** Users think in tasks ("convert these files") not operations ("enable mirror phase, set scope, run").
**Alternatives:** Keep checkboxes but add quick-action buttons on top → rejected as cluttered.

### Decision 2: Unified table with checkbox column
**What:** Single table view with checkbox column for selection, source and mirror columns side-by-side.
**Why:** Two separate tables with single-select is confusing and broken for batch work.
**Alternatives:** Fix multi-select in dual tables → still confusing UX with two selection models.

### Decision 3: Stats bar as primary navigation
**What:** Clickable stats bar (Total: X | Missing: Y | ...) that filters the table when clicked.
**Why:** Users want to quickly see and act on specific file states.

### Decision 4: Progressive disclosure for advanced options
**What:** Move compression level, resample settings, worker counts to Settings dialog.
**Why:** Most users never change these; clutters the main UI.

## Component Structure

```
MainWindow
├── PathBar (Library + Mirror paths, Settings button)
├── StatsBar (clickable counters)
├── ActionToolbar (Convert Missing, Sync Outdated, Check Integrity, More▼)
├── FilterBar (dropdown + search)
├── UnifiedTableView (checkbox column + source + status + mirror columns)
├── SelectionBar (appears when files selected: Convert Selected, Check Selected)
└── CollapsibleLogPanel
```

## Migration Plan
1. Implement new components alongside existing code
2. Add feature flag to switch between old/new UI
3. Test new UI thoroughly
4. Remove old UI code after validation

## Risks / Trade-offs
- **Risk:** Existing users may be confused by new layout
  - **Mitigation:** Keep all functionality accessible, just reorganized
- **Risk:** Large refactor may introduce bugs
  - **Mitigation:** Feature flag allows fallback to old UI

## Open Questions
- Should we keep the "Convert" tab or merge everything into Library tab?
- What keyboard shortcuts should be added (Ctrl+Enter to convert selected)?
