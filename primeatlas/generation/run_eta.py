"""
run_eta.py -- the remaining time of a running generation run from the time model
(time_model.py). No tkinter here.

A run is modelled as its iterations (one for a Quick-gen run, run_count for a pipeline
loop), each a fixed prep cost followed by its sieve and write, which the engine's progress
lines cover by their percent. `done` is the modelled seconds of the work reported finished:
the earlier iterations whole, then the current one's prep plus its percent of the rest.

    remaining = total - max(done, elapsed)        while done < TRUST_SHARE * total
              = (total - done) * elapsed / done   from then on

Before the progress covers TRUST_SHARE of the model the model alone counts down (its wall
clock, or the progress when the run is ahead of it), since the first lines arrive after
the process start-up and the prep, which a pace measured over them would inflate. After
that the modelled rest is scaled by the run's measured pace against the model, so a machine
slower or faster than the calibration's corrects itself. The 10 % share is arbitrary.
"""
import time

TRUST_SHARE = 0.1


def now():
    """Wall clock of the estimate (a test replaces it)."""
    return time.time()


class RunEta:
    def __init__(self, iterations):
        """`iterations`: [(prep_seconds, rest_seconds)], one per iteration in run order."""
        self.iterations = list(iterations)
        self.total = sum(prep + rest for prep, rest in self.iterations)
        self.done = 0.0

    def _before(self, iteration):
        """Modelled seconds of the iterations before 1-based `iteration`, and its index."""
        index = max(1, min(iteration, len(self.iterations))) - 1
        return sum(p + r for p, r in self.iterations[:index]), index

    def mark_sieve(self, iteration, percent):
        """A progress line of `iteration` at `percent` of its sieve and write."""
        if not self.iterations:
            return
        before, index = self._before(iteration)
        prep, rest = self.iterations[index]
        share = max(0.0, min(float(percent), 100.0)) / 100
        self.done = max(self.done, before + prep + share * rest)

    def mark_iteration_done(self, iteration):
        """`iteration`'s done line: it counts whole."""
        if not self.iterations:
            return
        before, index = self._before(iteration)
        self.done = max(self.done, before + sum(self.iterations[index]))

    def remaining(self, elapsed):
        """Seconds left after `elapsed` seconds of the run, or None without a model."""
        if self.total <= 0:
            return None
        if self.done < TRUST_SHARE * self.total:
            return max(0.0, self.total - max(self.done, elapsed))
        return max(0.0, (self.total - self.done) * elapsed / self.done)
