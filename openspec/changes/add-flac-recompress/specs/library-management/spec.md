## MODIFIED Requirements

### Requirement: Compression Policy Enforcement
The system SHALL recompress FLAC files to a target compression level using `flac -V -{level}` and write a COMPRESSION tag in the format `flac {version}; level={level}; verify=1; date={date}`. Files with matching COMPRESSION tags SHALL be skipped.

#### Scenario: File recompressed
- **WHEN** a FLAC lacks a COMPRESSION tag or has a different level
- **THEN** the system SHALL recompress with `flac -V -{level}` and set the COMPRESSION tag

#### Scenario: Recompression skipped
- **WHEN** a FLAC has COMPRESSION tag matching target level
- **THEN** the system SHALL skip recompression

#### Scenario: Recompression failure
- **WHEN** `flac -V` returns non-zero exit code
- **THEN** the system SHALL mark the file as held and skip remaining phases

### Requirement: CD Quality Resampling
The system SHALL resample FLAC files exceeding CD quality (16-bit/44.1kHz/2ch) down to CD quality using an FFmpeg or sox pipeline to `flac -V -{level}`.

#### Scenario: Hi-res file resampled
- **WHEN** a 24-bit/96kHz FLAC is processed with `--resample-to-cd`
- **THEN** the system SHALL produce a 16-bit/44.1kHz stereo FLAC with verification

#### Scenario: CD quality file unchanged
- **WHEN** a 16-bit/44.1kHz stereo FLAC is processed
- **THEN** the system SHALL NOT resample the file
