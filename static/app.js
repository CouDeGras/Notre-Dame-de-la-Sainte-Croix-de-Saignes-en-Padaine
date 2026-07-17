'use strict';

const I18N = window.I18N || {};

// Display labels for decision codes, in the site's configured language
const DECISION_LABEL = {
  DRENCH:      I18N.decision_drench,
  WAIT:        I18N.decision_wait,
  FREEZE_HOLD: I18N.decision_freeze,
};

const ANCHOR_LABEL = { sunrise: I18N.anchor_sunrise, sunset: I18N.anchor_sunset };

// ── Countdown ─────────────────────────────────────────────────────────────────

let nextEpoch = null;
let nextQueryEpoch = null;

function pad(n) { return String(Math.floor(n)).padStart(2, '0'); }

function tickCountdown() {
  const el = document.getElementById('countdown');
  if (nextEpoch === null) { el.textContent = '—'; return; }
  const diff = nextEpoch - Date.now() / 1000;
  if (diff <= 0) { el.textContent = I18N.now; return; }
  const d = Math.floor(diff / 86400);
  const h = Math.floor((diff % 86400) / 3600);
  const m = Math.floor((diff % 3600) / 60);
  const s = Math.floor(diff % 60);
  el.textContent = d > 0
    ? `${d}d ${pad(h)}h ${pad(m)}m ${pad(s)}s`
    : `${pad(h)}:${pad(m)}:${pad(s)}`;
}

function tickQueryCountdown() {
  const el = document.getElementById('query-countdown');
  if (!el) return;
  if (nextQueryEpoch === null) { el.textContent = '—'; return; }
  const diff = nextQueryEpoch - Date.now() / 1000;
  if (diff <= 0) { el.textContent = I18N.now; return; }
  const h = Math.floor(diff / 3600);
  const m = Math.floor((diff % 3600) / 60);
  const s = Math.floor(diff % 60);
  el.textContent = `${pad(h)}:${pad(m)}:${pad(s)}`;
}

setInterval(tickCountdown, 1000);
setInterval(tickQueryCountdown, 1000);

function setRing(pct) {
  const label = document.getElementById('ring-pct');
  if (!label) return;
  label.textContent = Math.max(0, Math.min(100, pct)) + '%';
}

// ── Shared color helper (reads CSS vars so dark/light mode works) ─────────────

function getColors() {
  const cs = getComputedStyle(document.documentElement);
  return {
    fg:    cs.getPropertyValue('--b').trim() || '#fff',
    bg:    cs.getPropertyValue('--w').trim() || '#000',
    irrig: cs.getPropertyValue('--irrig').trim() || '#1b7a1b',
  };
}

// Continuous (fractional) column index for an arbitrary epoch, found by
// linear interpolation between the two bracketing row epochs. Columns are
// evenly spaced in the grid regardless of the real time gap between rows, so
// this is the only way to place a mark at its true time rather than
// snapping to the nearest column. Returns null when the epoch falls outside
// the plotted range entirely -- callers must not draw a mark for it, since
// clamping to column 0 / the last column would misrepresent an event that's
// actually before or after the chart's timescale as happening right at its
// edge.
function colForEpoch(epochs, epoch) {
  if (!epochs.length) return null;
  if (epoch < epochs[0]) return null;
  const last = epochs.length - 1;
  if (epoch > epochs[last]) return null;
  for (let i = 0; i < last; i++) {
    const a = epochs[i], b = epochs[i + 1];
    if (epoch <= b) {
      const t = b > a ? (epoch - a) / (b - a) : 0;
      return i + t;
    }
  }
  return last;
}

// ── Shared column layout (used by both chart types for identical x-axis) ──────

function colLayout(parentElem, nCols) {
  const pw   = parentElem ? (parentElem.clientWidth || 400) : 400;
  const ML   = 36;
  const CELL = Math.max(4, Math.min(8, Math.floor((pw - ML) / nCols)));
  const GAP  = Math.max(1, Math.floor(CELL * 0.15));
  const colW = CELL + GAP;
  return { ML, CELL, GAP, colW, cssW: ML + nCols * colW };
}

