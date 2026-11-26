/* report_page.js -- the page: Report builds the controls (report_controls.js), redraws the
charts, headings and tables from the data, and binds the chart gestures; shownCharts() picks
the charts to show, emptyColumns() the table columns to hide. Report runs only in a browser. */
var TEXT_SCALES = [1, 1.25, 1.5, 1.75, 2];
var DEFAULT_TEXT_SCALE = 1.5;
var DRAG_SLOP_PX = 4;

/* The columns of one table to hide: cells[r][j] is true where run r lacks a value in
column j, hidden[r] whether the filter drops run r; a column from `keys` on is hidden when
no shown run has a value in it (every one, with no run shown). */
function emptyColumns(cells, hidden, keys) {
  var width = cells.length ? cells[0].length : 0, out = [];
  for (var j = keys; j < width; j++) {
    var empty = true;
    for (var r = 0; r < cells.length && empty; r++) {
      if (!hidden[r] && !cells[r][j]) empty = false;
    }
    if (empty) out.push(j);
  }
  return out;
}

/* Per page, per chart: whether it shows, i.e. its series (legend-hidden lines included, so
a chart whose lines are all clicked off keeps its legend) set a point for the page's filter.
pages[i][j].series: the chart's Series. */
function shownCharts(pages) {
  return pages.map(function (charts) {
    return charts.map(function (c) {
      return c.series.some(function (s) { return s.points.length > 0; });
    });
  });
}

function Report(root, data) {
  var self = this;
  this.root = root;
  this.data = data;
  if (data.number_marks) numberMarks = data.number_marks;
  var selection = {};
  Object.keys(data.selection).forEach(function (k) { selection[k] = new Set(data.selection[k]); });
  this.selection = selection;
  this.view = data.view;
  this.xMode = data.x_mode || "floor";
  this.choices = {};
  Object.keys(data.choices || {}).forEach(function (k) { self.choices[k] = data.choices[k]; });
  this.xLevel = data.x_level;
  this.xBase = data.x_base;
  this.yViews = {};
  this.yLevels = {};
  this.scale = DEFAULT_TEXT_SCALE;
  this.log = data.log;
  this.refs = data.refs_on;
  this.hidden = {};
  data.pages.forEach(function (page, i) {
    page.charts.forEach(function (chart, j) {
      self.hidden[i + "/" + j] = new Set();
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
  var self = this;
  var box = this.root.querySelector(".pa-controls");
  box.innerHTML = controlsHtml(this.data, this);
  box.addEventListener("change", function (e) {
    var el = e.target;
    if (el.dataset.toggle === "log") self.log = el.checked;
    else if (el.dataset.toggle === "scale") self.scale = Number(el.value);
    else if (el.dataset.toggle === "refs") self.refs = el.checked;
    else if (el.dataset.toggle === "xmode") {
      self.xMode = el.value;
      self.resetView();
    } else if (el.dataset.choice) self.choices[el.dataset.choice] = el.value;
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

/* The chart's Series in benchmark.benchmark_series() order: by line, then by floor on the
width axis, named and shaded from data.width_lines there. */
Report.prototype.chartSeries = function (chart, kept, reduced) {
  var lines = this.data.lines, widthLines = this.data.width_lines || {};
  function order(key) { return key.split("/").map(Number); }
  var out = Object.keys(reduced).sort(function (a, b) {
    var ka = order(a), kb = order(b);
    return ka[0] - kb[0] || (ka[1] || 0) - (kb[1] || 0);
  }).map(function (key) {
    var line = lines[order(key)[0]], own = widthLines[key] || line;
    // benchmark_line_widths(): the widths of one x joined, "10^10/10^11" (all runs).
    var notes = {};
    reduced[key].forEach(function (p) {
      if (!p[2]) return;
      var found = notes[p[0]] ? notes[p[0]].split("/") : [];
      if (found.indexOf(p[2]) < 0) found.push(p[2]);
      notes[p[0]] = found.join("/");
    });
    return {name: own.name, tag: line.tag, color: own.color, dashed: false,
            points: reduced[key].map(function (p) { return [p[0], p[1]]; }), notes: notes};
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
      var reduced = reduce(chart.records, kept, self.xMode, self.choices[chart.key],
                           d.selected_run);
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
  var shown = shownCharts(pages);
  this.span = span;
  // A filter change keeps the zoom level; the view only moves back toward the new floors.
  if (this.view && span) this.view = clampView(this.view[0], this.view[1], span);
  var view = this.view;
  this.w = Math.round(d.width / this.scale);
  this.h = Math.round(d.height / this.scale);

  d.pages.forEach(function (page, i) {
    var mixed = {};
    if (self.xMode === "floor") {
      pages[i].forEach(function (c) {
        mixedFloors(c.reduced, view).forEach(function (f) { mixed[f] = true; });
      });
    }
    var mixedList = Object.keys(mixed).map(Number).sort(function (a, b) { return a - b; });
    var heading = (page.heading ? [page.heading] : [])
      .concat(mixedList.length ? [fill(t.mixed, {floors: mixedList.join(", ")})] : []);
    // A page with no chart shown hides its heading too (.pa-heading:empty).
    self.root.querySelector('.pa-heading[data-page="' + i + '"]').textContent =
      shown[i].indexOf(true) < 0 ? "" : heading.join("  |  ");
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
                                             pins: chart.pins, view: view, xMode: self.xMode,
                                             yView: self.yViews[i + "/" + j], text: t});
      var box = self.root.querySelector('.pa-chart[data-page="' + i + '"][data-chart="' + j + '"]');
      box.hidden = !shown[i][j];
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
  this.root.querySelectorAll("table[data-keys]").forEach(function (table) {
    var keys = Number(table.dataset.keys);
    var rows = Array.prototype.slice.call(table.querySelectorAll("tr[data-run]"));
    var cells = rows.map(function (tr) {
      return Array.prototype.map.call(tr.cells, function (td) {
        return td.classList.contains("pa-none");
      });
    });
    var empty = emptyColumns(cells, rows.map(function (tr) { return tr.hidden; }), keys);
    var gone = {};
    empty.forEach(function (j) { gone[j] = true; });
    Array.prototype.forEach.call(table.rows, function (tr) {
      Array.prototype.forEach.call(tr.cells, function (cell, j) { cell.hidden = !!gone[j]; });
    });
    var section = table.closest("details");
    var width = table.rows[0].cells.length;
    section.hidden = empty.length === width - keys;
    var link = self.root.querySelector('.pa-nav a[href="#' + section.id + '"]');
    if (link) link.hidden = section.hidden;
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
  // A link into a closed section opens it before the browser scrolls to the anchor.
  this.root.addEventListener("click", function (e) {
    var link = e.target.closest && e.target.closest('a[href^="#"]');
    var target = link && document.getElementById(link.getAttribute("href").slice(1));
    for (var el = target; el && el !== self.root; el = el.parentElement) {
      if (el.tagName === "DETAILS") el.open = true;
    }
  });
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
