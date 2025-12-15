## ADDED Requirements

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

## MODIFIED Requirements

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