// ── Grid chart (precipitation, single series) ─────────────────────────────────
//
// GitHub-contribution style: filled black cell = value; outlined white = empty.
// Cell size adapts to fill the container width.

function drawGrid(canvasId, values, opts) {
  const canvas = document.getElementById(canvasId);
  if (!canvas) return;
  const dpr   = Math.min(2, window.devicePixelRatio || 1);
  const nCols = values.length;
  const nRows = Math.max(1, Math.round((opts.maxY - opts.minY) / opts.stepY));
  // One extra always-empty row above the highest data row, purely so the
  // axis-max tick has a real row edge to land on (the same way every other
  // tick points at the boundary of the row it labels) instead of floating
  // in the padding above a grid that stops one row short.
  const totalRows = nRows + 1;

  const MB = opts.hideXLabels ? 0 : 18;
  const { ML, CELL, GAP, colW, cssW } = colLayout(canvas.parentElement, nCols);
  const rowH = CELL + 1;
  // Single label row above the bars, shared by day-boundary marks and
  // irrigation percent marks. They're laid out together with collision
  // avoidance (see the merged label pass below) rather than each owning a
  // fixed slot, so a same-row layout doesn't require a second band.
  const TOP_PAD = 3;
  const ROW_H   = 11;
  const BOT_PAD = 3;
  const LABEL_ROW_Y = TOP_PAD;
  const MT = TOP_PAD + ROW_H + BOT_PAD;
  const cssH = totalRows * rowH + MB + MT;
  const MR = opts.overlay ? 32 : 0; // room for the right-hand temperature axis
  const canvasW = cssW + MR;

  canvas.width  = canvasW * dpr;
  canvas.height = cssH * dpr;
  canvas.style.width  = canvasW + 'px';
  canvas.style.height = cssH + 'px';

  const ctx = canvas.getContext('2d');
  ctx.scale(dpr, dpr);
  const { fg, bg, irrig } = getColors();
  ctx.fillStyle = bg;
  ctx.fillRect(0, 0, canvasW, cssH);

  // Y labels + ticks
  ctx.font = '8px monospace';
  ctx.fillStyle = fg;
  ctx.textAlign = 'right';
  ctx.textBaseline = 'middle';
  const yEvery = Math.max(1, Math.ceil(nRows / 7));
  for (let r = 0; r <= nRows; r += yEvery) {
    const val = opts.minY + r * opts.stepY;
    // Points at the row's bottom edge (an extension of the square's
    // undermost side), not the square's vertical middle -- that edge is the
    // actual value boundary between "this row filled" and "this row not".
    const y   = cssH - MB - r * rowH;
    ctx.fillText(val.toFixed(opts.decimals ?? 0) + (opts.unit || ''), ML - 4, y);
    ctx.strokeStyle = fg;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(ML - 2, Math.round(y) + 0.5);
    ctx.lineTo(ML,     Math.round(y) + 0.5);
    ctx.stroke();
  }

  // Cells
  //
  // Same quantized-square grid as always (each row is its own CELLxCELL
  // block with a 1px gap, so bars still read as stacked unit cells, not a
  // smooth bar). The only change: columns flagged `interpolated` carry a
  // `block` id identifying which single coarse Yr.no reading they were
  // split from (set by the backend, not guessed from the rendered value —
  // guessing merged/failed to merge runs unpredictably). Columns sharing a
  // block id widen their row-cells to span the whole run.
  for (let c = 0; c < nCols; c++) {
    const v = values[c];
    if (v == null || isNaN(v)) continue;
    const coarse = !!(opts.interpolated && opts.interpolated[c]);
    const filled = Math.max(0, Math.min(nRows, Math.round((v - opts.minY) / opts.stepY)));
    const blockId = opts.block && opts.block[c];

    let end = c;
    let w = CELL;
    if (coarse && blockId != null) {
      while (
        end + 1 < nCols && opts.interpolated[end + 1] &&
        values[end + 1] != null && !isNaN(values[end + 1]) &&
        opts.block && opts.block[end + 1] === blockId
      ) {
        end++;
      }
      w = (end - c + 1) * colW - GAP;
    }

    const cx = ML + c * colW;

    for (let r = 0; r < totalRows; r++) {
      const cy = cssH - MB - (r + 1) * rowH + 1;
      if (r < filled) {
        ctx.fillStyle = fg;
        ctx.fillRect(cx, cy, w, CELL);
      } else {
        ctx.fillStyle = bg;
        ctx.fillRect(cx, cy, w, CELL);
        ctx.strokeStyle = fg;
        ctx.lineWidth = 0.5;
        ctx.strokeRect(cx + 0.5, cy + 0.5, w - 1, CELL - 1);
      }
    }
    c = end;
  }

  // Day marks: dotted vertical line at each day change. Thicker than the
  // line chart's version — at 0.5px it got lost against the dense cell grid.
  const labelCandidates = []; // { x, text, color } — laid out below as one row
  if (opts.dateMarks && opts.dateMarks.length) {
    const botY = cssH - MB;
    ctx.strokeStyle = fg;
    ctx.lineWidth   = 1.5;
    ctx.setLineDash([5, 2]);
    for (const mark of opts.dateMarks) {
      if (!mark.isBoundary) continue;
      const x = Math.round(ML + mark.col * colW) + 0.5;
      ctx.beginPath(); ctx.moveTo(x, MT); ctx.lineTo(x, botY); ctx.stroke();
    }
    ctx.setLineDash([]);

    for (const mark of opts.dateMarks) {
      labelCandidates.push({ x: ML + mark.col * colW + 2, text: mark.label, color: fg });
    }
  }

  // Scheduled irrigation marks: dark green dotted vertical line at the
  // (fractional, interpolated) column position of each upcoming event — a
  // bit heavier than the day-boundary marks so a specific scheduled event
  // outweighs a generic day change. Its percent label joins the same row
  // as the date labels below.
  if (opts.eventMarks && opts.eventMarks.length && opts.epochs && opts.epochs.length && opts.epochs.every(Number.isFinite)) {
    const botY = cssH - MB;
    ctx.strokeStyle = irrig;
    ctx.lineWidth   = 2.5;
    ctx.setLineDash([5, 2]);
    for (const mark of opts.eventMarks) {
      const col = colForEpoch(opts.epochs, mark.epoch);
      if (col == null) continue;
      const x = Math.round(ML + col * colW + CELL / 2) + 0.5;
      ctx.beginPath(); ctx.moveTo(x, MT); ctx.lineTo(x, botY); ctx.stroke();
      labelCandidates.push({ x: x + 2, text: `${mark.percent}%`, color: irrig });
    }
    ctx.setLineDash([]);
  }

  // Merged label row: date marks and irrigation percent marks share one
  // horizontal line. Laid out left-to-right in x order, pushing each label
  // past the previous one's right edge (+ a small gap) whenever their
  // natural positions would collide — e.g. a day boundary falling right on
  // top of a late-night irrigation event — instead of letting them overlap.
  if (labelCandidates.length) {
    ctx.font = '8px monospace';
    ctx.textAlign = 'left';
    ctx.textBaseline = 'top';
    const GAP_PX = 3;
    labelCandidates.sort((a, b) => a.x - b.x);
    let cursor = -Infinity;
    for (const item of labelCandidates) {
      const w = ctx.measureText(item.text).width;
      let drawX = Math.max(item.x, cursor);
      drawX = Math.min(drawX, canvasW - 2 - w); // keep the last label on-canvas
      item.drawX = drawX;
      cursor = drawX + w + GAP_PX;
    }
    for (const item of labelCandidates) {
      ctx.fillStyle = item.color;
      ctx.fillText(item.text, item.drawX, LABEL_ROW_Y);
    }
  }

  if (!opts.hideXLabels) {
    ctx.textAlign    = 'center';
    ctx.textBaseline = 'alphabetic';
    ctx.fillStyle    = fg;
    const xEvery = Math.max(1, Math.ceil(nCols / 9));
    for (let c = 0; c < nCols; c += xEvery) {
      ctx.fillText(opts.labels[c] || '', ML + c * colW + CELL / 2, cssH - 2);
    }
    if ((nCols - 1) % xEvery !== 0) {
      ctx.fillText(opts.labels[nCols - 1] || '', ML + (nCols - 1) * colW + CELL / 2, cssH - 2);
    }
  }

  // Overlay: right-axis line series (temperature), drawn on top of the bars.
  if (opts.overlay) {
    const ov = opts.overlay;
    const cH   = cssH - MT - MB; // same vertical span as the bar area
    const toYOv = v => MT + cH - ((v - ov.minY) / (ov.maxY - ov.minY)) * cH;
    const axisX = Math.round(cssW) + 0.5;

    // Right axis border + ticks + labels
    ctx.strokeStyle = fg;
    ctx.lineWidth   = 1;
    ctx.beginPath(); ctx.moveTo(axisX, MT); ctx.lineTo(axisX, MT + cH); ctx.stroke();

    ctx.font = '8px monospace';
    ctx.textAlign = 'left';
    ctx.textBaseline = 'middle';
    const OV_STEPS = 4;
    for (let i = 0; i <= OV_STEPS; i++) {
      const val = ov.minY + i * (ov.maxY - ov.minY) / OV_STEPS;
      const y   = Math.round(toYOv(val)) + 0.5;
      ctx.strokeStyle = fg;
      ctx.lineWidth   = 1;
      ctx.beginPath(); ctx.moveTo(axisX, y); ctx.lineTo(axisX + 3, y); ctx.stroke();
      ctx.fillStyle = fg;
      ctx.fillText(val.toFixed(0) + (ov.unit || ''), axisX + 5, y);
    }

    // Temperature line + × markers, matching the OWM series style used
    // previously in the standalone temperature chart.
    //
    // The line should render bg-colored (black) wherever it crosses an
    // actual filled/data bar, and plain fg everywhere else. Canvas blend
    // modes (difference/destination-in) react to any fg pixel underneath,
    // including empty-cell border outlines, and their anti-aliased edges
    // don't line up cleanly with those borders, producing visible notches.
    // Simpler and exact: pick each small piece's color directly by comparing
    // its position to that column's bar height -- the same numbers used to
    // draw the bars -- and stroke it plainly. No compositing, so it can't
    // interact with border pixels at all.
    const toXOv = c => ML + c * colW + CELL / 2;
    const barTopY = c => {
      const v = values[c];
      if (v == null || isNaN(v)) return cssH - MB;
      const filled = Math.max(0, Math.min(nRows, Math.round((v - opts.minY) / opts.stepY)));
      return filled <= 0 ? (cssH - MB) : (cssH - MB - filled * rowH + 1);
    };
    const colAt = x => Math.max(0, Math.min(nCols - 1, Math.round((x - ML - CELL / 2) / colW)));

    ctx.lineWidth = 1.5;
    ctx.setLineDash([]);
    const SUBSTEPS = 6; // per inter-column segment, for smooth color transitions
    let prevX = null, prevY = null;
    for (let c = 0; c < nCols; c++) {
      const v = ov.values[c];
      if (v == null || isNaN(v)) { prevX = null; continue; }
      const x = toXOv(c), y = toYOv(v);
      if (prevX != null) {
        for (let s = 0; s < SUBSTEPS; s++) {
          const t0 = s / SUBSTEPS, t1 = (s + 1) / SUBSTEPS;
          const x0 = prevX + (x - prevX) * t0, y0 = prevY + (y - prevY) * t0;
          const x1 = prevX + (x - prevX) * t1, y1 = prevY + (y - prevY) * t1;
          const midX = (x0 + x1) / 2, midY = (y0 + y1) / 2;
          ctx.strokeStyle = midY >= barTopY(colAt(midX)) ? bg : fg;
          ctx.beginPath();
          ctx.moveTo(x0, y0); ctx.lineTo(x1, y1);
          ctx.stroke();
        }
      }
      prevX = x; prevY = y;
    }

    const a = 3;
    for (let c = 0; c < nCols; c++) {
      const v = ov.values[c];
      if (v == null || isNaN(v)) continue;
      const x = toXOv(c), y = toYOv(v);
      ctx.strokeStyle = y >= barTopY(c) ? bg : fg;
      ctx.beginPath();
      ctx.moveTo(x - a, y - a); ctx.lineTo(x + a, y + a);
      ctx.moveTo(x + a, y - a); ctx.lineTo(x - a, y + a);
      ctx.stroke();
    }
  }
}

