/* report_format.js -- text of the report's charts: XML escaping, {key} templates, the app's
number notation (number_format.py), width and x-axis labels, a point's label. */
function escapeXml(text) {
  return String(text).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function fill(template, values) {
  return template.replace(/\{(\w+)\}/g, function (m, key) {
    return key in values ? String(values[key]) : m;
  });
}

// The app's number notation (report_html: number_marks), set by a Report from its data.
var numberMarks = {group: ",", mark: "."};

function formatNumber(decimals, value) {
  return value.toLocaleString("en-US", {minimumFractionDigits: decimals,
                                        maximumFractionDigits: decimals})
    .replace(/[,.]/g, function (c) { return c === "," ? numberMarks.group : numberMarks.mark; });
}

// number_format.compact(): from a million up 3 significant digits and an SI prefix.
var PREFIXES = ["M", "G", "T", "P", "E", "Z", "Y"];

function intDigits(x) { return String(Math.floor(x)).length; }

function formatCompact(decimals, value) {
  if (Math.abs(value) < 1e6) return formatNumber(decimals, value);
  for (var power = 0; power < PREFIXES.length; power++) {
    var scaled = Math.abs(value) / Math.pow(10, 6 + 3 * power);
    var digits = Math.max(0, 3 - intDigits(scaled));
    // Rounding up to the next power of ten (9.996 -> 10.00) costs one decimal place.
    if (intDigits(Number(scaled.toFixed(digits))) > intDigits(scaled)) digits = Math.max(0, digits - 1);
    if (Number(scaled.toFixed(digits)) < 1000 || power === PREFIXES.length - 1) {
      return (value < 0 ? "-" : "") + formatNumber(digits, scaled) + "\u00a0" + PREFIXES[power];
    }
  }
}

// line_names.width_label(): "10^11", "2x10^11", "1.5x10^10".
function widthLabel(numbers) {
  var exponent = String(numbers).length - 1;
  var mantissa = numbers / Math.pow(10, exponent);
  if (mantissa === 1) return "10^" + exponent;
  return String(parseFloat(mantissa.toPrecision(3))) + "x10^" + exponent;
}

// chart_points.x_label(): the floor, or the width of log10 x.
function xLabel(x, mode) {
  return mode === "width" ? widthLabel(Math.round(Math.pow(10, x))) : String(Math.round(x));
}

// chart_series.point_label(); short: the value in formatCompact().
function pointLabel(decimals, value, series, x, short) {
  var note = (series.notes || {})[x] || "";
  return (short ? formatCompact : formatNumber)(decimals, value) +
    (series.tag ? " [" + series.tag + "]" : "") + (note ? " @ " + note : "");
}
