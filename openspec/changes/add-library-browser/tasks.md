## 1. Backend - Library Analysis
- [ ] 1.1 Create `library_analyzer.py` module for non-destructive library analysis
- [ ] 1.2 Implement file status detection: integrity state, audio format, compression tag, PAC_* presence
- [ ] 1.3 Return structured data suitable for GUI display (file path, status flags, metadata)

## 2. GUI - Browser View
- [ ] 2.1 Add "Browser" sub-tab or panel to Library tab
- [ ] 2.2 Implement tree view showing directory structure with file status icons
- [ ] 2.3 Add table view alternative showing flat list with sortable columns
- [ ] 2.4 Add status column indicators (icons/colors) for each file state
- [ ] 2.5 Add filter controls: show only hi-res, show only legacy, show only needs-action

## 3. GUI - Statistics Panel
- [ ] 3.1 Add summary statistics bar: total files, hi-res, legacy, integrity unknown, etc.
- [ ] 3.2 Update statistics after scan completes
- [ ] 3.3 Make statistics clickable to filter view

## 4. Selection and Actions
- [ ] 4.1 Enable multi-select in browser view
- [ ] 4.2 Add context menu for selected files: "Run Integrity", "Adopt", etc.
- [ ] 4.3 Connect selections to operation runners from granular-operations proposal

## 5. Testing
- [ ] 5.1 Test scan on library with mixed file states
- [ ] 5.2 Test filtering and sorting
- [ ] 5.3 Test selection-based operations
