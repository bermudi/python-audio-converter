## Context

The current `BrowserWorker` analyzes either a source library OR an output directory, but never correlates them. The `LibraryAnalysis` data model tracks individual files, not source↔output pairs. To show conversion status, we need a new analysis mode that joins source and output directories.

Users need to answer questions like:
- Which source files haven't been converted yet?
- Which outputs are orphaned (source deleted)?
- Which outputs are outdated (source changed)?
- What codec/quality were my files converted with?

## Goals / Non-Goals

**Goals:**
- Show source-to-output correlation in a single view
- Enable filtering by sync status
- Minimal UI complexity—prefer a view toggle over dual panels
- Reuse existing `analyze_library` and `analyze_output_directory` functions

**Non-Goals:**
- Real-time sync (users trigger scan manually or via auto-scan)
- Bidirectional editing (output → source correlation is read-only)
- Automatic conversion triggering from browser (use existing Convert tab)

## Decisions

### Decision 1: Single Table with Correlation Columns
Instead of side-by-side panels, extend the existing table with additional columns showing output status. This keeps the UI simple and familiar.

**Alternatives considered:**
- Dual-panel split view: More complex, harder to correlate visually
- Tree view with nested outputs: Cluttered for large libraries

### Decision 2: Correlation Analysis in `library_analyzer.py`
Add a new `analyze_library_with_outputs()` function that:
1. Scans source library (existing `analyze_library`)
2. Scans output directory (existing `analyze_output_directory`)
3. Correlates by relative path (source `Artist/Album/Track.flac` → output `Artist/Album/Track.m4a`)
4. Returns enriched `AnalyzedFile` objects with output metadata

**Data flow:**
```
Source FLAC files → analyze_library() → source_files[]
Output M4A/Opus  → analyze_output_directory() → output_files[]
                 ↓
         correlate_libraries()
                 ↓
         CorrelatedFile[] with:
           - source: AnalyzedFile
           - output: Optional[OutputInfo]
           - sync_status: SYNCED | OUTDATED | MISSING | ORPHAN
```

### Decision 3: View Mode Toggle
Add a dropdown/segmented control: "Source Only" | "With Outputs" | "Outputs Only"
- **Source Only**: Current behavior, shows FLAC library
- **With Outputs**: Correlated view showing source + output status
- **Outputs Only**: Shows output directory, highlights orphans

### Decision 4: Sync Status Calculation
Match source↔output by:
1. Relative path (minus extension)
2. For matched pairs, compare PAC_SRC_MD5 tag in output against source FLAC MD5
   - Match: SYNCED
   - Mismatch: OUTDATED
3. Source without output: MISSING
4. Output without source: ORPHAN (only visible in "Outputs Only" view)

## Risks / Trade-offs

- **Performance**: Correlating large libraries requires holding both analyses in memory. Mitigate with lazy loading or streaming correlation.
- **UI Clutter**: Adding output columns may make table wide. Mitigate with column visibility toggles.
- **Stale Data**: Correlation is point-in-time. Users must manually rescan after conversions.

## Open Questions

1. Should we persist correlation results or always recompute?
   - Recommendation: Always recompute; correlation is fast if individual analyses are cached in DB.

2. What columns to show in correlated view?
   - Recommendation: Path, Source Status, Output Status, Sync Status, Output Codec, Output Quality
