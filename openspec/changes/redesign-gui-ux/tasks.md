# Tasks: Redesign GUI for Better Usability

## 1. Enable Multi-Select
- [x] 1.1 Change `sbs_source_table` selection mode from `SingleSelection` to `ExtendedSelection`
- [x] 1.2 Change `sbs_mirror_table` selection mode from `SingleSelection` to `ExtendedSelection`
- [ ] 1.3 Add checkbox column to table models for visual multi-select
- [x] 1.4 Update selection sync logic to handle multi-select properly

## 2. Redesign Statistics Bar
- [x] 2.1 Create unified stats bar showing: Total, Synced, Missing, Outdated, Orphan counts
- [x] 2.2 Make stats clickable to filter the table
- [x] 2.3 Highlight actionable stats (Missing, Outdated) with color

## 3. Create Action-Oriented Toolbar
- [x] 3.1 Replace checkbox operations panel with horizontal action toolbar
- [x] 3.2 Add "Convert Missing (N)" button - converts all missing files
- [x] 3.3 Add "Sync Outdated (N)" button - reconverts outdated files
- [x] 3.4 Add "Check Integrity" button - runs integrity check on library
- [x] 3.5 Add "More ▼" dropdown for less common operations (Adopt, Recompress, Extract Art)
- [x] 3.6 Disable action buttons when no files match (e.g., disable "Convert Missing" when count is 0)

## 4. Add Selection-Based Actions
- [x] 4.1 Show "Convert Selected (N)" button when files are selected
- [x] 4.2 Show "Check Selected (N)" button for integrity check on selection
- [x] 4.3 Add "Select All Missing" quick action
- [ ] 4.4 Add "Select All Outdated" quick action

## 5. Simplify Layout
- [x] 5.1 Remove left operations panel entirely
- [x] 5.2 Move Dry Run checkbox to toolbar or settings
- [x] 5.3 Consolidate filter controls to single row
- [x] 5.4 Make log panel collapsible (default collapsed)

## 6. Update Settings Dialog
- [x] 6.1 Move advanced options to Settings dialog (compression level, resample, etc.)
- [x] 6.2 Add codec selection to Settings (currently hidden)
- [x] 6.3 Add worker thread count to Settings

## 7. Testing & Polish
- [ ] 7.1 Test multi-select with 1000+ files
- [ ] 7.2 Verify keyboard shortcuts work (Ctrl+A, Shift+Click)
- [x] 7.3 Update tooltips for new UI elements
- [ ] 7.4 Test all action buttons trigger correct operations
