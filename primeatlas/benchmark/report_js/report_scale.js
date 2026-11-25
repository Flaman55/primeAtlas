/* report_scale.js -- the y scale and line clipping of chart_series.py: YScale (linear or
log, pinned ends, zoomed views, ticks), the band clip of a polyline. */
var LOG_MARGIN = 0.06;
var LOG_MIN_SPAN = 0.2;
var VIEW_EPSILON = 1e-9;

function fit(lo, hi, pinLo, pinHi, pad) {
  if (pinLo !== null && pinHi !== null && pinLo < pinHi) return [pinLo, pinHi];
  if (pinHi !== null) return [Math.min(lo, pinHi - pad), pinHi];
  if (pinLo !== null) return [pinLo, Math.max(hi, pinLo + pad)];
  return [lo, hi];
}

function YScale(values, log, pinLo, pinHi) {
  var lo, hi, bounds;
  pinLo = pinLo === undefined ? null : pinLo;
  pinHi = pinHi === undefined ? null : pinHi;
  this.log = log;
  if (log) {
    var positive = values.filter(function (v) { return v > 0; });
    if (!positive.length) positive = [1.0];
    var logLo = pinLo !== null && pinLo > 0 ? Math.log10(pinLo) : null;
    var logHi = pinHi !== null && pinHi > 0 ? Math.log10(pinHi) : null;
    lo = Math.log10(Math.min.apply(null, positive));
    hi = Math.log10(Math.max.apply(null, positive));
    if (hi - lo < LOG_MIN_SPAN) {
      var mid = (lo + hi) / 2;
      lo = mid - LOG_MIN_SPAN / 2;
      hi = mid + LOG_MIN_SPAN / 2;
    }
    var margin = (hi - lo) * LOG_MARGIN;
    bounds = fit(lo - margin, hi + margin, logLo, logHi, LOG_MIN_SPAN);
  } else {
    if (!values.length) values = [0.0];
    lo = Math.min.apply(null, values);
    hi = Math.max.apply(null, values);
    if (lo === hi) {
      var pad0 = Math.max(1.0, Math.abs(lo) * 0.1);
      lo -= pad0;
      hi += pad0;
    }
    lo = Math.min(lo, 0);
    var anchor = pinLo !== null ? pinLo : pinHi;
    var pad = anchor !== null ? Math.max(1.0, Math.abs(anchor) * 0.1) : 0;
    bounds = fit(lo, hi, pinLo, pinHi, pad);
  }
  this.lo = bounds[0];
  this.hi = bounds[1];
}

YScale.prototype.zoomed = function (view) {
  if (!view) return this;
  var out = Object.create(YScale.prototype);
  var span = this.hi - this.lo;
  out.log = this.log;
  out.lo = this.lo + view[0] * span;
  out.hi = this.lo + view[1] * span;
  return out;
};

YScale.prototype.usable = function (value) { return this.log ? value > 0 : true; };

YScale.prototype.frac = function (value) {
  if (this.log) return (Math.log10(value) - this.lo) / (this.hi - this.lo);
  return (value - this.lo) / (this.hi - this.lo);
};

YScale.prototype.logTicks = function (mantissas, step) {
  var out = [];
  for (var k = Math.floor(this.lo); k < Math.ceil(this.hi) + 1; k += step || 1) {
    for (var i = 0; i < mantissas.length; i++) {
      var e = Math.log10(mantissas[i]) + k;
      if (this.lo <= e && e <= this.hi) out.push(mantissas[i] * Math.pow(10, k));
    }
  }
  return out;
};

YScale.prototype.ticks = function () {
  if (this.log) {
    var span = this.hi - this.lo;
    if (span > 8) return this.logTicks([1], 2);
    var sets = (span > 2.5 ? [[1]] : []).concat([[1, 2, 5], [1, 2, 3, 4, 5, 6, 7, 8, 9]]);
    var ticks = [];
    for (var i = 0; i < sets.length; i++) {
      ticks = this.logTicks(sets[i]);
      if (ticks.length >= 2) return ticks;
    }
    return ticks;
  }
  var out = [];
  for (var j = 0; j < 6; j++) out.push(this.lo + (this.hi - this.lo) * j / 5);
  return out;
};

YScale.prototype.tickLabel = function (value, decimals) {
  if (this.log) {
    var exponent = Math.floor(Math.log10(value) + 1e-9);
    return Math.round(value / Math.pow(10, exponent)) + "e" + exponent;
  }
  return formatCompact(decimals, value);
};

function inView(frac) { return -VIEW_EPSILON <= frac && frac <= 1 + VIEW_EPSILON; }

// chart_series._clip: runs of a polyline inside bandLo <= coordinate k <= bandHi.
function clipBand(points, k, bandLo, bandHi, inside) {
  var runs = [], run = [];
  function cross(a, b, edge) {
    var t = (edge - a[k]) / (b[k] - a[k]);
    var other = a[1 - k] + (b[1 - k] - a[1 - k]) * t;
    return k === 0 ? [edge, other] : [other, edge];
  }
  for (var i = 0; i < points.length; i++) {
    var p = points[i];
    if (i) {
      var a = points[i - 1];
      var lo = Math.min(a[k], p[k]), hi = Math.max(a[k], p[k]);
      var edges = (bandLo === bandHi ? [bandLo] : [bandLo, bandHi])
        .filter(function (e) { return lo < e && e < hi; });
      if (a[k] > p[k]) edges.reverse();
      for (var j = 0; j < edges.length; j++) {
        var q = cross(a, p, edges[j]);
        if (run.length) {
          run.push(q);
          runs.push(run);
          run = [];
        } else {
          run = [q];
        }
      }
    }
    if (inside(p[k])) {
      run.push(p);
    } else if (run.length) {
      runs.push(run);
      run = [];
    }
  }
  if (run.length) runs.push(run);
  return runs;
}

// chart_series.clip_polyline: runs of [(x, frac)] inside 0 <= frac <= 1 and xLo <= x <= xHi.
function clipPolyline(points, xLo, xHi) {
  var runs = clipBand(points, 1, 0, 1, inView);
  if (xLo === undefined) return runs;
  var out = [];
  runs.forEach(function (run) {
    out = out.concat(clipBand(run, 0, xLo, xHi, function (x) { return xLo <= x && x <= xHi; }));
  });
  return out;
}
