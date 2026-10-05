"""
tree_colors.py -- one color per prime for the prime tree, plus the user's override
map. A default color is picked by the prime's level in the drawn tree (so primes
past uint64 need no prime counting); an override is keyed by the prime itself.

The default palette is Okabe-Ito followed by Paul Tol's muted scheme (colorblind-safe);
past the end of the palette the hues cycle with a golden-angle step.
"""

import colorsys

_DEFAULT_PALETTE_HEX = (
    "E69F00", "56B4E9", "009E73", "F0E442", "0072B2", "D55E00", "CC79A7",
    "88CCEE", "44AA99", "117733", "999933", "DDCC77", "CC6677", "882255", "AA4499",
)

NEUTRAL_NODE_RGB = (0.92, 0.92, 0.92)
TERMINAL_LANE_RGB = (0.70, 0.74, 0.82)
EDGE_RGB = (0.55, 0.55, 0.60)
AXIS_RGB = (0.75, 0.75, 0.75)
OVERFLOW_STRIPE_RGB = (1.0, 1.0, 1.0)
HIGHLIGHT_PRIME_RGB = (1.0, 0.84, 0.0)


def _hex_to_rgb(text):
    text = text.strip().lstrip("#")
    if len(text) != 6:
        raise ValueError(f"color {text!r} is not #rrggbb")
    try:
        return tuple(int(text[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
    except ValueError:
        raise ValueError(f"color {text!r} is not #rrggbb") from None


_DEFAULT_PALETTE = tuple(_hex_to_rgb(h) for h in _DEFAULT_PALETTE_HEX)


def _is_prime(n):
    if n < 2:
        return False
    d = 2
    while d * d <= n:
        if n % d == 0:
            return False
        d += 1
    return True


def _prime_index(p):
    index = 0
    candidate = 2
    while candidate < p:
        if _is_prime(candidate):
            index += 1
        candidate += 1
    return index


def prime_color(p, overrides=None, index=None):
    """RGB (0..1 floats) of prime p: the override if one is given, else the default
    palette entry for `index` (p's level in the drawn tree; None = p's index among
    all primes, counted by trial division, so only for small p)."""
    if overrides and p in overrides:
        return tuple(overrides[p])
    if index is None:
        index = _prime_index(p)
    if index < len(_DEFAULT_PALETTE):
        return _DEFAULT_PALETTE[index]
    hue = (index * 0.381966) % 1.0
    return colorsys.hsv_to_rgb(hue, 0.55, 0.9)


def parse_color_map(text):
    """Parses "p=#rrggbb, q=#rrggbb" into {p: (r, g, b)}; an empty string is no
    override. Raises ValueError on a malformed entry or a key that is not prime."""
    overrides = {}
    for entry in (part.strip() for part in text.split(",")):
        if not entry:
            continue
        if "=" not in entry:
            raise ValueError(f"color entry {entry!r} is not p=#rrggbb")
        key, value = (side.strip() for side in entry.split("=", 1))
        try:
            p = int(key)
        except ValueError:
            raise ValueError(f"color entry {entry!r}: {key!r} is not an integer") from None
        if not _is_prime(p):
            raise ValueError(f"color entry {entry!r}: {p} is not prime")
        overrides[p] = _hex_to_rgb(value)
    return overrides
