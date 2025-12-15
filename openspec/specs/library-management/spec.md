# Library Management

## Purpose
Maintain a FLAC library with integrity checks, compression policy enforcement, CD-quality resampling, and artwork extraction.
## Requirements
### Requirement: FLAC Library Management Command
The system SHALL provide a `library` command that maintains a FLAC library with integrity checks, compression policy enforcement, and artwork extraction.

#### Scenario: Library command invocation
- **WHEN** user runs `pac library --root ~/Music/FLAC`
- **THEN** the system SHALL scan, plan, and execute library maintenance actions

### Requirement: Integrity Verification
The system SHALL verify FLAC file integrity using `flac -t` before any modifications. Files that fail integrity checks SHALL be marked as "held" and excluded from further processing.

#### Scenario: Integrity check passes
- **WHEN** `flac -t` succeeds for a file
- **THEN** the file SHALL proceed to subsequent maintenance phases

#### Scenario: Integrity check fails
- **WHEN** `flac -t` fails for a file
- **THEN** the file SHALL be marked as "held" with the error message logged

### Requirement: CD Quality Resampling
The system SHALL resample FLAC files exceeding CD quality (16-bit/44.1kHz/2ch) down to CD quality when configured to do so.

#### Scenario: Hi-res file resampled
- **WHEN** a 24-bit/96kHz FLAC is processed with `--resample-to-cd`
- **THEN** the system SHALL resample to 16-bit/44.1kHz stereo FLAC

#### Scenario: CD quality file unchanged
- **WHEN** a 16-bit/44.1kHz stereo FLAC is processed
- **THEN** the system SHALL NOT resample the file

### Requirement: Compression Policy Enforcement
The system SHALL recompress FLAC files to a target compression level and write a COMPRESSION tag. Files with matching COMPRESSION tags SHALL be skipped.

#### Scenario: File recompressed
- **WHEN** a FLAC lacks a COMPRESSION tag or has a different level
- **THEN** the system SHALL recompress with `flac -V -{level}` and set the COMPRESSION tag

#### Scenario: Recompression skipped
- **WHEN** a FLAC has COMPRESSION tag matching target level
- **THEN** the system SHALL skip recompression

### Requirement: Artwork Extraction
The system SHALL extract front cover artwork to a structured folder path using a configurable pattern.

#### Scenario: Artwork extracted
- **WHEN** a FLAC contains embedded front cover art
- **THEN** the system SHALL write the artwork to `{art_root}/{artist}/{album}/front.jpg`

#### Scenario: No artwork present
- **WHEN** a FLAC has no embedded artwork
- **THEN** the system SHALL skip artwork extraction for that file

### Requirement: Phase-Based Execution
The system SHALL execute maintenance in phases: (1) Integrity, (2) Resample, (3) Recompress, (4) Extract Art, (5) Adopt Legacy, (6) Optional Mirror. Each phase SHALL be independently selectable and use configurable worker pools.

#### Scenario: Phased execution
- **WHEN** library maintenance runs with all phases selected
- **THEN** integrity checks SHALL complete before resampling begins

#### Scenario: Single phase execution
- **WHEN** library maintenance runs with only one phase selected
- **THEN** only that phase SHALL execute

### Requirement: Early Stop on Issues
The system SHALL stop processing a file on first error and mark it as "held" to prevent cascading changes.

#### Scenario: Error triggers hold
- **WHEN** any phase fails for a file
- **THEN** subsequent phases SHALL be skipped for that file

### Requirement: Mirror Integration
The system SHALL optionally trigger lossy mirror conversion (via existing convert-dir) after library maintenance, limited to files that passed all checks.

#### Scenario: Mirror after maintenance
- **WHEN** `--mirror-out` is provided
- **THEN** the system SHALL run convert-dir only for files without issues

### Requirement: Library Database Tracking
The system SHALL track maintenance state in SQLite tables: flac_checks (integrity), flac_policy (compression), art_exports (artwork).

#### Scenario: State persisted
- **WHEN** a file is processed
- **THEN** the system SHALL record timestamps and results in the database

