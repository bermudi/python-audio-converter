# Audio Conversion

## Purpose
Mirror FLAC libraries to AAC (M4A) or Opus with stateless change detection and metadata preservation.
## Requirements
### Requirement: Directory Mirroring
The system SHALL mirror a source FLAC library to an AAC (M4A) or Opus destination, preserving relative directory structure and file base names, changing only the extension.

#### Scenario: FLAC to M4A conversion
- **WHEN** a FLAC file exists at `source/Artist/Album/01 Track.flac`
- **THEN** the output SHALL be created at `destination/Artist/Album/01 Track.m4a`

#### Scenario: FLAC to Opus conversion
- **WHEN** codec is set to Opus and a FLAC file exists at `source/Artist/Album/01 Track.flac`
- **THEN** the output SHALL be created at `destination/Artist/Album/01 Track.opus`

### Requirement: Encoder Backend Selection
The system SHALL encode AAC using this ordered backend selection: (1) FFmpeg with libfdk_aac; (2) FFmpeg decode piped to qaac; (3) FFmpeg decode piped to fdkaac. If none are available, preflight SHALL fail with clear remediation guidance.

#### Scenario: Preferred encoder available
- **WHEN** FFmpeg with libfdk_aac is available
- **THEN** the system SHALL use libfdk_aac for encoding

#### Scenario: Fallback to qaac
- **WHEN** libfdk_aac is unavailable but qaac is available
- **THEN** the system SHALL pipe FFmpeg decode to qaac

#### Scenario: No encoder available
- **WHEN** no suitable AAC encoder is available
- **THEN** the system SHALL fail preflight with exit code 3 and display remediation guidance

### Requirement: Stateless Operation
The system SHALL NOT require a local database. All change detection SHALL derive from current source tree, destination tree, and PAC_* metadata embedded in outputs.

#### Scenario: Resumable run without database
- **WHEN** a conversion run is interrupted and restarted
- **THEN** the system SHALL resume by reading PAC_* tags from existing outputs without requiring external state

### Requirement: PAC Fingerprint Embedding
The system SHALL embed in each output: PAC_SRC_MD5 (FLAC STREAMINFO MD5), PAC_ENCODER, PAC_QUALITY, PAC_VERSION, PAC_SOURCE_REL.

#### Scenario: Tags embedded in M4A
- **WHEN** an M4A file is created
- **THEN** the system SHALL write PAC_* fields as MP4 freeform atoms (e.g., `----:org.pac:src_md5`)

#### Scenario: Tags embedded in Opus
- **WHEN** an Opus file is created
- **THEN** the system SHALL write PAC_* fields as Vorbis comments

### Requirement: Move/Rename Detection
The system SHALL detect moved/renamed sources by matching PAC_SRC_MD5 in destination and MAY rename outputs instead of re-encoding.

#### Scenario: Source file renamed
- **WHEN** a source FLAC is renamed but content unchanged (same MD5)
- **THEN** the system SHALL rename the existing output to match the new source path

### Requirement: Metadata Preservation
The system SHALL preserve metadata tags (artist, album, title, track number, disc, date/year, genre, album artist, compilation flag, MusicBrainz IDs when present) and cover art when possible. Failures to copy any field or art SHALL be logged per file.

#### Scenario: Tags copied from FLAC to M4A
- **WHEN** a FLAC with metadata is converted
- **THEN** all standard tags SHALL be mapped to equivalent MP4 atoms

#### Scenario: Cover art preserved
- **WHEN** source FLAC contains embedded cover art
- **THEN** the output SHALL contain the cover art in the appropriate format

### Requirement: Parallel Processing
The system SHALL support parallel conversion with a configurable number of workers. Default SHALL be a sensible fraction of available CPU cores.

#### Scenario: Multi-worker conversion
- **WHEN** workers is set to 8
- **THEN** up to 8 files SHALL be encoded concurrently

### Requirement: Dry Run Mode
The system SHALL provide a dry-run mode that produces a plan without encoding.

