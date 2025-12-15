## MODIFIED Requirements

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

## ADDED Requirements

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
