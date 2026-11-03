# 0004. Shared values in one const or dynamic module; the engines pass the storage folder explicitly

Date: 2026-11-03. Status: accepted.

## Context
Splitting large files into modules (PRs #16-#27) left values used by several modules. Copies drift;
values scattered across modules have to be hunted for. The constellation engines also read the storage
folder from a mutable module global (`PORTAL_FOLDER`) and depended on import order for `sys.path`.

## Decision
- A fixed value used by several modules lives in one `*_const` module; a value computed once at startup
  and used by several modules lives in one `*_dynamic` module. Both are read as module attributes
  (`_const.X`, `_dyn.X`). Values local to a function or passed between functions stay parameters and
  return values. Examples: `primeatlas/app/app_const.py`, `app_dynamic.py`, `constellation_const_v2_3.py`.
- The constellation engines (`constellation_*_v2_3`, `ktuple_*_v2_2`) take the storage folder as an
  explicit `portal` argument; the CLI resolves it once (`constellation_portal_v2_3.default_portal_folder`).
  Only entry scripts change `sys.path`.

## Options rejected
- Module globals patched by tests: hidden dependency, order-sensitive.
- A config object passed everywhere: more ceremony than one path needs.

## Consequences
Tests check that no other module assigns module-level values (`test_prime_atlas_app_layout`,
`test_constellation_finder_v2_3`). The GUI still holds the storage path as one rebindable value
(`app_dynamic.PORTAL_FOLDER`, rebound only by `_set_portal_folder`), since a Settings change must reach
every tab at once.
