## ADDED Requirements

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

## MODIFIED Requirements

### Requirement: Phase-Based Execution
The system SHALL execute maintenance in phases: (1) Integrity, (2) Resample, (3) Recompress, (4) Extract Art, (5) Adopt Legacy, (6) Optional Mirror. Each phase SHALL be independently selectable and use configurable worker pools.

#### Scenario: Phased execution
- **WHEN** library maintenance runs with all phases selected
- **THEN** integrity checks SHALL complete before resampling begins

#### Scenario: Single phase execution
- **WHEN** library maintenance runs with only one phase selected
- **THEN** only that phase SHALL execute
