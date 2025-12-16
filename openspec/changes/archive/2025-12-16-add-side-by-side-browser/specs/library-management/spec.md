## ADDED Requirements

### Requirement: Side-by-Side Browser View
The GUI SHALL provide a side-by-side view mode displaying the source library and mirror library in two synchronized panels.

#### Scenario: Enable side-by-side view
- **WHEN** user selects "Side-by-Side" view mode and both library and mirror paths are set
- **THEN** the browser SHALL display two panels: source library (left) and mirror library (right)

#### Scenario: Side-by-side requires both paths
- **WHEN** user selects "Side-by-Side" view mode without a mirror path set
- **THEN** the system SHALL display an error prompting for the mirror path

### Requirement: Side-by-Side Selection Synchronization
The GUI SHALL synchronize selection between the two side-by-side panels, highlighting counterpart files when a selection is made.

#### Scenario: Select source file shows mirror counterpart
- **WHEN** user selects a source file in the left panel
- **THEN** the right panel SHALL highlight and scroll to the corresponding output file (if it exists)

#### Scenario: Select mirror file shows source counterpart
- **WHEN** user selects an output file in the right panel
- **THEN** the left panel SHALL highlight and scroll to the corresponding source file (if it exists)

#### Scenario: No counterpart exists
- **WHEN** user selects a file that has no counterpart (orphan or missing)
- **THEN** the other panel SHALL clear its selection and show no highlight

### Requirement: Side-by-Side Linked Scrolling
The GUI SHALL synchronize vertical scrolling between the two side-by-side panels by default, keeping counterpart files aligned.

#### Scenario: Scroll left panel syncs right panel
- **WHEN** user scrolls the source panel (left)
- **THEN** the mirror panel (right) SHALL scroll to keep corresponding files aligned

#### Scenario: Scroll right panel syncs left panel
- **WHEN** user scrolls the mirror panel (right)
- **THEN** the source panel (left) SHALL scroll to keep corresponding files aligned

### Requirement: Side-by-Side Sync Status Indicators
The GUI SHALL display visual sync status indicators in both panels of the side-by-side view.

#### Scenario: Synced file indicator
- **WHEN** a source file has a matching output with valid PAC_SRC_MD5
- **THEN** both panels SHALL show a green "Synced" indicator for that file pair

#### Scenario: Missing output indicator
- **WHEN** a source file has no corresponding output
- **THEN** the source panel SHALL show a red "Missing" indicator and the mirror panel SHALL show an empty placeholder row

#### Scenario: Orphan output indicator
- **WHEN** an output file has no corresponding source
- **THEN** the mirror panel SHALL show a yellow "Orphan" indicator and the source panel SHALL show an empty placeholder row

### Requirement: Side-by-Side Filtering
The GUI SHALL allow filtering the side-by-side view, applying filters to both panels simultaneously.

#### Scenario: Filter to missing outputs
- **WHEN** user selects "Missing" filter in side-by-side view
- **THEN** both panels SHALL show only source files without corresponding outputs

#### Scenario: Filter to orphaned outputs
- **WHEN** user selects "Orphaned" filter in side-by-side view
- **THEN** both panels SHALL show only output files without corresponding sources

#### Scenario: Clear filter
- **WHEN** user selects "All Files" filter
- **THEN** both panels SHALL show all files

## MODIFIED Requirements

### Requirement: View Mode Selection
The GUI SHALL allow users to switch between different browser view modes.

#### Scenario: Switch to source-only view
- **WHEN** user selects "Source Only" view mode
- **THEN** the browser SHALL display only the FLAC library analysis (current behavior)

#### Scenario: Switch to correlated view
- **WHEN** user selects "With Outputs" view mode
- **THEN** the browser SHALL display source files with output correlation columns

#### Scenario: Switch to outputs-only view
- **WHEN** user selects "Outputs Only" view mode
- **THEN** the browser SHALL display only the output directory contents, highlighting orphans

#### Scenario: Switch to side-by-side view
- **WHEN** user selects "Side-by-Side" view mode
- **THEN** the browser SHALL display two synchronized panels for source and mirror libraries