// ── Render helpers ────────────────────────────────────────────────────────────

function rv(v, d = 1) { return v == null ? '—' : Number(v).toFixed(d); }

function renderHeader(data) {
  document.getElementById('demo-badge').classList.toggle('hidden', !data._demo);
  document.getElementById('city-name').textContent = (data.location || {}).city || '';
}

function renderCountdown(schedule) {
  const events = (schedule.json_payload || {}).events || [];
  const active = events.filter(ev => (ev.percent || 0) > 0);

  if (active.length) {
    nextEpoch = active[0].epoch;
    setRing(active[0].percent ?? 0);
    tickCountdown();
    document.getElementById('event-list').innerHTML = active.map(ev => {
      const anchor = (ev.solar_anchor || '').toLowerCase();
      const label  = ANCHOR_LABEL[anchor] || anchor.toUpperCase();
      const time   = String(ev.iso_local || '').replace('T', ' ').slice(0, 16);
      return `<div class="event-row">
        <span class="ev-seq">#${ev.sequence}</span>
        <span class="ev-anchor">${label}</span>
        <span class="ev-time">${time}</span>
        <span class="ev-pct">${ev.percent}%</span>
        <span class="ev-dur">${ev.pump_seconds}s</span>
      </div>`;
    }).join('');
  } else {
    nextEpoch = null;
    setRing(0);
    tickCountdown();
    document.getElementById('event-list').innerHTML = '';
  }
}

