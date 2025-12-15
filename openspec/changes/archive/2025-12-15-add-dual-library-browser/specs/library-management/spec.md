## ADDED Requirements

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

## MODIFIED Requirements

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
