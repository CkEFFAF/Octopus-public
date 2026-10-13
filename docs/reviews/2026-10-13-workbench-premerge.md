# Review, feature/workbench-modes, 2026-10-13

**Reviewed by**: GPT-6 independent review agent (author model not supplied)
**Scope**: 28 changed application, test and spec files; uncommitted changes against `302585ff4ad0e231aa219b20af2b01d7e821d341`, including untracked Git UI files
**Verdict**: Approve (focused re-review of all three original findings)

## Summary

The change introduces local skill discovery with explicit import approval, a Git dock and workflow presets. All three original findings below have been resolved. No blocker or major remains within this focused re-review; the original findings are retained as an audit trail.

## Resolution and verification

- **Literal restore — resolved.** Every Git invocation now includes global `--literal-pathspecs`. Re-ran the original real-Git reproduction independently: only `[ab].txt` returned to its original contents, its backup retained the modified bytes, and `a.txt`/`b.txt` remained modified. The added regression asserts these same externally observable outcomes.
- **Snapshot encoding — resolved.** Each UTF-8 filename and content is preceded by its 8-byte length. Re-ran the original two-package collision reproduction against the actual loader: the two digests now differ. The added regression covers that boundary ambiguity.
- **Quoted filenames — resolved.** Backend `core.quotepath=false` preserves Unicode. Frontend decoding removes quoted path syntax consistently, recognizes quoted destination headers, and only interprets rename arrows outside quoted strings. Inspection of the focused changes and regressions confirms ordinary Unicode, spaces and quoted rename cases. The parent reports targeted frontend regressions passed. This reviewer's Vitest attempt could not start esbuild because of sandbox `EPERM`; its escalation was aborted and is not counted as a successful run.

The parent additionally reports the pinned-environment gate passed: 4,517 tests passed, 188 skipped, with Ruff and mypy green. That full-suite result is parent-provided evidence; this reviewer independently reran only the two focused backend reproductions.

## Original blocker (resolved)

### 🔴 Restore treats a filename as a wildcard pathspec, `src/octop/infra/backend/git_workbench.py:115`

**Problem**: Passing `file_path` after `--` stops option parsing but does not disable Git pathspec matching. A valid tracked filename such as `[ab].txt` also matches `a.txt` and `b.txt`. Only the selected file has its hash checked and bytes backed up.

**Why it matters**: A confirmation to restore one file silently discards unrelated changes without recovery copies. Reproduced using the actual helper and Git on Windows: commit `[ab].txt`, `a.txt`, and `b.txt` with `old\n`; change each to `new\n`; call `restore_file` for `[ab].txt` with its correct SHA-256. All three return to `old\n`, while the recovery directory contains only the copy of `[ab].txt`.

**Suggested fix**: Use Git's global `--literal-pathspecs` option or explicitly construct a literal pathspec. Add a regression exercising real filenames with brackets and verifying all other changed files remain untouched.

## Original major findings (resolved)

### 🟠 Snapshot digest has ambiguous file boundaries, `src/octop/infra/skills/external_sources.py:82`

**Problem**: The digest concatenates `filename + NUL + arbitrary file bytes + NUL`. Since content can contain NUL, different file sets can produce exactly the same hashed byte stream without breaking SHA-256.

**Why it matters**: Import can accept changed contents and a changed file list using the previously approved digest, violating the exact-snapshot approval contract. Reproduced against the actual loader, package validator and frontmatter helper (loaded directly to avoid unrelated package-initialization dependencies). Package A contains `SKILL.md` with `b'---\nname: Review\n---\nBody\n'` and `a.txt` with `b'abc'`. Package B deletes `a.txt` and appends `b'\0a.txt\0abc'` to `SKILL.md`. Both loads succeed and return digest `4f6886e6ee9f441940a72be5e061960d73bc2c52515ceee2d0bbff7d3e59ab11`. The import endpoint's equality check therefore cannot distinguish these packages.

**Suggested fix**: Encode lengths before each filename/content field, or hash a canonical list of filenames and fixed-length per-file content hashes. Add a regression for the two distinct packages above.

### 🟠 Quoted Git filenames lose their diff and restore action, `dashboard/src/pages/Chat/components/ChatDockGit.tsx:52`

**Problem**: `splitDiff` only recognizes an unquoted ` b/` header, while status parsing at lines 66–67 retains Git's quotes and escaped bytes. Git quotes non-ASCII filenames by default and quotes spaces in short status. These representations do not match each other or the raw paths in `restorable`.

**Why it matters**: Chinese filenames show no diff and cannot be restored through the panel. Names with spaces create separate quoted status and unquoted diff entries, so the initially selected entry has no diff. Confirmed from actual `git_snapshot` output for modified `说明.md` and `space file.txt`: the Chinese diff header is `diff --git "a/\350\257\264\346\230\216.md" "b/\350\257\264\346\230\216.md"`; its header does not match the regex, while `restorable` contains the actual Unicode path. Short status reports ` M "space file.txt"`, but its diff key is `space file.txt`.

**Suggested fix**: Supply structured file records from machine-readable, NUL-delimited Git output and associate each patch with its exact path, or implement complete Git quoted-path decoding consistently for both outputs. Cover Unicode, spaces, quotes, renames and literal ` -> ` filenames with fixtures generated by real Git.

## Strengths

- Discovery/import require an administrator and validate agent access; imports reuse the existing skill installation path.
- Restore rejects staged changes, checks the selected content hash and creates a recovery copy before mutation.
- Presets preserve the existing Plan/Ask policy and explicitly qualify workflows that require expert capabilities.

## Test coverage

Existing tests cover ordinary restore, stale hashes, staged-change rejection, parent traversal, separate staged/unstaged output, confirmation and basic diff rendering. New regressions cover literal bracket filenames, ambiguous snapshot boundaries, Unicode and space-containing paths, and quoted rename arrows. The new filename UI fixture includes the actual branch header. Focused independent reproductions and the parent-provided test results are distinguished in the verification section above.
