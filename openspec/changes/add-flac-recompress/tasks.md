## 1. Validation
- [ ] 1.1 Test `recompress_flac()` with various compression levels
- [ ] 1.2 Verify COMPRESSION tag is written correctly after recompress
- [ ] 1.3 Test `resample_to_cd_flac()` with hi-res input (24-bit/96kHz)
- [ ] 1.4 Verify output is 16-bit/44.1kHz/stereo after resample

## 2. Integration
- [ ] 2.1 Verify library_runner calls recompress phase correctly
- [ ] 2.2 Verify library_runner calls resample phase correctly
- [ ] 2.3 Test early-stop behavior when recompress/resample fails

## 3. Tests
- [ ] 3.1 Add unit test for `recompress_flac()` with mock FLAC
- [ ] 3.2 Add unit test for `resample_to_cd_flac()` with mock hi-res FLAC
- [ ] 3.3 Add integration test for full library maintenance cycle
