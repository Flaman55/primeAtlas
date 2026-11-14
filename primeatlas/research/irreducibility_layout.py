"""
irreducibility_layout.py -- block layouts for Research -> Irreducibility, on the value side:
the input of a number into block representation, the ranges W of a layout, fitting a layout
to a number and the parameter sweep. These form lcm values and the number itself, so they
stay outside irreducibility_residues.py.

A layout has blocks D (consecutive moduli from a start, `count` blocks of `size` moduli) and
quotient blocks K built the same way. W(D) is the lcm of the moduli of D, W(K) that of K and
W the lcm of all of them: every number below W has exactly one block representation.
"""
import math

LIMIT_BLOCK = 10 ** 6
"""A block modulus above this is flagged: the residue arithmetic runs on plain integers and
slows down; arbitrary."""

MAX_FIT_BLOCKS = 80
"""fit_for adds at most this many blocks D; arbitrary."""

MAX_FIT_QUOT_BLOCKS = 300
"""fit_for adds at most this many quotient blocks K; arbitrary."""

PARAMS = ("ds", "dz", "dc", "ks", "kz", "kc")
"""Layout parameters: start, block size and block count of D, then of K."""

SWEEP_STEPS = (-3, -2, -1, 0, 1, 2, 3)


def blocks(start, size, count):
    """count blocks of size consecutive moduli from start."""
    return [[start + i * size + j for j in range(size)] for i in range(count)]


def lcm_all(xs):
    return math.lcm(*xs) if xs else 1


def _flat(bs):
    return [m for b in bs for m in b]


def layout_of(params):
    """(D, K) of a parameter dict with the keys of PARAMS."""
    return (blocks(params["ds"], params["dz"], params["dc"]),
            blocks(params["ks"], params["kz"], params["kc"]))


def block_rep_of(n, D, K):
    """The block representation of n: member residues of n on D, and of n // W(D) on K."""
    w_d = lcm_all(_flat(D))
    k, r = divmod(n, w_d)
    return {"blocks": D, "residues": [[r % m for m in b] for b in D],
            "quot_blocks": K, "quot_residues": [[k % m for m in b] for b in K]}


def capacity(D, K):
    """W: the lcm of all moduli of D and K (never above W(D) * W(K))."""
    return lcm_all(_flat(D) + _flat(K))


def ranges(D, K):
    """W(D), W(K), W, the nominal W(D) * W(K) and the largest block modulus."""
    w_d, w_k = lcm_all(_flat(D)), lcm_all(_flat(K))
    return {"w_blocks": w_d, "w_quot": w_k, "w": capacity(D, K), "nominal": w_d * w_k,
            "max_block": max((lcm_all(b) for b in D + K), default=0)}


def fit_for(n, zD, zK, startD=2):
    """A layout for n: blocks D of size zD from startD until W(D) > isqrt(n), then quotient
    blocks K of size zK right after D until W > n."""
    root = math.isqrt(n)
    dc = 1
    while dc < MAX_FIT_BLOCKS and lcm_all(_flat(blocks(startD, zD, dc))) <= root:
        dc += 1
    D = blocks(startD, zD, dc)
    ks = startD + zD * dc
    kc = 1
    while kc < MAX_FIT_QUOT_BLOCKS and capacity(D, blocks(ks, zK, kc)) <= n:
        kc += 1
    return {"ds": startD, "dz": zD, "dc": dc, "ks": ks, "kz": zK, "kc": kc,
            "D": D, "K": blocks(ks, zK, kc)}


def digit_count(w):
    """Digits of the largest number below w."""
    return len(str(max(w - 1, 0)))


def fmt_big(n):
    """n with thin-space groups up to 15 digits, else as m,mmm·10^e."""
    t = str(n)
    if len(t) <= 15:
        return f"{n:,}".replace(",", " ")
    return f"{t[0]},{t[1:4]}·10^{len(t) - 1}"


def sweep(params):
    """One row per parameter: W for the parameter changed by each of SWEEP_STEPS. A cell is
    None below the minimum (start 2, size and count 1), else {value, delta, w, digits, up,
    down, ratio}: up / down when W grows / shrinks against the current W, ratio the integer
    quotient of the larger by the smaller."""
    base = capacity(*layout_of(params))
    rows = []
    for key in PARAMS:
        lo = 2 if key in ("ds", "ks") else 1
        cells = []
        for d in SWEEP_STEPS:
            q = dict(params, **{key: params[key] + d})
            if q[key] < lo:
                cells.append(None)
                continue
            w = capacity(*layout_of(q))
            cells.append({"value": q[key], "delta": d, "w": w, "digits": digit_count(w),
                          "up": w > base, "down": w < base,
                          "ratio": w // base if w > base else base // w})
        rows.append({"key": key, "cells": cells})
    return rows
