## 1. Backend Refactoring
- [ ] 1.1 Refactor `library_runner.py` to expose individual phase functions callable independently
- [ ] 1.2 Create `AdoptWorker` for adopting legacy files (retag without re-encode)
- [ ] 1.3 Add phase-selection parameter to `cmd_manage_library` to run specific phases only

## 2. GUI Restructure
- [ ] 2.1 Replace single "Run Library Maintenance" button with operation selector
- [ ] 2.2 Add checkboxes for each operation: Integrity, Resample, Recompress, Artwork, Adopt
- [ ] 2.3 Add "Run Selected" button that executes only checked operations
- [ ] 2.4 Add individual "Run" buttons next to each operation for quick single-operation runs
- [ ] 2.5 Keep "Dry Run" toggle that applies to all operations

## 3. Adopt Legacy Files Feature
- [ ] 3.1 Add "Adopt Legacy Files" operation that scans for outputs without PAC_* tags
- [ ] 3.2 Show count of adoptable files before running
- [ ] 3.3 Retag adoptable files with PAC_* metadata without re-encoding

## 4. Progress and Feedback
- [ ] 4.1 Show per-operation progress when multiple operations selected
- [ ] 4.2 Display operation-specific summaries (e.g., "Integrity: 100 OK, 2 failed")
- [ ] 4.3 Keep existing held files list for issues

## 5. Testing
- [ ] 5.1 Test individual operation execution
- [ ] 5.2 Test combined operation execution
- [ ] 5.3 Test adopt legacy files workflow
