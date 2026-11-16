"""number_text -- read_number(), the reader behind every number field: a whole number written
in any common notation, as typed or pasted from a web page, spreadsheet or paper.

Accepted: digit grouping by spaces of any kind, apostrophes, underscores, commas or dots
(groups of three, or Indian lakh groups 1,00,00,000); a decimal comma or dot; powers "^",
"**", superscript digits (10²⁵) and LaTeX braces (10^{25}); scientific "1.5E+25"; times
signs * × · ⋅ ∙ \\times \\cdot and "x" before a power of ten; minus signs - − –; + - * / and
parentheses. Arithmetic is exact (fractions) and evaluated by a small parser, never eval().

A comma or dot that appears once before exactly three digits is either grouping or a decimal
mark, so both readings are tried: only whole results count. One whole result -> OK; several
-> AMBIGUOUS with the candidates; none -> INVALID with a reason (NOT_WHOLE, SYNTAX, TOO_LARGE).
"""
import itertools
import math
import re
from collections import namedtuple
from fractions import Fraction

EMPTY = "empty"
OK = "ok"
AMBIGUOUS = "ambiguous"
INVALID = "invalid"

NOT_WHOLE = "not_whole"
SYNTAX = "syntax"
TOO_LARGE = "too_large"

MAX_EXPONENT = 100_000       # largest |exponent| of one power
MAX_DIGITS = 100_000         # largest result of one power, in decimal digits
MAX_READINGS = 64            # combinations of ambiguous number tokens tried

Reading = namedtuple("Reading", "state value candidates reason")

_SUPERSCRIPT = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻", "0123456789+-")
_SUPERSCRIPT_RUN = re.compile("[⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻]+")
_GROUPING = re.compile(r"[\s'’ʼ`_]")
_LETTER_X = re.compile(r"[xX](?=10(?:\^|\*\*))")
_REPLACEMENTS = (("\\times", "*"), ("\\cdot", "*"), ("×", "*"), ("·", "*"), ("⋅", "*"),
                 ("∙", "*"), ("−", "-"), ("–", "-"), ("**", "^"), ("{", "("), ("}", ")"))
_TOKEN = re.compile(r"(?P<num>\d[\d.,]*(?:[eE][+-]?\d+)?)|(?P<op>[-+*/^()])")
_GROUPS_3 = re.compile(r"\d{1,3}(?:X\d{3})+")
_GROUPS_INDIAN = re.compile(r"\d{1,2}(?:X\d{2})*X\d{3}")


class _Error(Exception):
    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


def _normalise(text):
    text = _SUPERSCRIPT_RUN.sub(lambda m: "^(" + m.group().translate(_SUPERSCRIPT) + ")", text)
    text = _GROUPING.sub("", text)
    for old, new in _REPLACEMENTS:
        text = text.replace(old, new)
    return _LETTER_X.sub("*", text)


def _valid_groups(body, mark):
    shape = body.replace(mark, "X")
    return bool(_GROUPS_3.fullmatch(shape) or _GROUPS_INDIAN.fullmatch(shape))


def _decimal(body, mark):
    whole, _, frac = body.partition(mark)
    if not whole or not frac:
        return None
    return Fraction(int(whole + frac), 10 ** len(frac))


def _mantissas(body):
    """Every reading of digits with commas and dots, as Fractions."""
    marks = [c for c in body if c in ".,"]
    if not marks:
        return [Fraction(int(body))]
    kinds = set(marks)
    if len(kinds) == 2:
        point = marks[-1]
        group = "," if point == "." else "."
        whole, _, frac = body.rpartition(point)
        if point in whole or not frac or not _valid_groups(whole, group):
            return []
        return [_decimal(whole.replace(group, "") + point + frac, point)]
    mark = marks[0]
    readings = []
    if _valid_groups(body, mark):
        readings.append(Fraction(int(body.replace(mark, ""))))
    if len(marks) == 1:
        value = _decimal(body, mark)
        if value is not None:
            readings.append(value)
    return readings


