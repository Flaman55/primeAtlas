/* report_controls.js -- the page's controls as HTML: its filter, and the chart controls when
it has charts. */
/* The controls' HTML: the page's filter (one row per dimension, All runs), and when the page
has charts the chart controls (log scale, references, text size, x axis, All floors, each
chart's point choice, the gesture hint). state: {log, refs, scale, xMode, choices}. */
function controlsHtml(d, state) {
  var t = d.text, charts = d.pages.length > 0;
  var html = '<div class="pa-row">';
  if (charts) {
    html += '<label><input type="checkbox" data-toggle="log"' + (state.log ? " checked" : "") +
      "> " + escapeXml(t.log) + "</label>";
    if (d.refs_available) {
      html += '<label><input type="checkbox" data-toggle="refs"' +
        (state.refs ? " checked" : "") + "> " + escapeXml(t.refs) + "</label>";
    }
    html += "<label>" + escapeXml(t.text_size) + ' <select data-toggle="scale">' +
      TEXT_SCALES.map(function (k) {
        return '<option value="' + k + '"' + (k === state.scale ? " selected" : "") + ">" +
          Math.round(k * 100) + "%</option>";
      }).join("") + "</select></label>";
    html += "<label>" + escapeXml(t.x_axis) + ' <select data-toggle="xmode">' +
      ["floor", "width"].map(function (m) {
        return '<option value="' + m + '"' + (m === state.xMode ? " selected" : "") + ">" +
          escapeXml(t["x_" + m]) + "</option>";
      }).join("") + "</select></label>";
  }
  html += '<button type="button" data-act="runs">' + escapeXml(t.all_runs) + "</button>";
  if (charts) {
    html += '<button type="button" data-act="floors">' + escapeXml(t.all_floors) + "</button>";
  }
  html += "</div>";
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
  if (!charts) return html;
  var keys = [];
  d.pages.forEach(function (page) {
    page.charts.forEach(function (c) { if (keys.indexOf(c.key) < 0) keys.push(c.key); });
  });
  html += '<div class="pa-row"><span class="pa-dim-name">' + escapeXml(t.point) + "</span> ";
  keys.forEach(function (key) {
    html += "<label>" + escapeXml(t["chart_" + key]) + ' <select data-choice="' + key + '">' +
      ["last", "min", "max", "selected", "all"].map(function (c) {
        return '<option value="' + c + '"' + (c === (state.choices[key] || "last") ?
          " selected" : "") + ">" + escapeXml(t["point_" + c]) + "</option>";
      }).join("") + "</select></label>";
  });
  html += "</div>";
  html += '<p class="pa-hint">' + escapeXml(t.hint) + "</p>";
  return html;
}
