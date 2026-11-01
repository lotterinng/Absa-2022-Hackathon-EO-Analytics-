/* Shared helpers for all pages. */
const EO = (() => {
  const csrf = () => document.querySelector('meta[name="csrf-token"]')?.content || '';

  async function api(url, options = {}) {
    const opts = { headers: { 'Accept': 'application/json' }, ...options };
    if (opts.body && typeof opts.body !== 'string') {
      opts.body = JSON.stringify(opts.body);
      opts.headers['Content-Type'] = 'application/json';
    }
    if (opts.method && opts.method !== 'GET') opts.headers['X-CSRF-Token'] = csrf();
    let res;
    try {
      res = await fetch(url, opts);
    } catch (e) {
      throw new Error('No connection to the server. Check your internet and try again.');
    }
    let data = null;
    try { data = await res.json(); } catch (e) { /* not JSON */ }
    if (res.status === 401) { window.location = '/login?next=' + encodeURIComponent(location.pathname); }
    if (!res.ok) throw new Error((data && data.error) || `Request failed (${res.status})`);
    return data;
  }

  const store = {
    get(k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* private mode */ } },
  };

  let fieldsCache = null;
  async function fields() {
    if (!fieldsCache) fieldsCache = await api('/api/fields');
    return fieldsCache;
  }

  /** Fill a <select> with the farmer's fields and remember the choice. */
  async function fieldSelect(select, onChange) {
    const list = await fields();
    const params = new URLSearchParams(location.search);
    const wanted = params.get('field') || store.get('eo.field');
    select.innerHTML = list.map(f =>
      `<option value="${f.id}">${escape(f.name)} · ${escape(f.crop)} · ${f.area_ha} ha</option>`).join('');
    if (wanted && list.some(f => String(f.id) === String(wanted))) select.value = wanted;
    const fire = () => {
      store.set('eo.field', select.value);
      const p = new URLSearchParams(location.search); p.set('field', select.value);
      history.replaceState(null, '', location.pathname + '?' + p.toString());
      onChange(list.find(f => String(f.id) === select.value));
    };
    select.addEventListener('change', fire);
    if (list.length) fire();
    return list;
  }

  function sourceNote(el, source, kind = 'satellite') {
    if (!el) return;
    el.classList.remove('hidden', 'real');
    if (source) {
      el.classList.add('real');
      el.innerHTML = kind === 'satellite'
        ? 'Real Sentinel-2 satellite imagery (ESA Copernicus, via Microsoft Planetary Computer). Cloudy pixels are removed.'
        : 'Live weather from Open-Meteo.';
    } else {
      el.classList.add('hidden');
    }
  }

  /** Satellite + street base maps for Leaflet. */
  function baseMap(el, opts = {}) {
    const map = L.map(el, { zoomControl: true, ...opts });
    const sat = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
      maxZoom: 19, attribution: 'Imagery © Esri, Maxar, Earthstar Geographics',
    }).addTo(map);
    const osm = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 19, attribution: '© OpenStreetMap contributors',
    });
    L.control.layers({ 'Satellite': sat, 'Map': osm }, null, { position: 'topright' }).addTo(map);
    map.setView([-24.43, 26.02], 13);
    return map;
  }

  function escape(s) {
    return String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }

  function fmtDate(iso, opts = { day: 'numeric', month: 'short', year: 'numeric' }) {
    if (!iso) return '';
    return new Date(iso + (iso.length === 10 ? 'T12:00:00' : '')).toLocaleDateString(undefined, opts);
  }

  function loading(el, text) {
    el.innerHTML = `<div class="spinner"></div><div>${text}</div>`;
    el.classList.remove('hidden');
  }

  const WX = {
    sun: '<svg viewBox="0 0 64 64"><circle cx="32" cy="32" r="12" fill="#fbc02d"/><g stroke="#fbc02d" stroke-width="4" stroke-linecap="round"><path d="M32 6v8M32 50v8M6 32h8M50 32h8M13 13l6 6M45 45l6 6M13 51l6-6M45 19l6-6"/></g></svg>',
    partly: '<svg viewBox="0 0 64 64"><circle cx="24" cy="24" r="11" fill="#fbc02d"/><path d="M22 52a10 10 0 010-20 14 14 0 0127 3 9 9 0 011 17z" fill="#e3ecf7" stroke="#9fb3cc" stroke-width="2"/></svg>',
    cloud: '<svg viewBox="0 0 64 64"><path d="M18 50a12 12 0 010-24 16 16 0 0131 4 10 10 0 011 20z" fill="#dfe6ef" stroke="#9fb3cc" stroke-width="2"/></svg>',
    fog: '<svg viewBox="0 0 64 64"><path d="M18 40a12 12 0 010-24 16 16 0 0131 4 10 10 0 011 20z" fill="#dfe6ef"/><path d="M10 48h44M16 56h32" stroke="#9fb3cc" stroke-width="4" stroke-linecap="round"/></svg>',
    rain: '<svg viewBox="0 0 64 64"><path d="M18 42a12 12 0 010-24 16 16 0 0131 4 10 10 0 011 20z" fill="#29a8e0"/><path d="M22 48l-3 8M34 48l-3 8M46 48l-3 8" stroke="#1e6fb5" stroke-width="4" stroke-linecap="round"/></svg>',
    storm: '<svg viewBox="0 0 64 64"><path d="M18 40a12 12 0 010-24 16 16 0 0131 4 10 10 0 011 20z" fill="#64748b"/><path d="M34 40l-8 12h8l-4 10 12-14h-8l4-8z" fill="#fbc02d"/></svg>',
  };

  return { api, fields, fieldSelect, sourceNote, baseMap, escape, fmtDate, loading, store, WX };
})();
