"""Text of a width_advisor.WidthAdvice for the Quick-gen width line: a benchmark proposal with
its speeds and the note that the prep time stays, or an Explore proposal with its total times
(an exact split, or a wider one naming the extra windows).
The speeds and times are left out when the time model has no calibration for the engine.

T is a translator (primeatlas.core.i18n.Translator), duration(seconds) formats a time,
rate(numbers per second) a speed.
"""
from ..core import number_format
from . import width_advisor


def width_text(advice, T, duration, rate):
    if advice.kind == width_advisor.KIND_BENCHMARK:
        speeds = ""
        if advice.speed is not None and advice.new_speed is not None:
            speeds = T("width_advice.benchmark_speeds", speed=rate(advice.speed),
                       new_speed=rate(advice.new_speed))
        return T("width_advice.benchmark", windows=number_format.whole(advice.windows),
                 new_windows=number_format.whole(advice.new_windows), speeds=speeds,
                 note=T("width_advice.benchmark_note"))
    times = ""
    if advice.seconds is not None and advice.new_seconds is not None:
        times = T("width_advice.explore_times", time=duration(advice.seconds),
                  new_time=duration(advice.new_seconds))
    extra = advice.new_iterations * advice.new_windows - advice.iterations * advice.windows
    key = ("width_advice.explore" if advice.kind == width_advisor.KIND_EXPLORE
           else "width_advice.explore_wider")
    return T(key, iterations=advice.iterations,
             windows=number_format.whole(advice.windows), new_iterations=advice.new_iterations,
             new_windows=number_format.whole(advice.new_windows), extra=number_format.whole(extra),
             times=times)
