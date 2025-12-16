## ADDED Requirements
### Requirement: Debug/Testing CLI Interface (Audio Conversion)
The system SHALL provide a CLI interface for debug/testing and advanced usage of audio conversion features. The CLI SHALL NOT be the primary user-facing interface and SHALL NOT be highlighted in user-facing documentation.

#### Scenario: Developer runs conversion from CLI
- **WHEN** a developer runs the CLI to execute `convert` or `convert-dir`
- **THEN** the system SHALL perform the conversion and report success/failure via exit codes

#### Scenario: Documentation positions GUI as primary
- **WHEN** project documentation describes how to use PAC
- **THEN** the GUI entrypoint SHALL be presented as the primary interface and the CLI SHALL be presented as optional (debug/testing and advanced usage)

#### Scenario: Packaged CLI entrypoint
- **WHEN** PAC is installed as a Python package
- **THEN** a `pac-cli` entrypoint SHALL be provided for CLI access

## MODIFIED Requirements
### Requirement: Dry Run Mode
The system SHALL provide a dry-run mode that produces a plan without encoding. This capability SHALL be available from the GUI. A CLI flag MAY expose this capability for debug/testing.

#### Scenario: Dry run execution (CLI)
- **WHEN** `--dry-run` flag is provided
- **THEN** the system SHALL display planned actions without modifying any files

### Requirement: Exit Codes
The system SHALL exit with: 0 (success, no failures), 2 (completed with file failures), 3 (preflight failure: no suitable encoder found). Exit codes SHALL be used by the CLI for debug/testing and MAY be surfaced by the GUI as status messages.

#### Scenario: Successful run
- **WHEN** all files convert successfully
- **THEN** exit code SHALL be 0

#### Scenario: Partial failure
- **WHEN** some files fail to convert
- **THEN** exit code SHALL be 2
