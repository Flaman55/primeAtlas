"""Text of an engine_advisor.Advice, shared by the Time simulation window, the Quick-gen line
and tools/engine_advice.py: the proposal with its reason, the BPSW warning (only when the
proposal is probabilistic) and the guest line (only when a guest is faster).

T is a translator (primeatlas.core.i18n.Translator), duration(seconds) formats a time.
"""
from collections import namedtuple

from . import engine_advisor

AdviceText = namedtuple("AdviceText", "proposal warning guest")


def _ratio(value):
    return f"{value:.1f}" if value < 100 else f"{value:,.0f}"


def _offset(value):
    return f"{value:g}"


def advice_text(advice, T, duration, offset):
    """AdviceText of `advice` (None: the no-proposal line, no warning, no guest)."""
    if advice is None:
        return AdviceText(T("advisor.none"), "", "")
    if advice.reason == engine_advisor.REASON_BPSW_FASTER:
        reason = T("advisor.reason_bpsw_faster", ratio=_ratio(advice.ratio),
                   rival=advice.deterministic_engine,
                   rival_time=duration(advice.deterministic_seconds), offset=_offset(offset))
    elif advice.reason == engine_advisor.REASON_NO_DETERMINISTIC:
        reason = T("advisor.reason_no_deterministic")
    else:
        reason = T("advisor.reason_deterministic")
    proposal = T("advisor.proposal", engine=advice.engine, time=duration(advice.seconds),
                 reason=reason)
    if advice.estimated:
        proposal += " " + T("advisor.estimated")
    warning = "" if advice.deterministic else T("advisor.warning_bpsw")
    guest = ""
    if advice.guest is not None:
        g = advice.guest
        guest = T("advisor.guest", speedup=_ratio(g.speedup), rival=g.rival,
                  time=duration(g.seconds), rival_time=duration(g.rival_seconds))
    return AdviceText(proposal, warning, guest)
