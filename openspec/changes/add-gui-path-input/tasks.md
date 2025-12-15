## 1. CLI Arguments
- [ ] 1.1 Add argparse setup in `app/gui/main.py` with `--flac-library`, `--mirror-library`, `--source`, `--output` arguments
- [ ] 1.2 Pass parsed arguments to `MainWindow.__init__` and populate corresponding QLineEdit fields on startup

## 2. Drag-and-Drop Support
- [ ] 2.1 Create `DropLineEdit` widget subclass that accepts directory drops
- [ ] 2.2 Handle `dragEnterEvent` to accept `text/uri-list` MIME type (standard for file drops)
- [ ] 2.3 Handle `dropEvent` to extract directory path and set text
- [ ] 2.4 Replace path QLineEdit instances with `DropLineEdit` in Convert and Library tabs

## 3. Testing
- [ ] 3.1 Manual test: Launch GUI with CLI args and verify paths populate
- [ ] 3.2 Manual test: Drag folder from Dolphin (KDE) on Wayland to path fields
- [ ] 3.3 Manual test: Drag folder on X11 to verify cross-platform compatibility
