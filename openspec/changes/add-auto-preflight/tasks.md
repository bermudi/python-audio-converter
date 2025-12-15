## 1. Implementation

- [ ] 1.1 Create `AutoPreflightWorker` that runs on `MainWindow.__init__` completion
- [ ] 1.2 Add status indicator widget showing preflight progress ("Checking encoders...")
- [ ] 1.3 Connect preflight completion signal to enable Convert tab controls
- [ ] 1.4 Cache preflight results in `self.preflight_results` (already exists, ensure populated on startup)
- [ ] 1.5 Replace "Preflight" button with "Re-check Encoders" in menu bar or settings

## 2. UI Updates

- [ ] 2.1 Add persistent encoder status display (status bar or info label)
- [ ] 2.2 Show clear error state if no encoder available on startup
- [ ] 2.3 Update Convert tab to show "Checking encoders..." placeholder while preflight runs

## 3. Testing

- [ ] 3.1 Manual test: GUI starts and auto-enables Convert controls when ffmpeg available
- [ ] 3.2 Manual test: GUI shows error state gracefully when no encoder found
- [ ] 3.3 Manual test: Re-check option works after initial preflight
