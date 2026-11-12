"""WSL test: prime_sieve_v7_4.py produces exactly what prime_sieve_v6_1.py (v6.1) produces.

test_engine_v7_2_identity.py's checks on engine v7.4 (prime_sieve_engine_v7_4.so, the blocks
set up by jump_block_reuse(), which keeps the previous block's three-gap steps while the gaps
certificate holds) and its scanner:
  - engine calls against v6.1's .so: full coverage at floors 13-19 bit for bit, partial
    pieces at floors 16-30 (every v6.1 bit marked, further bits composite), block factors
    0.05 to 20; one jump piece dropped must be reported;
  - whole runs into empty portals, every output file byte for byte (PGS2 timestamp zeroed),
    with the gear on nearly every bucketed prime at the model's block factor, at 4 times it,
    at the defaults and with small segments;
  - the console's gear line names the block factor and its gain.

Run inside WSL from the repo root:
    python3 unitTests/test_engine_v7_4_identity.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import test_engine_v7_2_identity as v7_2  # noqa: E402

v7_2.CANDIDATE, v7_2.CANDIDATE_NAME = "prime_sieve_v7_4.py", "v7.4"
v7_2.CANDIDATE_SO = "prime_sieve_engine_v7_4.so"


if __name__ == "__main__":
    import engine_v7_4_lib
    from _native_skip import exit_if_skipped
    exit_if_skipped([engine_v7_4_lib.load_lib])
    raise SystemExit(v7_2.main())