#### Scenario: Dry run execution
- **WHEN** `--dry-run` flag is provided
- **THEN** the system SHALL display planned actions without modifying any files

### Requirement: Prune Orphans
The system SHALL optionally identify and prune orphan outputs whose PAC_SRC_MD5 has no source counterpart.

#### Scenario: Orphan file detected
- **WHEN** `--prune` flag is provided and an output has no matching source
- **THEN** the output file SHALL be deleted

### Requirement: Collision Safety
The system SHALL handle name conflicts and illegal characters in destination filesystem, applying safe transformations and logging any changes. This SHALL include case-insensitive collision safety for common removable filesystems (e.g., FAT/exFAT).

#### Scenario: Case collision on FAT filesystem
- **WHEN** two source files differ only by case
- **THEN** the system SHALL generate unique destination names to avoid collision

### Requirement: Exit Codes
The system SHALL exit with: 0 (success, no failures), 2 (completed with file failures), 3 (preflight failure: no suitable encoder found).

#### Scenario: Successful run
- **WHEN** all files convert successfully
- **THEN** exit code SHALL be 0

#### Scenario: Partial failure
- **WHEN** some files fail to convert
- **THEN** exit code SHALL be 2

### Requirement: GUI Application
The system SHALL provide a GUI that allows: selecting source/destination directories, scanning to show file counts, starting/stopping/pausing conversion, viewing per-file progress and logs. The GUI SHALL automatically verify encoder availability on startup without requiring manual preflight action.

#### Scenario: GUI scan and convert
- **WHEN** user selects directories and clicks Scan
- **THEN** the GUI SHALL display counts of new/changed/unchanged files and allow starting conversion

#### Scenario: GUI ready after startup
- **WHEN** application launches and preflight succeeds
- **THEN** the Convert tab SHALL be immediately usable without additional clicks

### Requirement: Adoption Policy
When outputs lack PAC_* tags (from older runs), the system SHALL optionally adopt them as up-to-date if present at expected path and retag to add PAC_*. A `--no-adopt` flag SHALL force re-encode instead.

#### Scenario: Adopt existing output
- **WHEN** an output exists at expected path without PAC_* tags
- **THEN** the system SHALL retag it with PAC_* fields without re-encoding

#### Scenario: Force re-encode with no-adopt
- **WHEN** `--no-adopt` flag is provided
- **THEN** the system SHALL re-encode files lacking PAC_* tags

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

### Requirement: Lazy Wine Encoder Detection
The system SHALL support lazy detection of Wine-based encoders (qaac) controlled by the `probe_wine_encoders` setting. When disabled (default), startup preflight SHALL skip qaac probing to avoid Wine initialization overhead and dialogs.

#### Scenario: Startup skips qaac when setting is false
- **WHEN** `probe_wine_encoders=false` (default)
- **THEN** startup preflight SHALL NOT invoke qaac or trigger Wine

#### Scenario: Manual Wine encoder probe
- **WHEN** user clicks "Check Wine Encoders" in GUI
- **THEN** the system SHALL probe qaac availability and update encoder status

#### Scenario: Wine probing enabled in settings
- **WHEN** `probe_wine_encoders=true`
- **THEN** startup preflight SHALL probe qaac as part of normal encoder detection

### Requirement: AAC Encoder Preference
The system SHALL allow users to select their preferred AAC encoder when multiple encoders are available, stored in the `aac_encoder_preference` setting. This overrides the automatic selection order.

#### Scenario: User selects preferred encoder
- **WHEN** multiple AAC encoders are available (e.g., libfdk_aac and qaac)
- **THEN** the GUI SHALL display a dropdown allowing the user to choose their preferred encoder

#### Scenario: Preference persists across sessions
- **WHEN** user selects an encoder preference
- **THEN** the preference SHALL be saved to settings and used in future sessions

#### Scenario: Preferred encoder unavailable
- **WHEN** user's preferred encoder is not available
- **THEN** the system SHALL fall back to the default selection order and log a warning

