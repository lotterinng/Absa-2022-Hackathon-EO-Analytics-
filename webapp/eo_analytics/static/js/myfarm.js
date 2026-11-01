/* My Farm Today: Crop Health (NDVI), Soil Moisture (NDMI) and Crop Yield. */
(async function () {
  const $ = id => document.getElementById(id);
  const TABS = {
    health: { index: 'ndvi', heading: 'Monitor the health status of your crops', label: 'Crop health (NDVI)' },
    moisture: { index: 'ndmi', heading: 'Measure the amount of moisture on the soil', label: 'Moisture (NDMI)' },
  };
  const CLASS_COLOURS = { poor: '#e53935', medium: '#fdd835', good: '#2e9e4f' };
  const RING_COLOURS = ['#3b7ddd', '#2e9e4f', '#e53935', '#fb8c00', '#8e24aa', '#00897b'];
  let tab = ['health', 'moisture', 'yield'].includes(window.EO_TAB) ? window.EO_TAB : 'health';
  let field = null, overlay = null, outline = null, ringsChart = null, yieldLoaded = false;
  let request = 0;

  const map = EO.baseMap('map');

  function setTab(t) {
    tab = t;
    document.querySelectorAll('.toggle button').forEach(b => {
      b.classList.toggle('on', b.dataset.tab === t);
      b.setAttribute('aria-selected', b.dataset.tab === t);
    });
    $('index-panel').classList.toggle('hidden', t === 'yield');
    $('yield-panel').classList.toggle('hidden', t !== 'yield');
    const p = new URLSearchParams(location.search); p.set('tab', t);
    history.replaceState(null, '', location.pathname + '?' + p.toString());
    if (t === 'yield') loadYield();
    else { setTimeout(() => map.invalidateSize(), 50); if (field) loadIndex(); }
  }
  document.querySelectorAll('.toggle button').forEach(b => b.addEventListener('click', () => setTab(b.dataset.tab)));

  function showField(f) {
    if (outline) map.removeLayer(outline);
    outline = L.geoJSON(f.geometry, { style: { color: '#fff', weight: 2, fill: false, dashArray: '4 4' } }).addTo(map);
    map.fitBounds(outline.getBounds(), { padding: [40, 40], maxZoom: 17 });
  }

  async function loadIndex(date) {
    const cfg = TABS[tab];
    const mine = ++request;
    $('index-heading').textContent = cfg.heading;
    EO.loading($('map-loading'), 'Fetching satellite images for this field…<br><span class="small muted">The first time can take up to a minute.</span>');
    $('rec').textContent = 'Loading…';
    try {
      const q = new URLSearchParams({ index: cfg.index });
      if (date) q.set('date', date);
      const data = await EO.api(`/api/fields/${field.id}/analysis?${q}`);
      if (mine !== request) return;
      render(data, cfg);
    } catch (err) {
      if (mine !== request) return;
      $('map-loading').innerHTML = `<div>⚠️ ${EO.escape(err.message)}</div><button class="btn sm" id="retry">Try again</button>`;
      $('retry').onclick = () => loadIndex(date);
      $('rec').textContent = 'Could not load the satellite analysis.';
    }
  }

  function render(data, cfg) {
    EO.sourceNote($('source'), data.source);
    if (overlay) { map.removeLayer(overlay); overlay = null; }
    const r = data.reading;
    // Date picker
    const sel = $('date');
    sel.innerHTML = data.dates.slice().reverse().map(d => `<option value="${d}">${EO.fmtDate(d)}</option>`).join('')
      || '<option>No clear images</option>';
    if (r) sel.value = r.date;
    $('rec').textContent = data.recommendation;
    if (!r) {
      $('map-loading').innerHTML = '<div>No cloud-free image of this field in the last 3 months yet.</div>';
      $('mean').textContent = '–';
      $('bars').innerHTML = ''; $('kv').innerHTML = ''; $('bars-label').textContent = '';
      $('map-date').classList.add('hidden');
      return;
    }
    $('map-loading').classList.add('hidden');
    overlay = L.imageOverlay(data.overlay.image, data.overlay.bounds, { opacity: 0.9 }).addTo(map);
    $('map-date').textContent = EO.fmtDate(r.date, { weekday: 'short', day: 'numeric', month: 'short', year: 'numeric' });
    $('map-date').classList.remove('hidden');
    $('legend-title').textContent = data.legend.label;
    [0, 1, 2].forEach(i => { $('lg' + i).textContent = data.legend.labels[i]; });

    const value = r[cfg.index];
    const classes = r[cfg.index + '_classes'];
    $('mean').textContent = value.toFixed(2);
    $('mean-label').textContent = `average ${cfg.label} for ${EO.escape(data.field.name)}`;
    $('bars').innerHTML = ['poor', 'medium', 'good'].map(k =>
      `<div style="width:${classes[k]}%;background:${CLASS_COLOURS[k]}" title="${k}: ${classes[k]}%"></div>`).join('');
    $('bars-label').innerHTML = `${data.legend.labels[0]} ${classes.poor}% · ${data.legend.labels[1]} ${classes.medium}% · ${data.legend.labels[2]} ${classes.good}%`;
    $('kv').innerHTML = [
      ['Image date', EO.fmtDate(r.date)],
      ['Field', `${EO.escape(data.field.name)} (${data.field.area_ha} ha)`],
      ['Crop', EO.escape(data.field.crop)],
      ['Cloud-free', Math.round(r.clear_fraction * 100) + '% of field'],
      ['Images (3 months)', data.dates.length],
    ].map(([k, v]) => `<div class="kv"><span class="muted">${k}</span><span>${v}</span></div>`).join('');
  }

  $('date').addEventListener('change', e => loadIndex(e.target.value));

  async function loadYield() {
    if (yieldLoaded) return;
    EO.loading($('yield-loading'), 'Estimating…');
    try {
      const data = await EO.api('/api/yield');
      yieldLoaded = true;
      $('yield-loading').classList.add('hidden');
      EO.sourceNote($('source'), data.source);
      $('yield-rec').textContent = data.recommendation;
      const fields = data.fields;
      const datasets = fields.map((f, i) => {
        const pct = f.status === 'ok' ? Math.min(f.current_pct, 100) : 0;
        const c = RING_COLOURS[i % RING_COLOURS.length];
        return { label: f.field, data: [pct, 100 - pct], backgroundColor: [c, c + '33'], borderWidth: 0, borderRadius: 8, weight: 1 };
      });
      if (ringsChart) ringsChart.destroy();
      ringsChart = new Chart($('rings'), {
        type: 'doughnut',
        data: { labels: ['Current yield', 'Gap to expected'], datasets },
        options: {
          cutout: '35%', rotation: 0, plugins: {
            legend: { display: false },
            tooltip: { callbacks: { label: ctx => `${ctx.dataset.label}: ${ctx.dataIndex === 0 ? ctx.raw + '% of expected' : ''}` } },
          },
        },
      });
      $('yield-cards').innerHTML = fields.map((f, i) => {
        const c = RING_COLOURS[i % RING_COLOURS.length];
        let body;
        if (f.status === 'ok') {
          body = `<div>Planted area: <b>${f.area_ha} ha</b></div>
            <div>Expected yield: <b>${f.expected_t_ha} t/ha</b> (${f.expected_total_t} t)</div>
            <div style="color:${c}">Current yield: <b>${f.current_pct}%</b> ≈ ${f.estimated_total_t} t</div>
            <div class="small muted">${f.growing ? 'Crop still growing – estimate may rise.' : 'Past peak greenness.'}</div>`;
        } else if (f.status === 'no-crop') {
          body = `<div>Planted area: <b>${f.area_ha} ha</b></div><div class="muted">No growing crop detected this season.</div>`;
        } else {
          body = `<div>Planted area: <b>${f.area_ha} ha</b></div><div class="muted">Not enough clear images yet.</div>`;
        }
        return `<div class="ycard" style="background:${c}14;border-top:4px solid ${c}">
          <div class="t"><b><i style="background:${c}"></i> ${EO.escape(f.field)}</b></div><div class="small muted">${EO.escape(f.crop)}</div>${body}</div>`;
      }).join('');
    } catch (err) {
      $('yield-loading').innerHTML = `<div>⚠️ ${EO.escape(err.message)}</div>`;
      $('yield-rec').textContent = 'Could not estimate yield right now.';
    }
  }

  setTab(tab);
  await EO.fieldSelect($('field'), f => {
    field = f;
    showField(f);
    if (tab !== 'yield') loadIndex();
  });
})();
