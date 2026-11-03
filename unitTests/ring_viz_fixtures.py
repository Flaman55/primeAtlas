"""
ring_viz_fixtures.py -- fixtures shared by the ring visualization tests
(test_ring_viz_sources.py, test_ring_viz_pattern_seek.py,
test_ring_viz_pattern_seek_async.py, test_ring_viz_pattern_mode.py): a synthetic
portal floor of real PGS2 window files, and a small reference prime sieve.
Imported by those scripts after they put the repo root and prime_sieve/ on sys.path.
"""
import os


def write_floor(portal_dir, base_exponent, windows):
    """windows: list of lists of ints, one shard-0 PRIME_WINDOW_*.bin per
    entry, named so list_source_filenames()'s offset-based sort places them
    in the given order (offsets 0, 1_000_000, 2_000_000, ... -- comfortably
    apart, real widths don't matter for these tests since load_archive reads
    whatever's actually in each file, not the offset in the filename). The
    values need not be real primes (arbitrary ascending ints)."""
    import window_sharding
    import prime_sieve_v1

    source_dir = os.path.join(portal_dir, f"10p{base_exponent}", "source_primes")
    shard0 = window_sharding.shard_dir(source_dir, 0)
    os.makedirs(shard0, exist_ok=True)
    for i, values in enumerate(windows):
        name = f"PRIME_WINDOW_off_{i}M.bin" if i > 0 else "PRIME_WINDOW_off_0.bin"
        prime_sieve_v1.write_prime_window(os.path.join(shard0, name), values)


def sieve_primes_upto(n):
    """Every prime <= n (sieve of Eratosthenes), the reference the pattern tests
    compare matches against."""
    is_composite = bytearray(n + 1)
    primes = []
    for p in range(2, n + 1):
        if not is_composite[p]:
            primes.append(p)
            if p * p <= n:
                is_composite[p * p:n + 1:p] = b"\x01" * len(range(p * p, n + 1, p))
    return primes
