"""Texts of the target planner's view: the bad lines of the target list, one table row per
group and the summary under the table (target_planner.Plan, target_plan_costs.Costs).

T is a translator (primeatlas.core.i18n.Translator), duration(seconds) formats a time.
"""
from benchmark_log_schema import ENGINE_PSEUDOSQUARES_COUNT

from ..core import number_format
from . import target_planner

ERRORS_SHOWN = 5


def errors_text(errors, T):
    """The first ERRORS_SHOWN bad lines, one per text line, then how many more there are."""
    lines = [T("target_planner.error_line", line=e.line,
               reason=T(f"target_planner.error_{e.key}"), text=e.text)
             for e in errors[:ERRORS_SHOWN]]
    if len(errors) > ERRORS_SHOWN:
        lines.append(T("target_planner.errors_more", count=len(errors) - ERRORS_SHOWN))
    return "\n".join(lines)


def method_text(group, T):
    if group.method == target_planner.METHOD_ATLAS:
        return T("target_planner.method_atlas", engine=group.engine)
    return T("target_planner.method_pss")


def row_values(number, group, T, duration):
    """(#, floor, from, to, windows, targets, method, time) of one table row."""
    return (str(number), str(group.floor), str(group.lo), str(group.hi),
            number_format.whole(group.windows),
            number_format.whole(group.targets), method_text(group, T), duration(group.seconds))


def summary_text(plan, costs, T, duration):
    """The plan's total, the comparison totals and the notes that apply, one per line."""
    lines = []
    if not plan.groups and not plan.unplanned:
        lines.append(T("target_planner.all_stored"))
    elif plan.seconds is not None:
        lines.append(T("target_planner.summary", groups=len(plan.groups),
                       time=duration(plan.seconds)))
    if plan.groups or plan.unplanned:
        na = T("target_planner.not_available")
        lines.append(T("target_planner.compare",
                       atlas=na if plan.atlas_seconds is None else duration(plan.atlas_seconds),
                       pss=na if plan.pss_seconds is None else duration(plan.pss_seconds)))
    if plan.stored_targets and (plan.groups or plan.unplanned):
        lines.append(T("target_planner.stored", count=plan.stored_targets))
    if plan.unplanned:
        lines.append(T("target_planner.unplanned", count=len(plan.unplanned)))
    if costs.atlas_estimated:
        lines.append(T("target_planner.atlas_estimated"))
    if costs.pss_engine == ENGINE_PSEUDOSQUARES_COUNT:
        lines.append(T("target_planner.pss_from_count"))
    if any(g.method == target_planner.METHOD_PSS for g in plan.groups):
        lines.append(T("target_planner.pss_writes_nothing"))
    return "\n".join(lines)

