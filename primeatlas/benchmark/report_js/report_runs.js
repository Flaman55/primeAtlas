/* report_runs.js -- the runs a chart compares: the page filter's kept runs and clicks
(chart_filter.py), and the reduction to one point per line and x (chart_points.py). */
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

/* chart_points.pick(): the record of a group (in log order) for `choice`; ties to the later
record, the selected run's record in its own group. */
function pick(group, choice, selectedRun) {
  if (choice === "selected") {
    var own = group.filter(function (r) { return r[0] === selectedRun; });
    return own.length ? own[0] : group[group.length - 1];
  }
  if (choice !== "min" && choice !== "max") return group[group.length - 1];
  var best = group[0][3];
  group.forEach(function (r) {
    best = choice === "min" ? Math.min(best, r[3]) : Math.max(best, r[3]);
  });
  var ties = group.filter(function (r) { return r[3] === best; });
  return ties[ties.length - 1];
}

/* {line key: [[x, value, width]] ascending}: one record per line and x among the kept runs
(records are in log order), chosen by pick(), every record of a group for "all". Floor axis (mode "floor", the default): key
the line index, x the floor; width axis: key "line index/floor", x log10 of the width, runs
without a width left out. */
function reduce(records, kept, mode, choice, selectedRun) {
  var width = mode === "width";
  var groups = {};
  records.forEach(function (r) {
    if (!kept[r[0]]) return;
    if (width && (r[5] === null || r[5] === undefined)) return;
    var key = width ? r[1] + "/" + r[2] : String(r[1]);
    var x = width ? r[5] : r[2];
    var line = (groups[key] = groups[key] || {});
    (line[x] = line[x] || []).push(r);
  });
  var out = {};
  Object.keys(groups).forEach(function (key) {
    var points = [];
    Object.keys(groups[key]).map(Number).sort(function (a, b) { return a - b; })
      .forEach(function (x) {
        var group = groups[key][x];
        (choice === "all" ? group : [pick(group, choice || "last", selectedRun)])
          .forEach(function (r) { points.push([width ? r[5] : r[2], r[3], r[4]]); });
      });
    out[key] = points;
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
