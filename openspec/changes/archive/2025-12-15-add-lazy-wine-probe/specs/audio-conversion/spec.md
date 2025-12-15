## ADDED Requirements

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
