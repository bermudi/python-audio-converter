# Change: Redesign GUI for Better Usability

## Why
The current GUI has major usability issues:
1. **Single file selection only** - Side-by-side view limits to one file, defeating the purpose of batch operations
2. **No obvious way to convert missing files** - Users must understand complex filter/scope/operations workflow
3. **Cluttered operations panel** - Too many checkboxes that most users don't understand
4. **Ambiguous "Run" button** - Runs whatever operations are checked, unclear what will happen

## What Changes
- **BREAKING**: Replace checkbox-based operations panel with action-oriented toolbar
- **BREAKING**: Redesign main workflow around common tasks (Convert Missing, Sync Library, Check Integrity)
- Enable multi-select in all table views
- Add prominent "Convert Missing" button that's always visible when missing files exist
- Simplify the interface by hiding advanced options behind a settings dialog
- Add clear visual feedback for what action will be performed

### New UI Concept
```
┌─────────────────────────────────────────────────────────────────────┐
│ Library: [path field]  Mirror: [path field]  [Settings] [Rescan]   │
├─────────────────────────────────────────────────────────────────────┤
│ Total: 1082 │ Synced: 1012 │ Missing: 70 │ Outdated: 0 │ Orphan: 0 │
├─────────────────────────────────────────────────────────────────────┤
│ [Convert Missing (70)] [Sync Outdated] [Check Integrity] [More ▼]  │
├─────────────────────────────────────────────────────────────────────┤
│ Filter: [All ▼] [Search...]                                        │
│ ┌─────────────────────────────────────────────────────────────────┐ │
│ │ ☐ │ Source File                    │ Status  │ Mirror File     │ │
│ │ ☑ │ Artist/Album/01 Track.flac     │ Missing │ —               │ │
│ │ ☑ │ Artist/Album/02 Track.flac     │ Missing │ —               │ │
│ │ ☐ │ Artist/Album/03 Track.flac     │ Synced  │ .../03 Track.m4a│ │
│ └─────────────────────────────────────────────────────────────────┘ │
│ Selected: 2 files  [Convert Selected] [Check Selected]             │
├─────────────────────────────────────────────────────────────────────┤
│ ▶ Log                                                               │
└─────────────────────────────────────────────────────────────────────┘
```

### Key Design Principles
1. **Task-oriented**: Primary actions are buttons, not checkbox combinations
2. **Multi-select first**: Checkbox column for batch selection, Ctrl/Shift click support
3. **Contextual actions**: "Convert Selected" appears when files are selected
4. **Clear status**: Stats bar shows exactly what needs attention
5. **Progressive disclosure**: Advanced options in Settings dialog, not main UI

## Impact
- Affected specs: `library-management` (GUI requirements)
- Affected code: `app/gui/main.py` (complete rewrite of Library tab)
- User workflow: Simpler, but existing muscle memory will need relearning
