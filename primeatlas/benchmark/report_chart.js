/* report_chart.js -- the interactive charts of the Benchmark HTML report (report_html.py).

The page carries the runs the app's filter kept at export (script.pa-data, JSON) and this script redraws its charts in
the browser: the runs the page's filter keeps, then the last row per floor and line (the
reduction of benchmark.benchmark_engine_lines()), drawn with the layout of chart_pdf.chart_ops()
ported line by line, so with nothing hidden and no zoom a chart is the SVG the report's Python
side writes (unitTests/test_benchmark_report_html.py compares the two through node).

Gestures as in the Benchmark tab (chart_view.py), zooming like a picture: the mouse wheel over a
chart zooms the part under the pointer on both axes (the floor axis of every chart, the y axis of
that chart), a left drag moves the visible part, a double or middle click shows the whole
charts; a legend entry hides or shows its line. The wheel zooms only over a chart's picture; elsewhere
it scrolls the page. "Chart text" sets the text size: the charts are drawn on a canvas 1/k as
large and shown at their usual width, so text, markers and lines grow k times. The filter (per
dimension All and its values, clicked like the app's: toggleValue(), selectAll()), log scale and
reference toggles redraw the charts, the page headings and the tables (rows of runs the filter
drops are hidden).

Pure parts (scale, labels, reduction, zoom, chart drawing) are exported for node; the page
part runs only in a browser, on the .primeatlas-benchmark element holding this script.
*/
(function () {
  "use strict";

  var LABEL_SIZE = 7;
  var LABEL_CHAR_W = 0.6 * LABEL_SIZE;
  var LAST_LABEL_STEPS = 5;
  var AXIS_GRAY = "#666666";
  var GUIDE_GRAY = "#e0e0e0";
  var BOX_GRAY = "#cccccc";
  var LOG_MARGIN = 0.06;
  var LOG_MIN_SPAN = 0.2;
  var VIEW_EPSILON = 1e-9;
  var MAX_LEVEL = 18;
  var WHEEL_STEP = 0.8;
  var MAX_X_TICKS = 24;
  var TEXT_SCALES = [1, 1.25, 1.5, 1.75, 2];
  var DEFAULT_TEXT_SCALE = 1.5;
  var DRAG_SLOP_PX = 4;
  var FONTS = {"Helvetica": ["sans-serif", "normal"], "Helvetica-Bold": ["sans-serif", "bold"],
               "Courier": ["monospace", "normal"]};

  function escapeXml(text) {
    return String(text).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function fill(template, values) {
    return template.replace(/\{(\w+)\}/g, function (m, key) {
      return key in values ? String(values[key]) : m;
    });
  }

  function formatNumber(decimals, value) {
    return value.toLocaleString("en-US", {minimumFractionDigits: decimals,
                                          maximumFractionDigits: decimals});
  }

  // --- chart_series.YScale ---------------------------------------------------------------

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
    return formatNumber(decimals, value);
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

  // chart_pdf.place_labels
  function placeLabels(candidates) {
    var placed = [], boxes = [];
    var order = candidates.map(function (c, i) { return [c, i]; });
    order.sort(function (a, b) {
      return a[0].prio[0] - b[0].prio[0] || a[0].prio[1] - b[0].prio[1] || a[1] - b[1];
    });
    order.forEach(function (entry) {
      var c = entry[0];
      for (var i = 0; i < c.positions.length; i++) {
        var x = c.positions[i][0], y = c.positions[i][1];
        var box = [x, y - 1, x + c.text.length * LABEL_CHAR_W, y + LABEL_SIZE];
        var free = boxes.every(function (b) {
          return !(box[0] < b[2] && b[0] < box[2] && box[1] < b[3] && b[1] < box[3]);
        });
        if (free) {
          boxes.push(box);
          placed.push([x, y, c.text, c.color]);
          break;
        }
      }
    });
    return placed;
  }

  // --- chart_svg.SvgBackend ------------------------------------------------------------

  function Backend(height) { this.height = height; }
  Backend.prototype.y = function (y) { return this.height - y; };
  Backend.prototype.rect = function (x, y, w, h, fill, stroke, width) {
    var s = stroke ? ' stroke="' + stroke + '" stroke-width="' + (width || 1).toFixed(2) + '"' : "";
    return '<rect x="' + x.toFixed(2) + '" y="' + this.y(y + h).toFixed(2) + '" width="' +
      w.toFixed(2) + '" height="' + h.toFixed(2) + '" fill="' + (fill || "none") + '"' + s + "/>";
  };
  Backend.prototype.line = function (x1, y1, x2, y2, width, color) {
    return '<line x1="' + x1.toFixed(2) + '" y1="' + this.y(y1).toFixed(2) + '" x2="' +
      x2.toFixed(2) + '" y2="' + this.y(y2).toFixed(2) + '" stroke="' + (color || "#000000") +
      '" stroke-width="' + (width === undefined ? 1 : width).toFixed(2) + '"/>';
  };
  Backend.prototype.dot = function (cx, cy, r, color, title) {
    var head = '<circle cx="' + cx.toFixed(2) + '" cy="' + this.y(cy).toFixed(2) + '" r="' +
      r.toFixed(2) + '" fill="' + (color || "#000000") + '"';
    return title ? head + "><title>" + escapeXml(title) + "</title></circle>" : head + "/>";
  };
  Backend.prototype.text = function (x, y, size, font, text, color) {
    var f = FONTS[font] || ["sans-serif", "normal"];
    return '<text x="' + x.toFixed(2) + '" y="' + this.y(y).toFixed(2) + '" font-family="' +
      f[0] + '" font-weight="' + f[1] + '" font-size="' + size + '" fill="' +
      (color || "#000000") + '">' + escapeXml(text) + "</text>";
  };
  function dashed(element) { return element.replace("/>", ' stroke-dasharray="3 2"/>'); }

  function pointLabel(decimals, value, series, x) {
    var note = (series.notes || {})[x] || "";
    return formatNumber(decimals, value) + (series.tag ? " [" + series.tag + "]" : "") +
      (note ? " @ " + note : "");
  }

  /* One chart as an <svg> element of w x h points, the layout of chart_pdf.chart_ops() on
  one axis. c: {series: drawn [{name, tag, color, dashed, points: [[x, y]], notes}],
  legend: [{name, color, dashed, hidden}] (every line of the chart, hidden ones dimmed),
  title, decimals, log, pins: [min, max], view: [lo, hi] floors | null, yView: [lo, hi]
  fractions of the full y scale | null, text: {floor, pinned, no_data, all_hidden}}. Returns
  {svg, geometry: [x of the first floor, its width, first floor, last floor, y of the plot
  top, plot height, yView, the data's [lowest, highest] fraction of the full y scale, the
  chart's own [first, last] floor unzoomed] | null}, the chart_geometry of the tab's canvas. */
  function chartSvg(w, h, c) {
    var b = new Backend(h);
    var t = c.text;
    var series = c.series.filter(function (s) { return s.points.length; });
    var ops = [b.rect(0, 0, w, h, null, BOX_GRAY, 0.5)];
    var geometry = null;
    var legend = c.legend || [];
    function done() {
      return {svg: '<svg xmlns="http://www.w3.org/2000/svg" width="' + w + '" height="' + h +
                   '" viewBox="0 0 ' + w + " " + h + '"><rect width="' + w + '" height="' + h +
                   '" fill="#ffffff"/>' + ops.join("") + "</svg>", geometry: geometry};
    }
    function drawLegend() {
      var lx = 90;
      legend.forEach(function (s) {
        var line = b.line(lx - 5, h - 8, lx + 5, h - 8, 1.5, s.color);
        var parts = [s.dashed ? dashed(line) : line, b.dot(lx, h - 8, 2.5, s.color)];
        if (s.dashed) parts.push(b.dot(lx, h - 8, 1.3, "#ffffff"));
        parts.push(b.text(lx + 8, h - 10.5, 6.5, "Helvetica-Bold", s.name, s.color));
        ops.push('<g class="pa-legend" data-line="' + escapeXml(s.name) + '"' +
                 (s.hidden ? ' opacity="0.35"' : "") + ">" + parts.join("") + "</g>");
        lx += 22 + 6.5 * 0.55 * s.name.length;
      });
    }
    if (!series.length) {
      if (!legend.length) {
        ops.push(b.text(w / 2 - 60, h / 2, 10, "Helvetica", t.no_data));
      } else {
        drawLegend();
        ops.push(b.text(w / 2 - 120, h / 2, 10, "Helvetica", t.all_hidden));
      }
      return done();
    }
    var pins = c.pins || [null, null];
    var values = [];
    series.forEach(function (s) { s.points.forEach(function (p) { values.push(p[1]); }); });
    var full = new YScale(values, c.log, pins[0], pins[1]);
    var scale = full.zoomed(c.yView);
    // chart_view.data_fracs: the y view pans within the data, not the scale's empty part.
    var fracs = [];
    series.forEach(function (s) {
      s.points.forEach(function (p) {
        if (full.usable(p[1])) fracs.push(Math.min(1, Math.max(0, full.frac(p[1]))));
      });
    });
    var dataFracs = fracs.length ? [Math.min.apply(null, fracs), Math.max.apply(null, fracs)]
      : [0, 1];
    var tickChars = 0;
    scale.ticks().forEach(function (v) {
      tickChars = Math.max(tickChars, scale.tickLabel(v, c.decimals).length);
    });
    var padLeft = Math.max(55, tickChars * 0.6 * 7 + 10);
    var padRight = 15;
    var plotX0 = padLeft, plotY0 = 30;
    var plotW = Math.max(1, w - padLeft - padRight);
    var plotH = Math.max(1, h - 30 - 30);

    var xsSet = {};
    series.forEach(function (s) { s.points.forEach(function (p) { xsSet[p[0]] = true; }); });
    var allXs = Object.keys(xsSet).map(Number).sort(function (a, b2) { return a - b2; });
    var xMin = c.view ? c.view[0] : allXs[0];
    var xMax = c.view ? c.view[1] : allXs[allXs.length - 1];
    if (xMin === xMax) {
      xMin -= 1;
      xMax += 1;
    }
    var pinned = pins[0] !== null || pins[1] !== null;
    var title = c.title + (pinned ? " [" + t.pinned + "]" : "");
    var insetX = Math.max(15.0, plotW * 0.05);
    function sx(x) { return plotX0 + insetX + (x - xMin) / (xMax - xMin) * (plotW - 2 * insetX); }
    function sy(y) { return plotY0 + scale.frac(y) * plotH; }
    function sf(frac) { return plotY0 + frac * plotH; }
    function onPlot(xPx) { return plotX0 <= xPx && xPx <= plotX0 + plotW; }
    geometry = [plotX0 + insetX, plotW - 2 * insetX, xMin, xMax, h - plotY0 - plotH, plotH,
                c.yView || null, dataFracs, [allXs[0], allXs[allXs.length - 1]]];
    var margin = insetX / Math.max(1.0, plotW - 2 * insetX) * (xMax - xMin);
    var xTicks = c.view ? tickFloors(xMin, xMax, margin) : allXs;

    scale.ticks().forEach(function (v) {
      ops.push(b.line(plotX0, sy(v), plotX0 + plotW, sy(v), 0.4, GUIDE_GRAY));
    });
    ops.push(b.line(plotX0, plotY0, plotX0, plotY0 + plotH, 1, AXIS_GRAY));
    ops.push(b.line(plotX0, plotY0, plotX0 + plotW, plotY0, 1, AXIS_GRAY));
    scale.ticks().forEach(function (v) {
      var yPx = sy(v);
      ops.push(b.line(plotX0 - 3, yPx, plotX0, yPx, 1, AXIS_GRAY));
      var text = scale.tickLabel(v, c.decimals);
      ops.push(b.text(plotX0 - 5 - text.length * 0.6 * 7, yPx - 3, 7, "Courier", text));
    });
    xTicks.forEach(function (x) {
      var xPx = sx(x);
      ops.push(b.line(xPx, plotY0, xPx, plotY0 - 3, 1, AXIS_GRAY));
      ops.push(b.text(xPx - 8, plotY0 - 14, 7, "Courier", String(x)));
    });
    ops.push(b.text(plotX0 + plotW / 2 - 30, 4, 8, "Helvetica-Bold", t.floor));
    ops.push(b.dot(4, h - 7.5, 2.2, AXIS_GRAY));
    ops.push(b.text(9, h - 10, 8, "Helvetica-Bold", title));
    drawLegend();

    var candidates = [];
    var labelYMin = plotY0 + 2, labelYMax = h - 22;
    series.forEach(function (s) {
      var pts = s.points.filter(function (p) { return scale.usable(p[1]); });
      clipPolyline(pts.map(function (p) { return [sx(p[0]), scale.frac(p[1])]; }),
                   plotX0, plotX0 + plotW)
        .forEach(function (run) {
          for (var i = 1; i < run.length; i++) {
            var op = b.line(run[i - 1][0], sf(run[i - 1][1]), run[i][0], sf(run[i][1]), 1.8,
                            s.color);
            ops.push(s.dashed ? dashed(op) : op);
          }
        });
      pts = pts.filter(function (p) { return inView(scale.frac(p[1])) && onPlot(sx(p[0])); });
      pts.forEach(function (p, i) {
        var cx = sx(p[0]), cy = sy(p[1]);
        var text = pointLabel(c.decimals, p[1], s, p[0]);
        ops.push(b.dot(cx, cy, 2.5, s.color, "10^" + p[0] + ": " + text));
        if (s.dashed) ops.push(b.dot(cx, cy, 1.3, "#ffffff"));
        var last = i === pts.length - 1;
        var above = cy + 8, below = cy - 22 - 8;
        var lx = Math.max(2, Math.min(cx - 10, w - 2 - text.length * LABEL_CHAR_W));
        var positions = [];
        for (var k = 0; k < (last ? LAST_LABEL_STEPS : 1); k++) {
          [above + k * (LABEL_SIZE + 2), below - k * (LABEL_SIZE + 2)].forEach(function (y) {
            if (labelYMin <= y && y <= labelYMax) positions.push([lx, y]);
          });
        }
        candidates.push({prio: [last ? 0 : 1, cx], positions: positions, text: text,
                         color: s.color});
      });
    });
    placeLabels(candidates).forEach(function (l) {
      ops.push(b.text(l[0], l[1], LABEL_SIZE, "Courier", l[2], l[3]));
    });
    return done();
  }

  // --- the runs, the filter and the reduction ---------------------------------------------

  function keptRuns(data, selection) {
    var kept = [];
    for (var run = 0; run < data.runs; run++) {
      var keep = data.dims.every(function (dim) {
        var chosen = selection[dim.key];
        return !chosen || chosen.has(dim.values[dim.of_run[run]]);
      });
      kept.push(keep);
    }
    return kept;
  }

  /* {line index: [[floor, value, width]] ascending}: the last record per floor and line among
  the kept runs (records are in log order). */
  function reduce(records, kept) {
    var latest = {};
    records.forEach(function (r) {
      if (!kept[r[0]]) return;
      (latest[r[1]] = latest[r[1]] || {})[r[2]] = [r[2], r[3], r[4]];
    });
    var out = {};
    Object.keys(latest).forEach(function (line) {
      out[line] = Object.keys(latest[line]).map(function (f) { return latest[line][f]; })
        .sort(function (a, b) { return a[0] - b[0]; });
    });
    return out;
  }

  function mixedFloors(reduced, view) {
    var widths = {};
    Object.keys(reduced).forEach(function (line) {
      reduced[line].forEach(function (p) {
        if (p[2] && (!view || (view[0] <= p[0] && p[0] <= view[1]))) {
          (widths[p[0]] = widths[p[0]] || {})[p[2]] = true;
        }
      });
    });
    return Object.keys(widths).filter(function (f) { return Object.keys(widths[f]).length > 1; })
      .map(Number);
  }

  /* chart_filter.toggle_value(): from All (key absent) only the clicked value; otherwise the
  value is added or removed, and removing the last one goes back to All. A new selection. */
  function toggleValue(selection, key, value) {
    var out = {};
    Object.keys(selection).forEach(function (k) { out[k] = new Set(selection[k]); });
    if (!out[key]) out[key] = new Set([value]);
    else if (out[key].has(value)) {
      out[key].delete(value);
      if (!out[key].size) delete out[key];
    } else out[key].add(value);
    return out;
  }

  /* chart_filter.select_all(): the selection with `key` back at All. */
  function selectAll(selection, key) {
    var out = {};
    Object.keys(selection).forEach(function (k) {
      if (k !== key) out[k] = new Set(selection[k]);
    });
    return out;
  }

  function filterSummary(data, selection) {
    var t = data.text;
    var parts = [];
    data.dims.forEach(function (dim) {
      var chosen = selection[dim.key];
      if (!chosen) return;
      var shown = dim.values.map(function (v, i) { return chosen.has(v) ? dim.labels[i] : null; })
        .filter(function (label) { return label !== null; }).join(", ");
      parts.push(dim.label + ": " + (shown || "-"));
    });
    return parts.length ? fill(t.filter_on, {parts: parts.join("; ")}) : t.filter_off;
  }

  // --- chart_view.py --------------------------------------------------------------------

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

  // --- the page -------------------------------------------------------------------------

  function Report(root, data) {
    this.root = root;
    this.data = data;
    var selection = {};
    Object.keys(data.selection).forEach(function (k) { selection[k] = new Set(data.selection[k]); });
    this.selection = selection;
    this.view = data.view;
    this.xLevel = data.x_level;
    this.xBase = data.x_base;
    this.yViews = {};
    this.yLevels = {};
    this.scale = DEFAULT_TEXT_SCALE;
    this.log = data.log;
    this.refs = data.refs_on;
    this.hidden = {};
    var self = this;
    data.pages.forEach(function (page, i) {
      page.charts.forEach(function (chart, j) {
        self.hidden[i + "/" + j] = new Set(chart.hidden);
        self.yViews[i + "/" + j] = chart.y_view;
        self.yLevels[i + "/" + j] = chart.y_level;
      });
    });
    this.geometry = {};
    this.buildControls();
    this.bindCharts();
    this.render();
  }

  Report.prototype.buildControls = function () {
    var self = this, d = this.data, t = d.text;
    var box = this.root.querySelector(".pa-controls");
    var html = '<div class="pa-row"><label><input type="checkbox" data-toggle="log"' +
      (this.log ? " checked" : "") + "> " + escapeXml(t.log) + "</label>";
    if (d.refs_available) {
      html += '<label><input type="checkbox" data-toggle="refs"' + (this.refs ? " checked" : "") +
        "> " + escapeXml(t.refs) + "</label>";
    }
    html += "<label>" + escapeXml(t.text_size) + ' <select data-toggle="scale">' +
      TEXT_SCALES.map(function (k) {
        return '<option value="' + k + '"' + (k === self.scale ? " selected" : "") + ">" +
          Math.round(k * 100) + "%</option>";
      }).join("") + "</select></label>";
    html += '<button type="button" data-act="runs">' + escapeXml(t.all_runs) + "</button>" +
      '<button type="button" data-act="floors">' + escapeXml(t.all_floors) + "</button></div>";
    d.dims.forEach(function (dim) {
      html += '<div class="pa-row pa-dim" data-dim="' + dim.key + '"><span class="pa-dim-name">' +
        escapeXml(dim.label) + '</span><span class="pa-values">' +
        '<label><input type="checkbox" data-dim-all="' + dim.key + '"> ' + escapeXml(t.all) +
        "</label>";
      dim.values.forEach(function (v, i) {
        html += '<label><input type="checkbox" data-dim-value="' + dim.key + '" data-index="' + i +
          '"> ' + escapeXml(dim.labels[i]) + "</label>";
      });
      html += "</span></div>";
    });
    html += '<p class="pa-hint">' + escapeXml(t.hint) + "</p>";
    box.innerHTML = html;
    box.addEventListener("change", function (e) {
      var el = e.target;
      if (el.dataset.toggle === "log") self.log = el.checked;
      else if (el.dataset.toggle === "scale") self.scale = Number(el.value);
      else if (el.dataset.toggle === "refs") self.refs = el.checked;
      else if (el.dataset.dimAll) self.selection = selectAll(self.selection, el.dataset.dimAll);
      else if (el.dataset.dimValue) {
        var dim = self.dimension(el.dataset.dimValue);
        self.selection = toggleValue(self.selection, dim.key,
                                     dim.values[Number(el.dataset.index)]);
      }
      self.render();
    });
    box.addEventListener("click", function (e) {
      var act = e.target.dataset && e.target.dataset.act;
      if (act === "runs") self.selection = {};
      else if (act === "floors") self.resetView();
      else return;
      self.render();
    });
  };

  Report.prototype.dimension = function (key) {
    return this.data.dims.filter(function (dim) { return dim.key === key; })[0];
  };

  Report.prototype.syncControls = function () {
    var self = this;
    this.root.querySelectorAll(".pa-dim").forEach(function (row) {
      var key = row.dataset.dim, chosen = self.selection[key];
      var dim = self.dimension(key);
      row.querySelector("[data-dim-all]").checked = !chosen;
      row.querySelectorAll("[data-dim-value]").forEach(function (box) {
        box.checked = !!chosen && chosen.has(dim.values[Number(box.dataset.index)]);
      });
    });
  };

  Report.prototype.chartSeries = function (chart, kept, reduced) {
    var lines = this.data.lines;
    var out = Object.keys(reduced).map(Number).sort(function (a, b) { return a - b; })
      .map(function (i) {
        var notes = {};
        reduced[i].forEach(function (p) { notes[p[0]] = p[2]; });
        return {name: lines[i].name, tag: lines[i].tag, color: lines[i].color, dashed: false,
                points: reduced[i].map(function (p) { return [p[0], p[1]]; }), notes: notes};
      });
    if (chart.refs && this.refs) out = out.concat(this.data.refs);
    return out;
  };

  Report.prototype.render = function () {
    var self = this, d = this.data, t = d.text;
    var kept = keptRuns(d, this.selection);
    this.syncControls();
    var floors = {}, runs = 0;
    kept.forEach(function (keep, run) {
      if (!keep) return;
      runs += 1;
      floors[d.floor_of_run[run]] = true;
    });
    var parts = Object.keys(this.selection).length ? [filterSummary(d, this.selection)] : [];
    if (t.measure_note) parts.push(t.measure_note);
    this.root.querySelector(".pa-subtitle").textContent =
      fill(t.subtitle, {runs: runs, depths: Object.keys(floors).length}) +
      (parts.length ? "  |  " + parts.join("  |  ") : "");

    var pages = d.pages.map(function (page) {
      return page.charts.map(function (chart) {
        var reduced = reduce(chart.records, kept);
        return {reduced: reduced, series: self.chartSeries(chart, kept, reduced)};
      });
    });
    var xs = [];
    pages.forEach(function (charts) {
      charts.forEach(function (c) {
        c.series.forEach(function (s) { s.points.forEach(function (p) { xs.push(p[0]); }); });
      });
    });
    var span = xs.length ? [Math.min.apply(null, xs), Math.max.apply(null, xs)] : null;
    this.span = span;
    // A filter change keeps the zoom level; the view only moves back toward the new floors.
    if (this.view && span) this.view = clampView(this.view[0], this.view[1], span);
    var view = this.view;
    this.w = Math.round(d.width / this.scale);
    this.h = Math.round(d.height / this.scale);

    d.pages.forEach(function (page, i) {
      var mixed = {};
      pages[i].forEach(function (c) {
        mixedFloors(c.reduced, view).forEach(function (f) { mixed[f] = true; });
      });
      var mixedList = Object.keys(mixed).map(Number).sort(function (a, b) { return a - b; });
      var heading = (page.heading ? [page.heading] : [])
        .concat(mixedList.length ? [fill(t.mixed, {floors: mixedList.join(", ")})] : []);
      self.root.querySelector('.pa-heading[data-page="' + i + '"]').textContent =
        heading.join("  |  ");
      page.charts.forEach(function (chart, j) {
        var hidden = self.hidden[i + "/" + j];
        var all = pages[i][j].series;
        // Engines first, references after, each in its own order (chart_series.legend_series).
        var legend = all.slice().sort(function (a, b) { return a.dashed - b.dashed; })
          .map(function (s) {
            return {name: s.name, color: s.color, dashed: s.dashed, hidden: hidden.has(s.name)};
          });
        var drawn = all.filter(function (s) { return !hidden.has(s.name); });
        var out = chartSvg(self.w, self.h, {series: drawn, legend: legend, title: chart.title,
                                               decimals: chart.decimals, log: self.log,
                                               pins: chart.pins, view: view,
                                               yView: self.yViews[i + "/" + j], text: t});
        var box = self.root.querySelector('.pa-chart[data-page="' + i + '"][data-chart="' + j + '"]');
        box.innerHTML = out.svg;
        // Shown at the report's chart width whatever the drawing size (text size).
        box.firstChild.setAttribute("width", d.width);
        box.firstChild.setAttribute("height", d.height);
        self.geometry[i + "/" + j] = out.geometry;
      });
    });
    this.root.querySelectorAll("tr[data-run]").forEach(function (tr) {
      tr.hidden = !kept[Number(tr.dataset.run)];
    });
  };

  // The pointer in the chart's own units (its viewBox), whatever size the page draws it at.
  Report.prototype.pointer = function (box, e) {
    var rect = box.querySelector("svg").getBoundingClientRect();
    return [(e.clientX - rect.left) * this.w / rect.width,
            (e.clientY - rect.top) * this.h / rect.height];
  };

  Report.prototype.resetView = function () {
    var self = this;
    this.view = null;
    this.xLevel = 0;
    this.xBase = null;
    Object.keys(this.yViews).forEach(function (k) {
      self.yViews[k] = null;
      self.yLevels[k] = 0;
    });
  };

  Report.prototype.bindCharts = function () {
    var self = this, drag = null;
    // Only the chart's picture takes the gestures; the rest of its row scrolls the page.
    function chartOf(e) {
      var svg = e.target.closest ? e.target.closest(".pa-chart svg") : null;
      var box = svg && svg.parentNode;
      return box && self.root.contains(box) ? box : null;
    }
    function key(box) { return box.dataset.page + "/" + box.dataset.chart; }
    this.root.addEventListener("wheel", function (e) {
      var box = chartOf(e), g = box && self.geometry[key(box)];
      if (!g) return;
      e.preventDefault();
      var at = self.pointer(box, e);
      var yv = g[6] || [0, 1];
      var steps = e.deltaY < 0 ? 1 : -1, k = key(box);
      if (self.xLevel === 0) self.xBase = g[8];
      var x = zoomStep(self.view, self.xLevel, self.xBase,
                       g[2] + (at[0] - g[0]) / g[1] * (g[3] - g[2]), steps, self.span);
      self.view = x[0];
      self.xLevel = x[1];
      var y = zoomStep(self.yViews[k], self.yLevels[k], [0, 1],
                       yv[0] + (g[4] + g[5] - at[1]) / g[5] * (yv[1] - yv[0]), steps, g[7]);
      self.yViews[k] = y[0];
      self.yLevels[k] = y[1];
      self.render();
    }, {passive: false});
    this.root.addEventListener("pointerdown", function (e) {
      var box = chartOf(e), g = box && self.geometry[key(box)];
      if (e.button === 1 && box) {
        e.preventDefault();
        self.resetView();
        self.render();
        return;
      }
      drag = g && e.button === 0 ? {at: self.pointer(box, e), view: self.view, key: key(box),
                                    yView: self.yViews[key(box)], g: g, box: box,
                                    moved: false} : null;
    });
    this.root.addEventListener("pointermove", function (e) {
      if (!drag || (!drag.view && !drag.yView)) return;
      var at = self.pointer(drag.box, e);
      var dx = at[0] - drag.at[0], dy = at[1] - drag.at[1];
      if (!drag.moved && Math.max(Math.abs(dx), Math.abs(dy)) < DRAG_SLOP_PX) return;
      drag.moved = true;
      var g = drag.g, yv = g[6] || [0, 1];
      self.view = pan(drag.view, self.span, -dx * (g[3] - g[2]) / g[1]);
      self.yViews[drag.key] = pan(drag.yView, g[7], dy * (yv[1] - yv[0]) / g[5]);
      self.render();
    });
    window.addEventListener("pointerup", function () {
      if (drag && drag.moved) self.suppressClick = true;
      drag = null;
    });
    this.root.addEventListener("dblclick", function (e) {
      if (!chartOf(e)) return;
      self.resetView();
      self.render();
    });
    this.root.addEventListener("click", function (e) {
      if (self.suppressClick) {
        self.suppressClick = false;
        return;
      }
      var box = chartOf(e);
      var entry = box && e.target.closest("[data-line]");
      if (!entry) return;
      var hidden = self.hidden[key(box)], name = entry.dataset.line;
      if (hidden.has(name)) hidden.delete(name); else hidden.add(name);
      self.render();
    });
  };

  var api = {YScale: YScale, clipPolyline: clipPolyline, placeLabels: placeLabels,
             chartSvg: chartSvg, keptRuns: keptRuns, reduce: reduce, mixedFloors: mixedFloors,
             filterSummary: filterSummary, toggleValue: toggleValue, selectAll: selectAll, zoomStep: zoomStep, pan: pan, tickFloors: tickFloors,
             formatNumber: formatNumber};
  if (typeof module === "object" && module.exports) module.exports = api;
  if (typeof document !== "undefined" && document.currentScript) {
    var root = document.currentScript.closest(".primeatlas-benchmark");
    var dataEl = root && root.querySelector("script.pa-data");
    if (dataEl) new Report(root, JSON.parse(dataEl.textContent));
  }
})();