def _number_readings(token):
    body, _, exponent = token.lower().partition("e")
    scale = Fraction(10) ** int(exponent) if exponent else 1
    readings = _mantissas(body)
    if not readings:
        raise _Error(SYNTAX)
    if exponent and abs(int(exponent)) > MAX_EXPONENT:
        raise _Error(TOO_LARGE)
    return [r * scale for r in readings]


def _tokenize(text):
    tokens, pos = [], 0
    while pos < len(text):
        m = _TOKEN.match(text, pos)
        if m is None:
            raise _Error(SYNTAX)
        tokens.append(("num", _number_readings(m.group("num"))) if m.group("num")
                      else ("op", m.group("op")))
        pos = m.end()
    return tokens


def _power(base, exponent):
    if exponent.denominator != 1:
        raise _Error(NOT_WHOLE)
    e = exponent.numerator
    if abs(e) > MAX_EXPONENT:
        raise _Error(TOO_LARGE)
    if base not in (0, 1, -1):
        digits = abs(e) * abs(math.log10(abs(base.numerator)) - math.log10(base.denominator))
        if digits > MAX_DIGITS:
            raise _Error(TOO_LARGE)
    if base == 0 and e < 0:
        raise _Error(SYNTAX)
    return base ** e


class _Parser:
    """expr := term (('+'|'-') term)*; term := unary (('*'|'/') unary)*;
    unary := ('+'|'-') unary | power; power := atom ('^' unary)?; atom := num | '(' expr ')'."""

    def __init__(self, tokens, values):
        self.tokens = tokens
        self.values = iter(values)
        self.pos = 0

    def peek(self):
        return self.tokens[self.pos] if self.pos < len(self.tokens) else (None, None)

    def take(self, op):
        if self.peek() == ("op", op):
            self.pos += 1
            return True
        return False

    def parse(self):
        value = self.expr()
        if self.pos != len(self.tokens):
            raise _Error(SYNTAX)
        return value

    def expr(self):
        value = self.term()
        while True:
            if self.take("+"):
                value += self.term()
            elif self.take("-"):
                value -= self.term()
            else:
                return value

    def term(self):
        value = self.unary()
        while True:
            if self.take("*"):
                value *= self.unary()
            elif self.take("/"):
                divisor = self.unary()
                if divisor == 0:
                    raise _Error(SYNTAX)
                value /= divisor
            else:
                return value

    def unary(self):
        if self.take("-"):
            return -self.unary()
        if self.take("+"):
            return self.unary()
        return self.power()

    def power(self):
        base = self.atom()
        if self.take("^"):
            return _power(base, self.unary())
        return base

    def atom(self):
        kind, _ = self.peek()
        if kind == "num":
            self.pos += 1
            return next(self.values)
        if self.take("("):
            value = self.expr()
            if not self.take(")"):
                raise _Error(SYNTAX)
            return value
        raise _Error(SYNTAX)


def read_number(text):
    """Reading(state, value, candidates, reason) of a field's text; see the module doc."""
    text = _normalise((text or "").strip())
    if not text:
        return Reading(EMPTY, None, (), None)
    try:
        tokens = _tokenize(text)
        choices = [readings for kind, readings in tokens if kind == "num"]
        if math.prod(len(c) for c in choices) > MAX_READINGS:
            raise _Error(SYNTAX)
        results, failure = [], None
        for values in itertools.product(*choices):
            try:
                value = _Parser(tokens, values).parse()
            except _Error as error:
                if error.reason != NOT_WHOLE:
                    raise
                failure = error.reason
                continue
            if value.denominator == 1 and int(value) not in results:
                results.append(int(value))
            elif value.denominator != 1:
                failure = NOT_WHOLE
    except _Error as error:
        return Reading(INVALID, None, (), error.reason)
    if len(results) == 1:
        return Reading(OK, results[0], (results[0],), None)
    if results:
        return Reading(AMBIGUOUS, None, tuple(results), None)
    return Reading(INVALID, None, (), failure or SYNTAX)
