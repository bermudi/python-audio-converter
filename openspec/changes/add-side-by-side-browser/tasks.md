## 1. Data Model
- [x] 1.1 Create `SideBySideModel` that holds paired source↔output file data
- [x] 1.2 Add bidirectional lookup map (source path → output path, output path → source path)

## 2. UI Layout
- [x] 2.1 Add "Side-by-Side" option to view mode combo box
- [x] 2.2 Create `QSplitter` with two `QTableView` panels (source left, mirror right)
- [x] 2.3 Add panel headers showing "Source Library" and "Mirror Library" labels
- [x] 2.4 Hide/show split view based on selected view mode

## 3. Selection and Scroll Synchronization
- [x] 3.1 Connect selection changed signals between both tables
- [x] 3.2 Implement cross-panel highlight on row selection
- [x] 3.3 Auto-scroll counterpart panel to show matched file
- [x] 3.4 Handle missing counterpart gracefully (no match to highlight)
- [x] 3.5 Implement linked scrolling (scroll one panel → other follows) enabled by default

## 4. Visual Indicators
- [x] 4.1 Add sync status column to both panels (Synced/Missing/Orphan)
- [x] 4.2 Color-code rows: green=synced, red=missing, yellow=orphan
- [x] 4.3 Show "—" placeholder in mirror panel for missing outputs

## 5. Filtering
- [x] 5.1 Add filter options specific to side-by-side view (All, Synced, Missing, Orphaned)
- [x] 5.2 Apply filter to both panels simultaneously

## 6. Testing
- [ ] 6.1 Manual test: verify selection sync works bidirectionally
- [ ] 6.2 Manual test: verify filters apply to both panels
- [ ] 6.3 Manual test: verify splitter resize persists during session
