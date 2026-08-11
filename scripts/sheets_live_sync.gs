/**
 * MTR Portal — live Google Sheets -> database sync.
 *
 * Paste this into the spreadsheet's Apps Script editor (Extensions -> Apps
 * Script), fill in TOKEN below, then run `setup` ONCE and authorize it. After
 * that, every edit you make in any portal tab (people, inventory_items, ...)
 * saves straight to the database — no buttons, no "pull".
 *
 * How it works: an installable onEdit trigger fires on each edit, reads the
 * changed row, and POSTs it to the portal's /api/bulk/sheet-webhook endpoint,
 * which validates and upserts it through the same engine the in-app grid uses.
 * For a brand-new row (blank id) the portal returns the new id and the script
 * writes it back into the id cell, so re-editing that row updates instead of
 * creating a duplicate.
 *
 * Requirements / notes:
 *  - The tab name must match the portal table key (it does if you opened the
 *    sheet via the portal's "Open in Google Sheets" button).
 *  - Keep the header row and the `id` column.
 *  - A row that fails validation gets a red note on its id cell explaining why;
 *    fix the cell and it retries on the next edit.
 */

// ---- CONFIG -----------------------------------------------------------------
// Public portal URL (live sync only works against a public server, not localhost).
var PORTAL_URL = 'https://mindtechrobotics.duckdns.org';
// Must equal SHEETS_SYNC_TOKEN configured on the portal.
var TOKEN = 'PASTE_YOUR_SHEETS_SYNC_TOKEN_HERE';
// -----------------------------------------------------------------------------

/** Run this ONCE to install the trigger (Apps Script will ask you to authorize). */
function setup() {
  ScriptApp.getProjectTriggers().forEach(function (t) {
    if (t.getHandlerFunction() === 'onEditInstallable') ScriptApp.deleteTrigger(t);
  });
  ScriptApp.newTrigger('onEditInstallable')
    .forSpreadsheet(SpreadsheetApp.getActive())
    .onEdit()
    .create();
  SpreadsheetApp.getActive().toast('MTR live sync installed — edits now save to the portal.');
}

/** Installable onEdit handler — runs with full auth (can call the portal). */
function onEditInstallable(e) {
  try {
    var sheet = e.range.getSheet();
    var tab = sheet.getName();
    var headerRow = findHeaderRow_(sheet);
    if (!headerRow) return;

    var lastCol = sheet.getLastColumn();
    var header = sheet.getRange(headerRow, 1, 1, lastCol).getValues()[0]
      .map(function (h) { return String(h).trim(); });
    var idCol = header.indexOf('id');
    if (idCol < 0) return;

    for (var r = e.range.getRow(); r <= e.range.getLastRow(); r++) {
      if (r <= headerRow) continue; // banner / header rows
      var values = sheet.getRange(r, 1, 1, lastCol).getValues()[0];
      if (!values.some(function (v) { return String(v).trim() !== ''; })) continue; // blank row

      var row = {};
      for (var c = 0; c < header.length; c++) {
        if (header[c]) row[header[c]] = values[c] === null ? '' : String(values[c]);
      }

      var resp = post_({ tab: tab, row: row });
      if (resp && resp.ok && resp.id && !String(row['id']).trim()) {
        sheet.getRange(r, idCol + 1).setValue(resp.id); // write assigned id back
      }
      markRow_(sheet.getRange(r, idCol + 1), resp);
    }
  } catch (err) {
    console.error(err); // never throw from a trigger (avoids failure emails)
  }
}

function post_(payload) {
  var res = UrlFetchApp.fetch(PORTAL_URL + '/api/bulk/sheet-webhook', {
    method: 'post',
    contentType: 'application/json',
    headers: { 'X-Sheet-Token': TOKEN },
    payload: JSON.stringify(payload),
    muteHttpExceptions: true,
  });
  try {
    return JSON.parse(res.getContentText());
  } catch (e) {
    return { ok: false, errors: [{ message: 'HTTP ' + res.getResponseCode() }] };
  }
}

function markRow_(idCell, resp) {
  if (resp && resp.ok) {
    idCell.setNote('');
    idCell.setBackground(null);
  } else {
    var msg = (resp && resp.errors || []).map(function (e) { return e.message; }).join('; ');
    idCell.setNote('⚠ Not saved: ' + (msg || 'unknown error'));
    idCell.setBackground('#f4cccc');
  }
}

/** First of the top 3 rows containing an 'id' cell (skips the frozen banner). */
function findHeaderRow_(sheet) {
  var n = Math.min(3, sheet.getLastRow());
  if (n < 1) return 0;
  var grid = sheet.getRange(1, 1, n, sheet.getLastColumn()).getValues();
  for (var i = 0; i < grid.length; i++) {
    for (var j = 0; j < grid[i].length; j++) {
      if (String(grid[i][j]).trim() === 'id') return i + 1;
    }
  }
  return 0;
}
