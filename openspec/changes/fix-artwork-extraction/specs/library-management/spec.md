## MODIFIED Requirements

### Requirement: Artwork Extraction
The system SHALL extract front cover artwork to a structured folder path using a configurable pattern. The extraction SHALL handle raw bytes returned by Mutagen without accessing a `.data` attribute.

#### Scenario: Artwork extracted
- **WHEN** a FLAC contains embedded front cover art
- **THEN** the system SHALL write the raw image bytes to `{art_root}/{artist}/{album}/front.jpg`

#### Scenario: No artwork present
- **WHEN** a FLAC has no embedded artwork
- **THEN** the system SHALL skip artwork extraction for that file
