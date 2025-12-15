## 1. Configuration

- [ ] 1.1 Add `probe_wine_encoders: bool = False` setting to `PacSettings`
- [ ] 1.2 Add `aac_encoder_preference: Optional[str]` setting for user's preferred AAC encoder

## 2. Preflight Logic

- [ ] 2.1 Update `PreflightWorker` to accept `skip_wine` parameter
- [ ] 2.2 Skip `probe_qaac()` when `skip_wine=True` (based on setting)
- [ ] 2.3 Add separate `probe_wine_encoders()` function for on-demand Wine probing

## 3. GUI Updates

- [ ] 3.1 Add "Check Wine Encoders" button (hidden by default, shown when `probe_wine_encoders=False`)
- [ ] 3.2 Add AAC encoder dropdown when multiple AAC encoders are detected
- [ ] 3.3 Persist encoder preference to settings when user selects one
- [ ] 3.4 Update encoder status display to show Wine encoder availability separately

## 4. Testing

- [ ] 4.1 Manual test: Startup skips qaac probe when setting is False
- [ ] 4.2 Manual test: "Check Wine Encoders" button triggers qaac detection
- [ ] 4.3 Manual test: Encoder preference persists across restarts
