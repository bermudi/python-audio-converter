## ADDED Requirements

### Requirement: GUI CLI Path Arguments
The GUI SHALL accept command-line arguments to pre-populate path fields on startup.

#### Scenario: Launch with FLAC library path
- **WHEN** user runs `python -m app.gui.main --flac-library ~/Music/FLAC`
- **THEN** the Library tab's "Library:" field SHALL be pre-populated with the provided path

#### Scenario: Launch with mirror library path
- **WHEN** user runs `python -m app.gui.main --mirror-library ~/Music/Opus`
- **THEN** the Library tab's "Mirror:" field SHALL be pre-populated with the provided path

#### Scenario: Launch with convert source and output paths
- **WHEN** user runs `python -m app.gui.main --source ~/FLAC --output ~/AAC`
- **THEN** the Convert tab's source and destination fields SHALL be pre-populated with the provided paths

### Requirement: GUI Drag-Drop Path Input
The GUI path input fields SHALL accept drag-and-drop of directories from file managers, supporting both X11 and Wayland display protocols.

#### Scenario: Drop folder on Library path field
- **WHEN** user drags a folder from a file manager and drops it on the "Library:" input field
- **THEN** the field SHALL be populated with the dropped folder's path

#### Scenario: Drop folder on Mirror path field
- **WHEN** user drags a folder from a file manager and drops it on the "Mirror:" input field
- **THEN** the field SHALL be populated with the dropped folder's path

#### Scenario: Drop folder on Convert source field
- **WHEN** user drags a folder and drops it on the Convert tab's source input field
- **THEN** the field SHALL be populated with the dropped folder's path

#### Scenario: Wayland compatibility
- **WHEN** user drags a folder from Dolphin (KDE) on Wayland
- **THEN** the drop SHALL be accepted and path populated correctly
