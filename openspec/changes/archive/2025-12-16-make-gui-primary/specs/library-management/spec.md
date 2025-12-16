## ADDED Requirements
### Requirement: Debug/Testing CLI Interface (Library Management)
The system SHALL provide a CLI interface for debug/testing and advanced usage of library management features. The CLI SHALL NOT be the primary user-facing interface and SHALL NOT be highlighted in user-facing documentation.

#### Scenario: Developer runs library maintenance from CLI
- **WHEN** a developer runs the CLI to execute library maintenance
- **THEN** the system SHALL perform the requested operations and report results via structured console output and exit codes

#### Scenario: Documentation positions GUI as primary
- **WHEN** project documentation describes how to manage a FLAC library with PAC
- **THEN** the GUI Library tab SHALL be presented as the primary workflow and the CLI SHALL be presented as optional (debug/testing and advanced usage)

#### Scenario: Packaged CLI entrypoint
- **WHEN** PAC is installed as a Python package
- **THEN** a `pac-cli` entrypoint SHALL be provided for CLI access

## MODIFIED Requirements
### Requirement: FLAC Library Management Command
The system SHALL provide a `library` command that maintains a FLAC library with integrity checks, compression policy enforcement, and artwork extraction. This CLI command SHALL be considered a debug/testing interface; the GUI Library tab SHALL be the primary user-facing interface.

#### Scenario: Library command invocation
- **WHEN** a developer runs `pac library --root ~/Music/FLAC`
- **THEN** the system SHALL scan, plan, and execute library maintenance actions
