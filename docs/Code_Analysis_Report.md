# Code Analysis Report

Version: 0.2 (Stateless)
Date: 2025-09-03

## 1. Overview

This report details the current state of the `python-audio-converter` codebase against the Software Requirements Specification (SRS) and Design Document, both version 0.2.

The project has a solid foundation. The shift to a stateless, DB-less architecture is well-reflected in the core components like `dest_index` and `planner`. The GUI and CLI are both functional. The main areas requiring work are **removing legacy code**, **dramatically increasing test coverage**, and **implementing a few missing features**.

## 2. Component-wise Analysis

| Component | Module | Status | Notes |
|---|---|---|---|
| **CLI Entrypoint** | `main.py` | ✅ **Implemented** | Orchestrates the full stateless workflow correctly. Argument parsing is comprehensive. |
| **GUI** | `app/gui/main.py` | ✅ **Implemented** | Appears functional and uses a worker thread for responsiveness. Includes controls for most new stateless features. |
| **Configuration** | `src/pac/config.py` | ⚠️ **Needs Cleanup** | Correctly uses Pydantic for settings management, but contains legacy fields from the database era (`mode`, `commit_batch_size`). |
| **FFmpeg Preflight** | `src/pac/ffmpeg_check.py` | ✅ **Implemented** | Correctly probes for `ffmpeg`, `libfdk_aac`, `qaac`, and `fdkaac`. |
| **Source Scanner** | `src/pac/scanner.py` | ✅ **Implemented** | Implements recursive scanning and parallel FLAC MD5 hashing. |
| **Destination Index** | `src/pac/dest_index.py` | ✅ **Implemented** | **Core of the stateless design.** Correctly scans the destination and reads `PAC_*` tags. |
| **Stateless Planner** | `src/pac/planner.py` | ✅ **Implemented** | Correctly implements the decision logic (skip, convert, rename, retag, prune) based on source/destination state. |
| **Encoder** | `src/pac/encoder.py` | ✅ **Implemented** | Handles `ffmpeg` direct and pipe-based encoding with atomic output writes. |
| **Metadata** | `src/pac/metadata.py` | ✅ **Implemented** | Handles tag/cover art copying and, crucially, the reading/writing of `PAC_*` tags. Verification logic is also present. |
| **Path Handling** | `src/pac/paths.py` | ✅ **Implemented** | Implements path sanitization and collision resolution. |
| **Scheduler** | `src/pac/scheduler.py` | ✅ **Implemented** | Provides a bounded worker pool to manage backpressure, fulfilling NFR-7. |
| **Database** | `src/pac/db.py` | ❌ **Legacy** | **This module is obsolete.** The v0.2 design is explicitly DB-less. This file should be removed. |
| **Tests** | `tests/` | ❌ **Insufficient** | Only `test_paths.py` exists. This is a **critical gap**. Core logic in the planner, scanner, and metadata modules is untested. |

## 3. Key Issues and Actionable Recommendations

### 3.1. Critical Issues

1.  **Remove Legacy Database Code**
    *   **Issue:** `src/pac/db.py` is a remnant of a previous design and is no longer used by the stateless planner. Its presence is misleading and adds clutter. The `init-db` command in `main.py` is also obsolete.
    *   **Recommendation:**
        *   Delete the file `src/pac/db.py`.
        *   Remove the `cmd_init_db` function and its registration from `main.py`.
        *   Remove legacy settings from `src/pac/config.py` (e.g., `mode`, `commit_batch_size`).

2.  **Add Comprehensive Tests**
    *   **Issue:** The lack of tests for critical components (`planner`, `dest_index`, `metadata`, `encoder`) is a major risk. The SRS (section 8) specifies unit and integration tests that are currently missing.
    *   **Recommendation:**
        *   Create `tests/test_planner.py` with various source/destination scenarios to validate actions.
        *   Create `tests/test_metadata.py` to test tag reading/writing, especially the `PAC_*` tags.
        *   Create `tests/test_encoder.py` with mock subprocess calls to verify command construction.
        *   Create integration tests that run a small, end-to-end conversion and verify the output.

### 3.2. Bugs and Missing Features

1.  **Hardcoded VBR Quality Bug**
    *   **Issue:** In `main.py`, the `_encode_one` and `cmd_convert` functions appear to use a hardcoded `vbr_quality=5` for `libfdk_aac`, ignoring the user's configuration.
    *   **Recommendation:** Refactor these functions to correctly pass the `vbr` quality setting from the configuration, similar to how `cmd_convert_dir` does.

2.  **Missing Cover Art Resizing**
    *   **Issue:** The design document (3.6) specifies that cover art can be optionally resized. This logic is not implemented in `src/pac/metadata.py`.
    *   **Recommendation:** Add a function in `metadata.py` to check image dimensions and resize using a library like `Pillow` if it exceeds a configurable limit. This would require adding `Pillow` as a dependency.

3.  **Missing GUI Features**
    *   **Issue:** The GUI is missing the "Retry failed" and "Double-click for details" features mentioned in the design document (section 6).
    *   **Recommendation:**
        *   Implement a mechanism to track failed files from a run and add a "Retry Failed" button to the GUI.
        *   Connect the `doubleClicked` signal on the progress table to a dialog showing detailed log entries for the selected file.

4.  **Missing Path Templating**
    *   **Issue:** The application only mirrors the source directory structure. FR-11 requires configurable output path templates.
    *   **Recommendation:** Enhance `src/pac/paths.py` to support token replacement (e.g., `{artist}`, `{album}`). This would likely involve reading metadata *before* planning paths, which could alter the current workflow. This is a significant feature and should be planned carefully.

## 4. Next Steps

1.  **Cleanup:** Perform the legacy code removal as described in 3.1.1.
2.  **Testing:** Prioritize writing unit tests for the `planner` and `metadata` modules (3.1.2).
3.  **Bug Fixes:** Address the hardcoded VBR quality bug (3.2.1).
4.  **Feature Work:** Begin implementing the smaller missing features like GUI enhancements (3.2.3) and cover art resizing (3.2.2).
