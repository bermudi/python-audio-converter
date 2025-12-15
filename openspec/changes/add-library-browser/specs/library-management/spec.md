## ADDED Requirements

### Requirement: Library Scan Operation
The GUI SHALL provide a non-destructive scan operation that analyzes library state without modifying any files.

#### Scenario: Scan library
- **WHEN** user clicks "Scan" on a library root
- **THEN** the system SHALL analyze all FLAC files and display their status without making changes

#### Scenario: Scan shows file count
- **WHEN** scan completes
- **THEN** the system SHALL display total file count and breakdown by status category

### Requirement: Library Browser View
The GUI SHALL provide a browsable view of the library showing files with their status indicators.

#### Scenario: Tree view display
- **WHEN** scan completes
- **THEN** the system SHALL display files in a tree structure matching directory hierarchy

#### Scenario: Status indicators shown
- **WHEN** files are displayed in browser
- **THEN** each file SHALL show icons/colors indicating: integrity status (unknown/ok/failed), audio format (CD/hi-res), compression status, legacy status (has PAC_* tags or not)

### Requirement: Browser Filtering
The GUI SHALL allow filtering the browser view by file status categories.

#### Scenario: Filter by hi-res
- **WHEN** user selects "Hi-res only" filter
- **THEN** the browser SHALL show only files with sample rate > 44.1kHz or bit depth > 16

#### Scenario: Filter by legacy
- **WHEN** user selects "Legacy (no PAC_*)" filter
- **THEN** the browser SHALL show only output files lacking PAC_* metadata tags

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
