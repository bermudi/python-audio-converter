## 1. Analysis Layer

- [x] 1.1 Create `CorrelatedFile` dataclass with source, output, and sync_status fields
- [x] 1.2 Create `SyncStatus` enum: SYNCED, OUTDATED, MISSING, ORPHAN
- [x] 1.3 Implement `correlate_libraries(source_analysis, output_analysis)` function
- [x] 1.4 Add `analyze_library_with_outputs()` convenience function
- [x] 1.5 Handle extension mapping (.flac → .m4a/.opus based on output directory contents)

## 2. Table Model Updates

- [x] 2.1 Create `CorrelatedTableModel` extending `LibraryTableModel`
- [x] 2.2 Add columns: Sync Status, Output Codec, Output Quality, Output Size
- [x] 2.3 Implement color coding for sync status (green=synced, yellow=outdated, red=missing)
- [x] 2.4 Add sync status filtering to model

## 3. Browser Worker Updates

- [x] 3.1 Add `correlation_mode` parameter to `BrowserWorker`
- [x] 3.2 Implement correlated scan path in `BrowserWorker.run()`
- [x] 3.3 Emit `CorrelatedAnalysis` result type

## 4. GUI Integration

- [x] 4.1 Add view mode selector: "Source Only" | "With Outputs" | "Outputs Only"
- [x] 4.2 Connect view mode selector to trigger appropriate scan
- [x] 4.3 Swap table model based on view mode
- [x] 4.4 Update statistics bar for correlated view (synced/outdated/missing counts)
- [x] 4.5 Add sync status filter options to filter dropdown

## 5. Filter Updates

- [x] 5.1 Add "Needs Conversion" filter (shows MISSING + OUTDATED)
- [x] 5.2 Add "Orphaned Outputs" filter (shows ORPHAN, only in Outputs view)
- [x] 5.3 Add "Synced" filter

## 6. Testing

- [x] 6.1 Unit test: correlate_libraries with various scenarios
- [x] 6.2 Unit test: SyncStatus calculation (MD5 match/mismatch)
- [x] 6.3 Manual test: View mode switching
- [x] 6.4 Manual test: Filter by sync status
- [x] 6.5 Manual test: Large library performance (>10k files)