function formatObsAge(ageMinutes) {
  if (ageMinutes == null) return '—';
  if (ageMinutes < 1) return I18N.just_now || '—';
  if (ageMinutes < 60) return `${Math.round(ageMinutes)}m`;
  const h = Math.floor(ageMinutes / 60);
  const m = Math.round(ageMinutes % 60);
  return `${h}h ${pad(m)}m`;
}

// Metric tiles show live airport ground truth (the latest METAR observation)
// rather than an average across the Yr.no/OWM/Open-Meteo forecast sources --
// those remain forecast-only inputs to the irrigation decision.
function renderMetrics(current, schedule, ensemble) {
  const cur   = current || {};
  const tMin  = schedule.tmin24_c;
  const tMax  = schedule.tmax24_c;

  document.getElementById('m-temp').textContent       = cur.temp_c   != null ? `${rv(cur.temp_c, 0)}°` : '—';
  document.getElementById('m-temp-range').textContent = `${rv(tMin)}° / ${rv(tMax)}°`;
  document.getElementById('m-rh').textContent         = cur.rh_pct   != null ? `${rv(cur.rh_pct, 0)}%` : '—';
  document.getElementById('m-rh-sub').textContent     = cur.age_minutes != null ? formatObsAge(cur.age_minutes) : (I18N.metric_rh_sub || '—');
  document.getElementById('m-wind').textContent       = cur.wind_mps != null ? rv(cur.wind_mps) : '—';
  document.getElementById('m-vpd').textContent        = cur.vpd_kpa != null ? rv(cur.vpd_kpa, 2) : '—';
  document.getElementById('m-demand').textContent     = (ensemble.demand_mm || {}).d0_24 != null
    ? `${rv(ensemble.demand_mm.d0_24)} mm` : '—';
}

