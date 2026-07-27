# Git on Windows

1. Inspect the repository status and running Git processes before changing Git metadata.
2. For `.git/index.lock`, confirm no live Git process owns the operation. Do not delete the lock
   merely because it exists.
3. For dubious ownership, add only the exact trusted repository when authorized; never configure a
   wildcard safe directory.
4. Keep CRLF/LF normalization separate from functional changes. Review staged diffs for mass
   line-ending churn.
5. Perform case-only renames through an explicit intermediate name when the filesystem requires it.
6. Treat antivirus, editor, and shell file locks as external state; identify the owning process
   before retrying or removing files.
7. Do not run destructive recovery such as hard reset or broad checkout without explicit request.
8. Stage only named in-scope paths and inspect the staged diff before commit.

Git mutation still follows repository approval policy even when a permission or lock workaround is
known.
