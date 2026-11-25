/* report_view.js -- the zoom and pan of chart_view.py: the notch step, the clamp of a
view to the data, the floor ticks of a zoomed axis. */
var MAX_LEVEL = 18;
var WHEEL_STEP = 0.8;
var MAX_X_TICKS = 24;

// chart_view._clamp: the data's far edge may reach the view's opposite edge, no further.
function clampView(lo, hi, full) {
  var width = hi - lo;
  lo = Math.min(Math.max(lo, full[0] - width), full[1]);
  return [lo, lo + width];
}

// chart_view.zoom_step: [view, level] after `steps` notches; the width follows the level.
function zoomStep(view, level, base, anchor, steps, full) {
  level = Math.min(MAX_LEVEL, Math.max(0, level + steps));
  if (level === 0 || !base || base[1] <= base[0]) return [null, 0];
  var from = view || base;
  var lo = from[0], hi = from[1];
  var width = (base[1] - base[0]) * Math.pow(WHEEL_STEP, level);
  var frac = hi > lo ? (anchor - lo) / (hi - lo) : 0.5;
  frac = Math.min(1.0, Math.max(0.0, frac));
  var newLo = anchor - frac * width;
  return [clampView(newLo, newLo + width, full), level];
}

function pan(view, full, delta) {
  if (!view || !full) return view;
  return clampView(view[0] + delta, view[1] + delta, full);
}

function tickFloors(xMin, xMax, margin) {
  var floors = [];
  for (var f = Math.ceil(xMin - margin); f <= Math.floor(xMax + margin); f++) floors.push(f);
  var step = Math.max(1, Math.ceil(floors.length / MAX_X_TICKS));
  return floors.filter(function (f, i) { return i % step === 0; });
}