function hLabel(row) {
  return parseInt(row.local_time.slice(-5), 10) + 'h';
}

// One mark per calendar day present in rows: { col, label, isBoundary }.
// col 0 always gets a mark (the first day, no vertical line needed since the
// axis border already marks the left edge); every day change after that adds
// a mark with isBoundary = true (dotted vertical line + date label).
// local_time is "MM-DD HH:MM"; first 5 chars are the date part.
function dateMarks(rows) {
  const fmt = s => s.slice(0, 5).replace('-', '/');
  const marks = [{ col: 0, label: fmt(rows[0].local_time), isBoundary: false }];
  for (let i = 1; i < rows.length; i++) {
    if (rows[i].local_time.slice(0, 5) !== rows[i - 1].local_time.slice(0, 5)) {
      marks.push({ col: i, label: fmt(rows[i].local_time), isBoundary: true });
    }
  }
  return marks;
}

const RAIN_STEP_MM = 2;
const RAIN_MIN_MAX_MM = 20; // floor for the axis top, so a dry spell doesn't flatten the grid

// Shared across all three precipitation panels so they're the same physical
// size and a given cell always means the same mm value on every chart.
function rainYAxis(...seriesList) {
  const maxRaw = Math.max(...seriesList.flat(), 0.01);
  const maxY   = Math.max(RAIN_MIN_MAX_MM, Math.ceil(maxRaw / RAIN_STEP_MM) * RAIN_STEP_MM);
  return { minY: 0, maxY, stepY: RAIN_STEP_MM, decimals: 0, unit: 'mm' };
}

