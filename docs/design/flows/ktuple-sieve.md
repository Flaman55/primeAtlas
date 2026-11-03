# Flow: targeted k-tuple sieve (pattern and locations to confirmed hits)

Entry points: Generation tab, Section C "Run" / "Auto" (`primeatlas/generation/ktuple_section.py`); by
hand: `python3 constellation/ktuple_sieve_v2_2.py <floor> <k> <variant> --strategy ...` under WSL.

```
 ktuple_section ─> engine_argv.build_ktuple_sieve_argv ─> WslLoggedRunner
   └─> ktuple_sieve_v2_2.py: portal = default_portal_folder()
         run_ktuple_job(portal, ...) or scan_locations(portal, ...) for manual_list
           locations (ktuple_locations_v2_2) ─> wheel + trial division + Miller-Rabin (ktuple_wheel_v2_2)
           ─> _record_confirmed_hits: below the exhaustive frontier ─> shared hit file
                                      at or beyond it            ─> PROVISIONAL_HITS_*
           ─> KTUPLE_CHECKPOINT_* after each batch
```

## Steps

| Step (module) | Runs when | Reads | Writes / does |
|---|---|---|---|
| Locations (`ktuple_locations_v2_2.py`) | each batch | strategy (even, concentrated, manual_list, manual_step, digit_sweep), checkpoint | window bases to scan |
| Candidates (`ktuple_wheel_v2_2.py`) | each location | pattern offsets | CRT residue wheel, trial division to `deep_prime_limit`, Miller-Rabin `mr_rounds` |
| Frontier (`ktuple_hit_store_v2_2._exhaustive_frontier_value`) | each recorded batch | the floor's window list and the finder's done ranges (`constellation_progress_v2_3`) | smallest value the exhaustive search has not covered |
| Record (`_record_confirmed_hits`) | confirmed hits | frontier | below it: `_append_hits_deduped` into the shared hit file; at or beyond: the provisional log ([ADR 0005](../../adr/0005-gap-safe-provisional-hits.md)) |
| Checkpoint (`ktuple_hit_store_v2_2.py`) | checkpointed strategies | | `KTUPLE_CHECKPOINT_10p{N}_k{K}_v{V}.txt` (next offset) |

## What leaves and what is kept

- What the caller gets: per-location candidate and confirmed counts, a final summary.
- What is stored ([data.md](../data.md)): hits in the shared hit file or the provisional log, the
  k-tuple checkpoint.

## Known gaps

- None known.
