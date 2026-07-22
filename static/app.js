'use strict';

const I18N = window.I18N || {};

// ── Shared header rendering (demo badge) ────────────────────────────────────
// Called from each page's own /api/status poll (weather.js, irrigation.js).
// The station/city name itself is shown by weather.js's location widget, not
// the header -- the header used to show it too, but that absolutely
// positioned span sat right on top of the page-nav links and ate their
// clicks.
function renderHeader(data) {
  document.getElementById('demo-badge').classList.toggle('hidden', !data._demo);
}

// ── Manual refresh button ────────────────────────────────────────────────────
// Triggers a live re-fetch of all four weather sources (Yr.no, OWM,
// Open-Meteo, METAR) via POST /api/refresh -- not just a re-read of the
// already-cached dashboard data like each page's passive 60s poll does. The
// backend deliberately never recomputes the irrigation decision or publishes
// to MQTT on this path (see dashboard/services.py's api_refresh docstring),
// so clicking this can't command a pump. The button lives in the shared
// header, so it just calls whichever page's own refresh() registered itself
// as window.dashboardRefresh.
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
      if (typeof window.dashboardRefresh === 'function') await window.dashboardRefresh();
      btn.classList.remove('spinning');
      btn.disabled = false;
    }
  });
})();

// ── Config modal ─────────────────────────────────────────────────────────────
// Loads/saves station, broker, root_topic, lang via /api/config. All four
// are always resolved to a real value by the backend (its own hardcoded
// defaults if unset/invalid), so the fields never show blank -- they show
// whatever's actually in effect, whether that's a saved override or the
// default.
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
