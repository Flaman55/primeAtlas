# 0002. Prime data as PGS2 gap/varint windows, sharded 5000 per folder

Date: 2026-11-03 (recorded; PGS2 in force since `prime_sieve_v3.py`). Status: accepted.

## Context
Floors hold billions of primes of 20 to 76+ digits, while the gaps between consecutive primes stay small
(average about 40 at 10^18, about 170 at 10^75). Storage must be dense, rebuilt in order, and fed to
numpy matching downstream. Floor 25 reaches 500k+ window files.

## Decision
Each window is a file `PRIME_WINDOW_10p{N}_off_{OFFSET}.bin` in PGS2 format (`prime_sieve_v1.py`): magic
`PGS2`, the base prime as a length-prefixed big-endian integer (any floor depth), count (uint32),
generation time (uint32 epoch), then count-1 LEB128 unsigned varint gaps. The magic names the layout
version, so a reader never misreads an older layout. A floor's windows are sharded into `shard_NNNNN/`
folders of 5000 (`window_sharding.py`), one shared module, since the shard boundary is a contract between
every writer and reader. Constellation hit files use the same format; dense ones are split into ~1M-entry
pages with `PAGES_META.json` (`hit_paging.py`).

## Options rejected
- Full values per prime: the values are 20-76+ digits while gaps take one or two varint bytes.
- The SQL/text schema of the prime-gap record lists: built for a sparse list of record gaps with rich
  metadata, not a dense encoding of every prime in a window.
- One flat `source_primes/` folder: listing and lookup across the WSL/Windows 9P mount degrade at 100k+
  entries per folder and can kill the WSL process without a Python exception.

## Consequences
Reading a value walks the gap stream from the window start; headers give base prime, count and time
without reading the payload. Every reader assumes sharded floors (`migrate_shard_source_primes.py`
converts old ones).
