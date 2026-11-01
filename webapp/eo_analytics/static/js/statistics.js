/* My Statistics: 3-month history of crop health, moisture and the yield outlook. */
(async function () {
  const $ = id => document.getElementById(id);
  let tab = ['health', 'moisture', 'yield'].includes(window.EO_TAB) ? window.EO_TAB : 'health';
  let data = null, trend = null, monthly = null, field = null;
  Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;
  Chart.defaults.color = '#687384';

  const EXPLAIN = {
    health: 'Each point is one cloud-free Sentinel-2 satellite pass over your field. The value is the field average NDVI: about 0.2 is bare soil, 0.5 is a moderate crop and 0.8 is a dense, healthy crop.',
    moisture: 'The blue line is NDMI from the satellite: it rises with water in the crop and soil surface. The green line is modelled soil moisture (3–9 cm deep, m³/m³) and the bars are daily rainfall for your field’s location.',
    yield: 'The green line is how green your crop got this season. The dashed line is the greenness a healthy crop of this type usually reaches. The closer the peak gets to the dashed line, the closer you are to your expected yield.',
  };

  function setTab(t) {
    tab = t;
    document.querySelectorAll('.toggle button').forEach(b => b.classList.toggle('on', b.dataset.tab === t));
    const p = new URLSearchParams(location.search); p.set('tab', t);
    history.replaceState(null, '', location.pathname + '?' + p.toString());
    $('explain-text').textContent = EXPLAIN[t];
    if (data) draw();
  }
  document.querySelectorAll('.toggle button').forEach(b => b.addEventListener('click', () => setTab(b.dataset.tab)));

  async function load() {
    EO.loading($('loading'), 'Collecting 3 months of satellite images…');
    $('analysis').innerHTML = '<li>Loading…</li>';
    try {
      data = await EO.api(`/api/fields/${field.id}/timeseries?months=3`);
      $('loading').classList.add('hidden');
      EO.sourceNote($('source'), data.source);
      draw();
    } catch (err) {
      $('loading').innerHTML = `<div>⚠️ ${EO.escape(err.message)}</div><button class="btn sm" id="retry">Try again</button>`;
      $('retry').onclick = load;
    }
  }

  function days() {
    // Daily axis covering the period, so satellite points and weather line up.
    const out = [];
    const end = new Date();
    for (let i = 92; i >= 0; i--) {
      const d = new Date(end); d.setDate(end.getDate() - i);
      out.push(d.toISOString().slice(0, 10));
    }
    return out;
  }

  function monthlyAverages(key) {
    const groups = {};
    data.readings.forEach(r => { if (r[key] != null) (groups[r.date.slice(0, 7)] ||= []).push(r[key]); });
    const months = Object.keys(groups).sort();
    return {
      labels: months.map(m => new Date(m + '-15').toLocaleDateString(undefined, { month: 'long' })),
      values: months.map(m => +(groups[m].reduce((a, b) => a + b, 0) / groups[m].length).toFixed(3)),
    };
  }

  function draw() {
    const labels = days();
    const byDate = Object.fromEntries(data.readings.map(r => [r.date, r]));
    const soil = Object.fromEntries((data.soil || []).map(s => [s.date, s]));
    const fmt = labels.map(d => EO.fmtDate(d, { day: 'numeric', month: 'short' }));
    if (trend) trend.destroy();
    if (monthly) monthly.destroy();
    const base = { responsive: true, maintainAspectRatio: false, interaction: { mode: 'index', intersect: false },
      plugins: { legend: { position: 'bottom', labels: { boxWidth: 12 } } } };

    let analysis;
    if (tab === 'health') {
      $('heading').textContent = 'Past 3 months health status of your crops';
      trend = new Chart($('trend'), {
        type: 'line',
        data: { labels: fmt, datasets: [{
          label: 'Crop health (NDVI)', data: labels.map(d => byDate[d]?.ndvi ?? null), spanGaps: true,
          borderColor: '#2e9e4f', backgroundColor: '#2e9e4f22', fill: true, tension: .3, pointRadius: 4,
        }] },
        options: { ...base, scales: { y: { min: 0, max: 1, title: { display: true, text: 'NDVI' } }, x: { ticks: { maxTicksLimit: 8 } } } },
      });
      analysis = data.analysis.ndvi;
      monthlyChart('ndvi', 'Crop health', '#43a047');
    } else if (tab === 'moisture') {
      $('heading').textContent = 'Past 3 months moisture of your field';
      const hasSoil = Object.keys(soil).length > 0;
      const ds = [{
        label: 'Satellite moisture (NDMI)', data: labels.map(d => byDate[d]?.ndmi ?? null), spanGaps: true,
        borderColor: '#3b7ddd', backgroundColor: '#3b7ddd', tension: .3, pointRadius: 4, yAxisID: 'y',
      }];
      if (hasSoil) {
        ds.push({ label: 'Soil moisture 3–9 cm (model)', data: labels.map(d => soil[d]?.soil_moisture ?? null),
          borderColor: '#2e9e4f', pointRadius: 0, borderWidth: 2, tension: .3, yAxisID: 'y2' });
        ds.push({ type: 'bar', label: 'Rain (mm)', data: labels.map(d => soil[d]?.rain_mm ?? null),
          backgroundColor: '#90caf988', yAxisID: 'y3' });
      }
      trend = new Chart($('trend'), {
        type: 'line', data: { labels: fmt, datasets: ds },
        options: { ...base, scales: {
          y: { min: -0.4, max: 0.6, title: { display: true, text: 'NDMI' } },
          y2: { display: hasSoil, position: 'right', min: 0, max: 0.5, grid: { drawOnChartArea: false }, title: { display: true, text: 'm³/m³' } },
          y3: { display: false, min: 0, max: 80 },
          x: { ticks: { maxTicksLimit: 8 } } } },
      });
      analysis = data.analysis.ndmi.slice();
      if (hasSoil) {
        const rain = (data.soil || []).reduce((a, s) => a + (s.rain_mm || 0), 0);
        analysis.push(`Total rainfall over the period: ${Math.round(rain)} mm.`);
      }
      monthlyChart('ndmi', 'Moisture', '#3b7ddd');
    } else {
      $('heading').textContent = 'Crop yield outlook for this season';
      const y = data.yield;
      const ref = y.reference_ndvi;
      trend = new Chart($('trend'), {
        type: 'line',
        data: { labels: fmt, datasets: [
          { label: 'Your crop (NDVI)', data: labels.map(d => byDate[d]?.ndvi ?? null), spanGaps: true,
            borderColor: '#2e9e4f', backgroundColor: '#2e9e4f22', fill: true, tension: .3, pointRadius: 4 },
          ...(ref ? [{ label: `Healthy ${y.crop} peak`, data: labels.map(() => ref), borderColor: '#e53935', borderDash: [6, 6], pointRadius: 0, borderWidth: 2 }] : []),
        ] },
        options: { ...base, scales: { y: { min: 0, max: 1 }, x: { ticks: { maxTicksLimit: 8 } } } },
      });
      if (y.status === 'ok') {
        analysis = [
          `${y.field} (${y.crop}, ${y.area_ha} ha) reached a peak NDVI of ${y.peak_ndvi} against ${y.reference_ndvi} for a healthy crop.`,
          `That points to about ${y.current_pct}% of your expected yield: roughly ${y.estimated_t_ha} t/ha or ${y.estimated_total_t} t in total (expected ${y.expected_total_t} t).`,
          y.growing ? 'The crop is still at or near its greenest, so the estimate can still go up.' : 'The crop has passed its greenest point; the estimate is unlikely to rise much now.',
          'This is an indicative estimate for planning, not a guarantee.',
        ];
      } else if (y.status === 'no-crop') {
        analysis = ['No actively growing crop was detected on this field in the period.', 'Set the planting date on My Fields once you plant so the estimate follows your season.'];
      } else {
        analysis = ['Not enough clear satellite images to estimate yield yet.'];
      }
      $('monthly-title').textContent = 'Expected vs estimated harvest (tonnes)';
      monthly = new Chart($('monthly'), {
        type: 'bar',
        data: { labels: ['Expected', 'Estimated'], datasets: [{ data: [y.expected_total_t, y.estimated_total_t ?? 0], backgroundColor: ['#90a4ae', '#43a047'], borderRadius: 6 }] },
        options: { responsive: true, maintainAspectRatio: false, indexAxis: 'y', plugins: { legend: { display: false } } },
      });
    }
    $('analysis').innerHTML = analysis.map(l => `<li>${EO.escape(l)}</li>`).join('');
  }

  function monthlyChart(key, label, colour) {
    const m = monthlyAverages(key);
    $('monthly-title').textContent = `Monthly average ${label.toLowerCase()}`;
    monthly = new Chart($('monthly'), {
      type: 'bar',
      data: { labels: m.labels, datasets: [{ label, data: m.values, backgroundColor: colour, borderRadius: 6, maxBarThickness: 60 }] },
      options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } },
        scales: { y: { beginAtZero: key === 'ndvi', suggestedMax: key === 'ndvi' ? 0.8 : 0.4 } } },
    });
  }

  $('csv').addEventListener('click', () => {
    if (!data) return;
    const rows = [['date', 'source', 'ndvi', 'ndmi', 'cloud_free_fraction', 'ndvi_poor_pct', 'ndvi_medium_pct', 'ndvi_good_pct']];
    data.readings.forEach(r => rows.push([r.date, r.source, r.ndvi, r.ndmi, r.clear_fraction,
      r.ndvi_classes?.poor, r.ndvi_classes?.medium, r.ndvi_classes?.good]));
    const blob = new Blob([rows.map(r => r.join(',')).join('\n')], { type: 'text/csv' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = `${data.field.name.replace(/\W+/g, '_')}_satellite_history.csv`;
    a.click();
  });

  setTab(tab);
  await EO.fieldSelect($('field'), f => { field = f; load(); });
})();
