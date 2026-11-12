# 0009. Atlas runs on its own engines; guest tools are optional

Date: 2026-11-12. Status: accepted.

## Context
Atlas ships programs it does not own next to its own engines. The Pseudosquares Prime Sieve runs
as a Quick-gen mode under its author's license, and on high floors it is faster than Atlas's own
deterministic engines. Atlas now proposes an engine for each run (`engine_advisor.py`), so it has
to decide what part such a program plays in that proposal. A guest program can leave Atlas: its
author may withdraw it, its license may change, or it may stop building. That must not break or
change anything Atlas does on its own.

## Decision
- The proposal is chosen only from Atlas's own engines (`engine_options.ENGINES`). The default
  deterministic choice on high floors is Atlas's own pt1-pss or v7.
- A guest tool (`engine_advisor.GUEST_ENGINES`) is never the proposal or an option. It shows as a
  separate line next to the proposal when it is faster, with the speed-up measured on this machine
  (two logged runs, no seed values) and with what it does and does not do: it writes no windows
  into the storage, but its deterministic prime count, kept in the Benchmark tab, proves a pt1 run's
  P windows over the same range when the counts are equal.
- Removing a guest leaves every proposal unchanged. `unitTests/test_engine_advisor.py` checks
  this: the same proposal with and without guests, and with a log that has no guest rows.

## Options rejected
- Propose the fastest deterministic program, the guest included. The proposal would then depend on
  a program Atlas cannot keep. Removing the guest would silently change the defaults, and the
  proposed run would write nothing into the storage.
- Hide the guest. Atlas would not tell the user about a faster deterministic tool it ships.

## Consequences
Where the guest is faster, the proposal is slower than the best available program; the guest line
says by how much. A new guest tool joins `GUEST_ENGINES` with its floor range and never reaches the
choice.
