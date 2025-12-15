## ADDED Requirements

### Requirement: Automatic Preflight on Startup
The GUI SHALL automatically run encoder preflight checks when the application starts, without requiring manual user action.

#### Scenario: Preflight runs on startup
- **WHEN** user launches the GUI application
- **THEN** the system SHALL immediately begin probing for available encoders in a background thread

#### Scenario: Convert tab enabled after preflight
- **WHEN** preflight completes successfully (at least one encoder available)
- **THEN** the Convert and Plan buttons SHALL be enabled without user intervention

#### Scenario: Preflight failure on startup
- **WHEN** preflight completes with no available encoder
- **THEN** the GUI SHALL display a clear error message and keep Convert controls disabled

### Requirement: Preflight Status Indicator
The GUI SHALL display preflight status during the check, showing progress and final encoder availability.

#### Scenario: Status shown during check
- **WHEN** preflight is running
- **THEN** the GUI SHALL display "Checking encoders..." or equivalent status indicator

#### Scenario: Encoder availability displayed
- **WHEN** preflight completes
- **THEN** the GUI SHALL display which encoders are available (e.g., "Encoders: libfdk_aac, libopus")

### Requirement: Manual Preflight Re-check
The GUI SHALL provide a way to manually re-run preflight checks after startup, accessible via menu or settings.

#### Scenario: User triggers re-check
- **WHEN** user selects "Re-check Encoders" from menu
- **THEN** the system SHALL re-run preflight and update encoder availability status

## MODIFIED Requirements

### Requirement: GUI Application
The system SHALL provide a GUI that allows: selecting source/destination directories, scanning to show file counts, starting/stopping/pausing conversion, viewing per-file progress and logs. The GUI SHALL automatically verify encoder availability on startup without requiring manual preflight action.

#### Scenario: GUI scan and convert
- **WHEN** user selects directories and clicks Scan
- **THEN** the GUI SHALL display counts of new/changed/unchanged files and allow starting conversion

#### Scenario: GUI ready after startup
- **WHEN** application launches and preflight succeeds
- **THEN** the Convert tab SHALL be immediately usable without additional clicks
