## MODIFIED Requirements

### Requirement: Library Browser Multi-Select
The GUI SHALL support selecting multiple files in all table views using standard selection patterns (Ctrl+Click, Shift+Click, Ctrl+A).

#### Scenario: Select multiple files with Ctrl+Click
- **WHEN** user Ctrl+clicks multiple rows in the library table
- **THEN** all clicked rows are added to the selection
- **AND** selection count is displayed in the UI

#### Scenario: Select range with Shift+Click
- **WHEN** user clicks a row, then Shift+clicks another row
- **THEN** all rows between the two clicks are selected

#### Scenario: Select all with Ctrl+A
- **WHEN** user presses Ctrl+A while table is focused
- **THEN** all visible rows are selected

## ADDED Requirements

### Requirement: Quick Action Buttons
The GUI SHALL provide prominent action buttons for common library operations, eliminating the need to configure checkbox options.

#### Scenario: Convert Missing button
- **WHEN** the library scan shows files with "missing" status
- **THEN** a "Convert Missing (N)" button is displayed showing the count
- **AND** clicking the button starts conversion of all missing files

#### Scenario: Convert Missing disabled when none missing
- **WHEN** no files have "missing" status
- **THEN** the "Convert Missing" button is disabled or hidden

#### Scenario: Sync Outdated button
- **WHEN** the library scan shows files with "outdated" status
- **THEN** a "Sync Outdated (N)" button is displayed
- **AND** clicking the button reconverts all outdated files

### Requirement: Selection-Based Actions
The GUI SHALL provide contextual action buttons when files are selected.

#### Scenario: Convert Selected appears on selection
- **WHEN** user selects one or more files in the table
- **THEN** a "Convert Selected (N)" button appears
- **AND** clicking converts only the selected files

#### Scenario: Actions update with selection changes
- **WHEN** user changes selection (adds/removes files)
- **THEN** the selection action buttons update their counts immediately

### Requirement: Unified Stats Bar
The GUI SHALL display a stats bar showing sync status counts that act as quick filters.

#### Scenario: Stats bar shows counts
- **WHEN** library scan completes
- **THEN** stats bar displays: Total, Synced, Missing, Outdated, Orphan counts

#### Scenario: Clicking stat filters table
- **WHEN** user clicks "Missing: 70" in stats bar
- **THEN** table is filtered to show only files with missing status

#### Scenario: Missing count highlighted
- **WHEN** missing count is greater than zero
- **THEN** the Missing stat is visually highlighted (color/bold)

### Requirement: Simplified Operations Panel
The GUI SHALL hide advanced operation settings behind a Settings dialog, showing only essential actions in the main interface.

#### Scenario: Settings dialog contains advanced options
- **WHEN** user opens Settings dialog
- **THEN** dialog shows: compression level, resample options, codec selection, worker counts

#### Scenario: Main UI shows only actions
- **WHEN** user views the Library tab
- **THEN** only action buttons are visible (no operation checkboxes)
- **AND** Dry Run toggle is available in toolbar or settings
