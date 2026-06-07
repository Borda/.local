## Task lifecycle sequencing

### TaskUpdate before long output

Call `TaskUpdate(status="completed")` **before** any long output block (audit report, calibration summary, release notes, multi-item list). Tool calls placed after a long output block may never execute if context compaction fires mid-response, leaving tasks permanently "in_progress".

Correct sequence: `TaskUpdate(completed)` → emit output. Wrong: emit output → `TaskUpdate(completed)`.
