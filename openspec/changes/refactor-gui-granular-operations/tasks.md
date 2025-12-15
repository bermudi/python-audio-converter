## 1. Backend Refactoring
- [x] 1.1 Refactor `library_runner.py` to expose individual phase functions callable independently
- [x] 1.2 Create `AdoptWorker` for adopting legacy files (retag without re-encode)
- [x] 1.3 Add phase-selection parameter to `cmd_manage_library` to run specific phases only

## 2. GUI Restructure
- [x] 2.1 Replace single "Run Library Maintenance" button with operation selector
- [x] 2.2 Add checkboxes for each operation: Integrity, Resample, Recompress, Artwork, Adopt
- [x] 2.3 Add "Run Selected" button that executes only checked operations
- [x] 2.4 Add individual "Run" buttons next to each operation for quick single-operation runs
- [x] 2.5 Keep "Dry Run" toggle that applies to all operations

## 3. Adopt Legacy Files Feature
- [x] 3.1 Add "Adopt Legacy Files" operation that scans for outputs without PAC_* tags
- [x] 3.2 Show count of adoptable files before running
- [x] 3.3 Retag adoptable files with PAC_* metadata without re-encoding

## 4. Progress and Feedback
- [x] 4.1 Show per-operation progress when multiple operations selected
- [x] 4.2 Display operation-specific summaries (e.g., "Integrity: 100 OK, 2 failed")
- [x] 4.3 Keep existing held files list for issues

## 5. Testing
- [x] 5.1 Test individual operation execution
- [x] 5.2 Test combined operation execution
- [x] 5.3 Test adopt legacy files workflow
