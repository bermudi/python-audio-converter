# Change: Add GUI Path Input via CLI Arguments and Drag-Drop

## Why
Users cannot launch the GUI with pre-configured library paths or quickly populate path fields by dragging folders from their file manager. This forces manual browsing every time, slowing down workflows for users who frequently switch between libraries or want to integrate PAC with file manager actions.

## What Changes
- Add CLI arguments `--flac-library` and `--mirror-library` to pre-populate Library tab paths on startup
- Add CLI arguments `--source` and `--output` to pre-populate Convert tab paths on startup
- Enable drag-and-drop on path input fields (QLineEdit) to accept folder paths
- Use Qt6's native drag-drop which works on both X11 and Wayland (including KDE Plasma)

## Impact
- Affected specs: `library-management`
- Affected code: `app/gui/main.py`