// Shared min/max so all three temperature overlays plot on the same
// right-axis scale and stay visually comparable across panels.
function tempAxis(...seriesList) {
  const all = seriesList.flat().filter(v => v != null);
  if (!all.length) return null;
  return {
    minY: Math.floor(Math.min(...all) / 2) * 2,
    maxY: Math.ceil( Math.max(...all) / 2) * 2,
    unit: '°',
  };
}

function renderRainCharts(rows, eventMarks) {
  const labels       = rows.map(hLabel);
  const epochs       = rows.map(r => r.epoch);
  const owmRain      = rows.map(r => r.owm_rain_3h_mm ?? 0);
  const yrRain       = rows.map(r => r.yr_rain_3h_mm  ?? 0);
  const omRain       = rows.map(r => r.om_rain_3h_mm  ?? 0);
  const yrInterp     = rows.map(r => r.yr_rain_interpolated ?? false);
  const yrBlock      = rows.map(r => r.yr_rain_block ?? null);
  const owmTemps     = rows.map(r => r.owm_temp_c);
  const yrTemps      = rows.map(r => r.yr_temp_c);
  const omTemps      = rows.map(r => r.om_temp_c);

  const dm = dateMarks(rows);
  const ta = tempAxis(owmTemps, yrTemps, omTemps);
  const ra = rainYAxis(owmRain, yrRain, omRain);

  drawGrid('chart-rain-owm', owmRain, {
    labels, ...ra, hideXLabels: false, dateMarks: dm, epochs, eventMarks,
    overlay: ta && { values: owmTemps, ...ta },
  });
  drawGrid('chart-rain-yr', yrRain, {
    labels, ...ra, hideXLabels: false, interpolated: yrInterp, block: yrBlock, dateMarks: dm, epochs, eventMarks,
    overlay: ta && { values: yrTemps, ...ta },
  });
  drawGrid('chart-rain-om', omRain, {
    labels, ...ra, hideXLabels: false, dateMarks: dm, epochs, eventMarks,
    overlay: ta && { values: omTemps, ...ta },
  });
}

