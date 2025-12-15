## ADDED Requirements

### Requirement: Library GUI Tab
The system SHALL provide a GUI tab for FLAC library maintenance with settings, plan preview, and execution controls.

#### Scenario: Configure and run library maintenance
- **WHEN** user opens the Library tab and configures settings
- **THEN** the system SHALL allow setting compression level, resample toggle, and art extraction paths

#### Scenario: Dry-run preview
- **WHEN** user clicks Plan button
- **THEN** the system SHALL display planned actions without modifying files

### Requirement: Library Progress Display
The system SHALL display per-phase progress counters and a list of held files during library maintenance.

#### Scenario: Phase counters update
- **WHEN** library maintenance is running
- **THEN** the GUI SHALL show counts for integrity checks, resamples, recompresses, and art exports

#### Scenario: Held files displayed
- **WHEN** files fail integrity or other checks
- **THEN** the GUI SHALL list held files with failure reasons