### Requirement: Hold List Output
The system SHALL produce a list of held files with reasons for human review.

#### Scenario: Hold list generated
- **WHEN** files are held due to errors
- **THEN** the system SHALL output a list with file paths and failure reasons

### Requirement: Dry Run Mode
The system SHALL provide a dry-run mode that produces a maintenance plan without modifying any files.

#### Scenario: Library dry run
- **WHEN** `--dry-run` flag is provided
- **THEN** the system SHALL display planned actions without modifying files

### Requirement: Library GUI Tab
The system SHALL provide a GUI tab for FLAC library maintenance with settings, plan preview, execution controls, and a browser-first workflow for inspecting library state.

#### Scenario: Configure and run library maintenance
- **WHEN** user opens the Library tab and configures settings
- **THEN** the system SHALL allow setting compression level, resample toggle, and art extraction paths

#### Scenario: Dry-run preview
- **WHEN** user enables dry-run and starts a library operation
- **THEN** the system SHALL display planned actions without modifying files

#### Scenario: Browser is primary workspace
- **WHEN** user opens the Library tab
- **THEN** the Library Browser view SHALL be the primary workspace and remain usable without excessive scrolling

### Requirement: Library Progress Display
The system SHALL display per-phase progress counters and a list of held files during library maintenance.

#### Scenario: Phase counters update
- **WHEN** library maintenance is running
- **THEN** the GUI SHALL show counts for integrity checks, resamples, recompresses, and art exports

#### Scenario: Held files displayed
- **WHEN** files fail integrity or other checks
- **THEN** the GUI SHALL list held files with failure reasons

### Requirement: Granular Operation Selection
The GUI SHALL allow users to select which library maintenance operations to run independently, rather than executing all phases automatically.

#### Scenario: User runs only integrity check
- **WHEN** user selects only "Integrity Check" and clicks Run
- **THEN** the system SHALL run only the integrity verification phase

#### Scenario: User runs multiple selected operations
- **WHEN** user selects "Integrity Check" and "Recompress" and clicks Run
- **THEN** the system SHALL run integrity first, then recompress, skipping resample and artwork phases

### Requirement: Adopt Legacy Files Operation
The GUI SHALL provide an explicit "Adopt Legacy Files" operation that identifies output files lacking PAC_* tags and retags them without re-encoding.

#### Scenario: Adopt legacy M4A files
- **WHEN** user runs "Adopt Legacy Files" on a library with M4A files from older PAC versions
- **THEN** the system SHALL scan for outputs without PAC_* tags, display the count, and retag them with appropriate PAC_* metadata

#### Scenario: Adopt count shown before execution
- **WHEN** user initiates adopt operation
- **THEN** the system SHALL display the number of adoptable files before proceeding

### Requirement: Per-Operation Dry Run
The GUI SHALL support dry-run mode for individual operations, showing what would be done without making changes.

#### Scenario: Dry run single operation
- **WHEN** user enables dry-run and runs "Recompress"
- **THEN** the system SHALL display files that would be recompressed without modifying them

### Requirement: Library Scan Operation
The GUI SHALL provide a non-destructive scan operation that analyzes library state without modifying any files. Scans SHALL be triggered automatically when a valid path is entered, or manually via a Rescan button.

#### Scenario: Scan library
- **WHEN** user enters a valid library root path
- **THEN** the system SHALL automatically analyze all FLAC files and display their status without making changes

#### Scenario: Scan shows file count
- **WHEN** scan completes
- **THEN** the system SHALL display total file count and breakdown by status category

#### Scenario: Manual rescan
- **WHEN** user clicks the Rescan button on an already-scanned library
- **THEN** the system SHALL re-scan and refresh the display

### Requirement: Library Browser View
The GUI SHALL provide a browsable view of the library showing files with their status indicators. The browser SHALL support multiple view modes: Source Only (FLAC library), With Outputs (correlated source↔output), and Outputs Only (mirror directory).

#### Scenario: Tree view display
- **WHEN** scan completes
- **THEN** the system SHALL display files in a table matching directory hierarchy

