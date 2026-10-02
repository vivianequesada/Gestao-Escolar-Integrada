---
name: School data preservation
description: Storage and data-retention constraints for the school management app.
---

Keep the existing SQLite database as the source of truth; do not replace it with JSON or another store. Schema changes must preserve existing users, students, and educational records. When a student or staff member should no longer appear as active, archive the record instead of hard-deleting it when history refers to it.

**Why:** The user asked to integrate new behavior into the current school app while keeping SQLite and its saved records.

**How to apply:** Inspect the current schema before migrations, test migrations against a disposable database copy, and verify retained rows and foreign keys. Prefer reversible active/inactive flags for records linked to attendance, reports, plans, or minutes.