function agoLabel(epoch) {
  if (epoch == null) return '—';
  const diff = Date.now() / 1000 - epoch;
  if (diff < 0) return I18N.just_now;
  if (diff < 60) return `${Math.floor(diff)}s`;
  if (diff < 3600) return `${Math.floor(diff / 60)}m`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h`;
  return `${Math.floor(diff / 86400)}d`;
}

function renderPumpNodes(devices) {
  const tbody = document.getElementById('acks-body');
  if (!tbody) return;
  const ids = Object.keys(devices || {});
  if (!ids.length) {
    tbody.innerHTML = `<tr><td colspan="6" class="tbl-empty">${I18N.no_acks}</td></tr>`;
    return;
  }
  tbody.innerHTML = ids
    .sort((a, b) => (devices[b].received_at_epoch || 0) - (devices[a].received_at_epoch || 0))
    .map(id => {
      const ack = devices[id] || {};
      const code = ack.ack_decision || '—';
      const label = DECISION_LABEL[code] || code;
      const executed = ack.executed
        ? `<span class="dec-pill dec-pill-inv">${I18N.yes}</span>`
        : `<span class="dec-pill">${I18N.no}</span>`;
      const armed = ack.armed ? I18N.yes : I18N.no;
      return `<tr>
        <td><strong>${id}</strong></td>
        <td>${agoLabel(ack.received_at_epoch)}</td>
        <td>${executed}</td>
        <td>${ack.executed_pump_s ?? 0}s</td>
        <td><span class="dec-pill">${label}</span></td>
        <td>${armed}</td>
      </tr>`;
    }).join('');
}

function renderHistory(rows) {
  const tbody = document.getElementById('history-body');
  if (!rows || !rows.length) {
    tbody.innerHTML = `<tr><td colspan="7" class="tbl-empty">${I18N.no_history}</td></tr>`;
    return;
  }
  tbody.innerHTML = [...rows].reverse().map(row => {
    const code = row.decision_code || 'WAIT';
    const inv  = code === 'DRENCH';
    const pill = inv ? 'dec-pill dec-pill-inv' : 'dec-pill';
    const label = DECISION_LABEL[code] || code;
    return `<tr>
      <td><strong>${row.local_date || '—'}</strong></td>
      <td><span class="${pill}">${label}</span></td>
      <td>${row.commanded_percent ?? 0}%</td>
      <td>${row.commanded_pump_seconds ?? 0}s</td>
      <td>${Number(row.forecast_precip_local_day_mm || 0).toFixed(1)}</td>
      <td>${Number(row.forecast_tmin24_c || 0).toFixed(1)}°</td>
      <td>${Number(row.forecast_tmax24_c || 0).toFixed(1)}°</td>
    </tr>`;
  }).join('');
}

// ── Main refresh ─────────────────────────────────────────────────────────────

let lastAckDevices = {};

async function refresh() {
  try {
    const [statusRes, histRes, acksRes] = await Promise.all([
      fetch('/api/status'),
      fetch('/api/history?n=14'),
      fetch('/api/acks'),
    ]);
    const data = await statusRes.json();
    const hist = await histRes.json();
    const acks = await acksRes.json();

    renderHeader(data);
    nextQueryEpoch = data.next_run_epoch ?? null;

    const irrig = data.irrigation  || {};
    const sched = irrig.schedule   || {};
    const ens   = data.ensemble    || {};
    const current = data.current  || null;
    const frows = (data.comparison || {}).rows || [];

    renderCountdown(sched);
    renderMetrics(current, sched, ens);

    if (frows.length) {
      const events = (sched.json_payload || {}).events || [];
      const eventMarks = events
        .filter(ev => (ev.percent || 0) > 0)
        .slice(0, 2)
        .map(ev => ({ epoch: ev.epoch, percent: ev.percent }));
      renderRainCharts(frows, eventMarks);
    }

    renderHistory(hist.rows || []);

    lastAckDevices = acks.devices || {};
    renderPumpNodes(lastAckDevices);

  } catch (err) {
    console.error('Error refreshing:', err);
  }
}

// Defer first paint until layout is settled
requestAnimationFrame(() => { refresh(); });
setInterval(refresh, 60_000);
setInterval(() => renderPumpNodes(lastAckDevices), 15_000);

// ── Manual refresh button ────────────────────────────────────────────────────
// Triggers a live re-fetch of all four weather sources (Yr.no, OWM,
// Open-Meteo, METAR) via POST /api/refresh -- not just a re-read of the
// already-cached dashboard data like the passive 60s poll does. The backend
// deliberately never recomputes the irrigation decision or publishes to MQTT
// on this path (see main.py's _api_refresh docstring), so clicking this can't
// command a pump.
(() => {
  const btn = document.getElementById('refresh-btn');
  if (!btn) return;
  btn.addEventListener('click', async () => {
    if (btn.classList.contains('spinning')) return;
    btn.classList.add('spinning');
    btn.disabled = true;
    try {
      const res = await fetch('/api/refresh', { method: 'POST' });
      if (!res.ok) console.error('Manual refresh failed:', await res.text());
    } catch (err) {
      console.error('Error triggering manual refresh:', err);
    } finally {
      await refresh();
      btn.classList.remove('spinning');
      btn.disabled = false;
    }
  });
})();

// ── Config modal ─────────────────────────────────────────────────────────────
// Loads/saves station, broker, root_topic, lang via /api/config. station and
// lang are always resolved to a real value by the backend (DEFAULT_STATION /
// DEFAULT_LANG if unset); an empty saved broker/root_topic just leaves the
// input blank -- the backend falls back to its own hardcoded default there.
(() => {
  const overlay = document.getElementById('config-overlay');
  const openBtn = document.getElementById('config-btn');
  const closeBtn = document.getElementById('config-close');
  const cancelBtn = document.getElementById('config-cancel');
  const saveBtn = document.getElementById('config-save');
  if (!overlay || !openBtn) return;

  const fields = {
    station: document.getElementById('cfg-station'),
    broker: document.getElementById('cfg-broker'),
    root_topic: document.getElementById('cfg-topic'),
    lang: document.getElementById('cfg-lang'),
  };

  // Airport codes are always 4 uppercase letters -- normalize as the user
  // types so what they see matches what the backend will validate/store.
  fields.station.addEventListener('input', () => {
    const start = fields.station.selectionStart;
    fields.station.value = fields.station.value.toUpperCase().replace(/[^A-Z]/g, '').slice(0, 4);
    fields.station.setSelectionRange(start, start);
  });

  const open = () => overlay.classList.remove('hidden');
  const close = () => overlay.classList.add('hidden');

  openBtn.addEventListener('click', async () => {
    open();
    try {
      const res = await fetch('/api/config');
      const cfg = await res.json();
      for (const key of Object.keys(fields)) {
        fields[key].value = cfg[key] || '';
      }
    } catch (err) {
      console.error('Error loading config:', err);
    }
  });
  closeBtn.addEventListener('click', close);
  cancelBtn.addEventListener('click', close);
  overlay.addEventListener('click', (e) => { if (e.target === overlay) close(); });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && !overlay.classList.contains('hidden')) close();
  });

  saveBtn.addEventListener('click', async () => {
    const label = saveBtn.textContent;
    saveBtn.textContent = I18N.saving;
    saveBtn.disabled = true;
    try {
      const body = {};
      for (const key of Object.keys(fields)) body[key] = fields[key].value.trim();
      const res = await fetch('/api/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      if (!res.ok) throw new Error(await res.text());
      // Static, server-rendered text only reflects the new language after a
      // full reload -- the modal fields themselves already show it live.
      if (fields.lang.value !== document.documentElement.lang) {
        window.location.reload();
        return;
      }
      close();
    } catch (err) {
      console.error('Error saving config:', err);
      saveBtn.textContent = I18N.error;
      setTimeout(() => { saveBtn.textContent = label; }, 1500);
    } finally {
      saveBtn.disabled = false;
      if (saveBtn.textContent === I18N.saving) saveBtn.textContent = label;
    }
  });
})();
