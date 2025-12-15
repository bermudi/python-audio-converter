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
The system SHALL execute maintenance in phases: (1) Integrity, (2) Resample, (3) Recompress, (4) Extract Art, (5) Optional Mirror. Each phase SHALL use configurable worker pools.

#### Scenario: Phased execution
- **WHEN** library maintenance runs
- **THEN** integrity checks SHALL complete before resampling begins

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
