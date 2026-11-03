# 0006. The version is read from CHANGELOG.md: release plus one numbered entry per merge

Date: 2026-11-03. Status: accepted.

## Context
Every copy of the app is a git checkout that Settings → Updates moves along `main` between releases, so
a hard-coded release number (`APP_VERSION`) did not say which changes a copy has. The agreed scheme is
"release + N merges since it", with the changes listed in the About tab. An installed copy has no git
on PATH, and counting commits from `.git` without git means reading packfiles.

## Decision
- `CHANGELOG.md` is the single source. The release is its newest `## X.Y.Z — date` heading; every merge
  into `main` after it appends one entry `### +N — title` (English, then Polish) to `## Since X.Y.Z`.
  The app shows `X.Y.Z+N (sha7)` (`primeatlas/core/version.py`).
- `unitTests/test_about_tab.py` keeps N equal to the first-parent merges since the tag `vX.Y.Z` (plus
  the branch's own entry before its merge) and the release equal to the newest release tag.
- The installer (`/DAppVersion`) and the release workflow's tag check read the same heading.
- Entries are append-only; a correction is a new entry. A release renames `## Since X.Y.Z` to
  `## A.B.C — date` and pushes the tag `vA.B.C`.

## Options rejected
- Counting merges with git at runtime: git is not on PATH in an installed copy; the bundled git would
  have to be located and run at every start.
- Keeping `APP_VERSION` next to the changelog: two sources of one number.

## Consequences
A PR without its changelog entry fails `test_about_tab` once the branch has a commit. Two branches open
at once both claim the next number; the second to merge renumbers its entry before merging.
