/* report_svg.js -- one chart as SVG: chart_pdf.chart_ops() ported line by line onto the
SvgBackend of chart_svg.py, with chart_pdf.place_labels() for the point labels. */
var LABEL_SIZE = 7;
var LABEL_CHAR_W = 0.6 * LABEL_SIZE;
var LAST_LABEL_STEPS = 5;
var TITLE_CHAR_W = 0.6 * 8;
var LEGEND_LEFT = 90;
var LEGEND_GAP = 14;
var AXIS_GRAY = "#666666";
var GUIDE_GRAY = "#e0e0e0";
var BOX_GRAY = "#cccccc";

var FONTS = {"Helvetica": ["sans-serif", "normal"], "Helvetica-Bold": ["sans-serif", "bold"],
             "Courier": ["monospace", "normal"]};

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

/* One chart as an <svg> element of w x h points, the layout of chart_pdf.chart_ops() on
one axis. c: {series: drawn [{name, tag, color, dashed, points: [[x, y]], notes}],
legend: [{name, color, dashed, hidden}] (every line of the chart, hidden ones dimmed),
title, decimals, log, pins: [min, max], view: [lo, hi] x | null, yView: [lo, hi]
fractions of the full y scale | null, xMode: "floor" (default) | "width", text: {floor,
width, pinned, no_data, all_hidden}}. Returns
{svg, geometry: [x of the first floor, its width, first floor, last floor, y of the plot
top, plot height, yView, the data's [lowest, highest] fraction of the full y scale, the
chart's own [first, last] floor unzoomed] | null}, the chart_geometry of the tab's canvas. */
function chartSvg(w, h, c) {
  var b = new Backend(h);
  var t = c.text;
  var xMode = c.xMode || "floor";
  var series = c.series.filter(function (s) { return s.points.length; });
  var ops = [b.rect(0, 0, w, h, null, BOX_GRAY, 0.5)];
  var geometry = null;
  var legend = c.legend || [];
  function done() {
    return {svg: '<svg xmlns="http://www.w3.org/2000/svg" width="' + w + '" height="' + h +
                 '" viewBox="0 0 ' + w + " " + h + '"><rect width="' + w + '" height="' + h +
                 '" fill="#ffffff"/>' + ops.join("") + "</svg>", geometry: geometry};
  }
  /* chart_pdf.legend_left(): the first entry past the title, so the two never overlap. */
  function drawLegend(title) {
    var lx = Math.max(LEGEND_LEFT, Math.ceil(9 + TITLE_CHAR_W * title.length + LEGEND_GAP));
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
      drawLegend("");
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
    var label = xLabel(x, xMode);
    ops.push(b.text(xPx - label.length * 0.6 * 7 / 2, plotY0 - 14, 7, "Courier", label));
  });
  ops.push(b.text(plotX0 + plotW / 2 - 30, 4, 8, "Helvetica-Bold",
                  xMode === "width" ? t.width : t.floor));
  ops.push(b.dot(4, h - 7.5, 2.2, AXIS_GRAY));
  ops.push(b.text(9, h - 10, 8, "Helvetica-Bold", title));
  drawLegend(title);

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
      var text = pointLabel(c.decimals, p[1], s, p[0], true);
      ops.push(b.dot(cx, cy, 2.5, s.color, (xMode === "width" ? "" : "10^") +
                     xLabel(p[0], xMode) + ": " + pointLabel(c.decimals, p[1], s, p[0])));
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