#### Scenario: Status indicators shown
- **WHEN** files are displayed in browser
- **THEN** each file SHALL show icons/colors indicating: integrity status (unknown/ok/failed), audio format (CD/hi-res), compression status, legacy status (has PAC_* tags or not)

#### Scenario: View mode selector
- **WHEN** browser is displayed
- **THEN** a view mode selector SHALL allow switching between Source Only, With Outputs, and Outputs Only views

### Requirement: Browser Filtering
The GUI SHALL allow filtering the browser view by file status categories. Filters SHALL adapt based on current view mode.

#### Scenario: Filter by hi-res
- **WHEN** user selects "Hi-res only" filter
- **THEN** the browser SHALL show only files with sample rate > 44.1kHz or bit depth > 16

#### Scenario: Filter by legacy
- **WHEN** user selects "Legacy (no PAC_*)" filter
- **THEN** the browser SHALL show only output files lacking PAC_* metadata tags

#### Scenario: Filter by sync status
- **WHEN** user selects a sync status filter in correlated view
- **THEN** the browser SHALL show only files matching the selected sync status

### Requirement: File Selection for Operations
The GUI SHALL allow selecting specific files or folders in the browser for targeted operations.

#### Scenario: Select files for integrity check
- **WHEN** user selects specific files and chooses "Run Integrity Check"
- **THEN** the system SHALL run integrity check only on selected files

#### Scenario: Select folder for operation
- **WHEN** user selects a folder and chooses an operation
- **THEN** the system SHALL run the operation on all files within that folder

### Requirement: Library Statistics Summary
The GUI SHALL display summary statistics after scanning a library.

#### Scenario: Statistics displayed
- **WHEN** scan completes
- **THEN** the system SHALL show counts for: total files, hi-res files, CD-quality files, legacy files, files needing integrity check, files needing recompression

### Requirement: Library Settings Modal Dialog
The GUI SHALL provide access to library settings via a modal dialog so settings do not permanently reduce browser workspace.

#### Scenario: Open and close settings dialog
- **WHEN** user clicks "Library Settings…" in the Library tab
- **THEN** the system SHALL open a modal dialog showing library settings

#### Scenario: Settings persist
- **WHEN** user updates library settings in the modal dialog and confirms
- **THEN** the system SHALL apply those settings for subsequent library operations

### Requirement: Compact Operations Panel
The GUI SHALL provide a compact operations panel that allows selecting operations and running them without consuming excessive vertical space.

#### Scenario: Run selected operations
- **WHEN** user selects one or more operations and clicks Run
- **THEN** the system SHALL execute the chosen operations in phase order

### Requirement: Operation Scope Control
The GUI SHALL allow running operations on either the entire library or the current selection from the Library Browser.

#### Scenario: Default to selection scope
- **WHEN** the user has a non-empty selection in the Library Browser and initiates an operation
- **THEN** the system SHALL default the operation scope to the selection

#### Scenario: Run on entire library
- **WHEN** user sets operation scope to "Entire Library" and initiates an operation
- **THEN** the system SHALL run the operation over the full library root

### Requirement: Automatic Library Scan on Path Entry
The GUI SHALL automatically scan the library when a valid directory path is entered, without requiring a manual button click.

#### Scenario: Auto-scan on typed path
- **WHEN** user types a valid directory path in the Library root field and pauses typing
- **THEN** the system SHALL automatically begin scanning the library after a brief debounce delay (300-500ms)

#### Scenario: Auto-scan on browse dialog selection
- **WHEN** user selects a directory via the file browser dialog
- **THEN** the system SHALL automatically begin scanning the selected directory

#### Scenario: Auto-scan on paste
- **WHEN** user pastes a valid directory path into the Library root field
- **THEN** the system SHALL automatically begin scanning after the debounce delay

### Requirement: Debounced Path Validation
The GUI SHALL validate path input with debouncing to avoid excessive filesystem checks or scans during typing.

