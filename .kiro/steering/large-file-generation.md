---
inclusion: auto
---

# Large File Generation Strategy

When generating large spec documents (design.md, requirements.md, tasks.md) that exceed ~50 lines:

1. **Use a Python script** to generate the file content programmatically
2. Write the script in chunks using `fsWrite` (initial) + `fsAppend` (subsequent sections)
3. Store content in a list of sections, then join and write to the target file
4. Run the script with `executePwsh` to produce the output file
5. Verify the output with a quick line count check

This avoids hitting file write size limits and ensures the complete document is generated in one pass.

Script location: `scripts/generate_design.py` (or similar) — can be deleted after use.
