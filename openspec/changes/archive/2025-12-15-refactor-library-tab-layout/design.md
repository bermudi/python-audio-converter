## Context
The Library tab currently uses a single vertical column of group boxes. This makes the Library Browser hard to use because non-browser sections (Operations + Settings) are always visible and consume most of the available height.

## Goals / Non-Goals
- Goals:
  - Make the Library Browser the primary canvas (largest area by default).
  - Keep operations discoverable and fast to use for power users.
  - Preserve existing capabilities: granular operations, dry-run, scan, selection-based actions.
  - Support running operations on both entire library and selected files.
- Non-Goals:
  - Changing the underlying library operation semantics.
  - Adding new library operations.
  - Introducing persistence beyond existing settings/config mechanisms.

## Decisions
- Decision: Use a horizontal splitter for the Library tab’s main body.
  - Rationale: Qt splitters are familiar, efficient, and let users tune space allocation.
  - Layout:
    - Left: compact operations panel (collapsible via toggle, or user can drag splitter).
    - Right: browser panel (filters + table) taking most space.

- Decision: Implement Library Settings as a modal dialog.
  - Rationale: Settings are configured infrequently, but occupy large space. A modal keeps the main workspace focused.
  - Structure: a `QDialog` with tabs/sections:
    - General (compression target, mirror codec)
    - Artwork (root, pattern)
    - Workers (FLAC/analysis/art)

- Decision: Provide explicit operation scope control.
  - Rationale: Users need both “entire library” workflows and “operate on selected rows” workflows.
  - Behavior:
    - When a selection exists, default scope is “Selection”.
    - Users can override to “Entire Library”.

- Decision: Collapse status/counters into a Details area.
  - Rationale: These are primarily useful during runs and troubleshooting; they should not permanently reduce browser height.
  - Behavior:
    - Collapsed by default.
    - Auto-expands when an operation starts.

## Alternatives Considered
- Keep settings inline but collapsible.
  - Rejected: still competes for vertical space and encourages leaving it open.
- Move operations to a top toolbar only.
  - Rejected: operations need labels, dry-run toggle, and scope controls; a minimal toolbar becomes cramped.

## Risks / Trade-offs
- More UI state (collapsed/expanded, scope selection) increases complexity.
  - Mitigation: default behaviors should require no configuration; keep controls minimal.

## Open Questions
- None (operation scope: entire library + selection; settings: modal).