#### Scenario: Debounce prevents rapid scans
- **WHEN** user is actively typing in the path field
- **THEN** the system SHALL NOT start scanning until typing pauses for at least 300ms

#### Scenario: Path validation feedback
- **WHEN** debounce delay completes
- **THEN** the system SHALL show visual feedback indicating whether the path is valid (exists and is a directory)

### Requirement: Browser State on Path Change
The GUI SHALL update the browser view appropriately when the library path changes or becomes invalid.

#### Scenario: Path cleared
- **WHEN** user clears the library path field
- **THEN** the system SHALL clear the browser table and statistics

#### Scenario: Invalid path entered
- **WHEN** user enters a path that does not exist or is not a directory
- **THEN** the system SHALL show an error indicator and NOT attempt to scan

#### Scenario: Path changed during scan
- **WHEN** user changes the path while a scan is in progress
- **THEN** the system SHALL cancel the current scan and start a new scan for the updated path

### Requirement: Manual Rescan Option
The GUI SHALL provide a manual rescan button to refresh the library view on demand.

#### Scenario: Manual rescan
- **WHEN** user clicks the Rescan button
- **THEN** the system SHALL re-scan the current library path regardless of cache state

### Requirement: Correlated Library View
The GUI SHALL provide a correlated view that displays source FLAC files alongside their corresponding output file status.

#### Scenario: View source with output status
- **WHEN** user selects "With Outputs" view mode and both library and mirror paths are set
- **THEN** the browser SHALL display each source file with columns showing output sync status, codec, and quality

#### Scenario: Output missing
- **WHEN** a source file has no corresponding output in the mirror directory
- **THEN** the system SHALL display sync status as "Missing" with visual indicator (e.g., red)

#### Scenario: Output synced
- **WHEN** a source file has a corresponding output with matching PAC_SRC_MD5
- **THEN** the system SHALL display sync status as "Synced" with visual indicator (e.g., green)

#### Scenario: Output outdated
- **WHEN** a source file has a corresponding output but PAC_SRC_MD5 does not match source MD5
- **THEN** the system SHALL display sync status as "Outdated" with visual indicator (e.g., yellow)

### Requirement: View Mode Selection
The GUI SHALL allow users to switch between different browser view modes.

#### Scenario: Switch to source-only view
- **WHEN** user selects "Source Only" view mode
- **THEN** the browser SHALL display only the FLAC library analysis (current behavior)

#### Scenario: Switch to correlated view
- **WHEN** user selects "With Outputs" view mode
- **THEN** the browser SHALL display source files with output correlation columns

#### Scenario: Switch to outputs-only view
- **WHEN** user selects "Outputs Only" view mode
- **THEN** the browser SHALL display only the output directory contents, highlighting orphans

### Requirement: Sync Status Filtering
The GUI SHALL allow filtering the correlated view by sync status.

#### Scenario: Filter to needs conversion
- **WHEN** user selects "Needs Conversion" filter in correlated view
- **THEN** the browser SHALL show only files with MISSING or OUTDATED sync status

#### Scenario: Filter to orphaned outputs
- **WHEN** user selects "Orphaned Outputs" filter in outputs view
- **THEN** the browser SHALL show only output files without corresponding sources

#### Scenario: Filter to synced files
- **WHEN** user selects "Synced" filter in correlated view
- **THEN** the browser SHALL show only files with SYNCED status

### Requirement: Orphan Detection
The GUI SHALL identify output files that have no corresponding source file (orphans).

#### Scenario: Orphan output detected
- **WHEN** an output file exists at a path with no corresponding source FLAC
- **THEN** the system SHALL mark the output as "Orphan" in the outputs view

#### Scenario: Orphan count displayed
- **WHEN** correlated or outputs scan completes
- **THEN** the statistics bar SHALL display the count of orphaned outputs

### Requirement: Correlated Statistics
The GUI SHALL display summary statistics for the correlated view.

#### Scenario: Sync statistics shown
- **WHEN** correlated scan completes
- **THEN** the statistics bar SHALL show counts for: Total, Synced, Outdated, Missing, Orphans

