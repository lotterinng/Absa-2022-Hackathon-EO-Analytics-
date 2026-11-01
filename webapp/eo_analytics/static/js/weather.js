/* Weather: current conditions, 7-day forecast and 3-month rainfall. */
(async function () {
  const $ = id => document.getElementById(id);
  let chart = null;

  function tip(w) {
    const next3 = w.forecast.slice(1, 4).reduce((a, d) => a + (d.rain_mm || 0), 0);
    const hot = w.forecast.slice(0, 3).some(d => d.tmax >= 35);
    const et0 = w.forecast[0]?.et0_mm;
    if (next3 >= 15) return `About ${Math.round(next3)} mm of rain is expected in the next 3 days. Hold off irrigating and avoid spraying or fertilising just before heavy rain.`;
    if (hot) return 'Very hot days are coming (35 °C or more). Irrigate early in the morning or late afternoon to reduce evaporation, and check livestock water.';
    if (et0 && et0 >= 6) return `Crops are using a lot of water (about ${et0} mm per day). Check the Soil Moisture view and irrigate the driest parts first.`;
    if (next3 < 2) return 'Little or no rain is expected in the next 3 days. Plan irrigation for the driest parts of the field.';
    return 'Light rain is expected. A good time for planting or top-dressing if the soil is moist.';
  }

  async function load(fieldId) {
    $('desc').textContent = 'Loading…';
    try {
      const w = await EO.api('/api/weather' + (fieldId ? `?field=${fieldId}` : ''));
      EO.sourceNote($('source'), w.source, 'weather');
      const c = w.current, today = w.forecast[0] || {};
      $('place').innerHTML = EO.escape(w.place);
      $('desc').textContent = `${EO.fmtDate(c.time.slice(0, 10), { weekday: 'long', day: 'numeric', month: 'long' })} · ${w.lat.toFixed(3)}, ${w.lon.toFixed(3)}`;
      $('temp').textContent = `${Math.round(c.temperature)}°`;
      $('desc2').textContent = c.description;
      $('range').textContent = `High ${Math.round(today.tmax)}° · Low ${Math.round(today.tmin)}°`;
      $('wx-icon').innerHTML = EO.WX[c.icon] || EO.WX.cloud;
      $('wind').textContent = `${Math.round(c.wind_kmh)} km/h`;
      $('hum').textContent = `${Math.round(c.humidity)}%`;
      $('rain').textContent = `${(today.rain_mm ?? 0).toFixed(1)} mm`;
      $('et0').textContent = today.et0_mm != null ? `${today.et0_mm} mm` : '–';
      $('tip').textContent = tip(w);
      $('days').innerHTML = w.forecast.map((d, i) => `
        <div class="day"><b>${i === 0 ? 'Today' : EO.fmtDate(d.date, { weekday: 'short' })}</b>
        <span class="muted small">${EO.fmtDate(d.date, { day: 'numeric', month: 'short' })}</span>
        <div>${EO.WX[d.icon] || EO.WX.cloud}</div>
        <div><b style="display:inline">${Math.round(d.tmax)}°</b> <span class="muted">${Math.round(d.tmin)}°</span></div>
        <div class="small" style="color:#1e6fb5">${d.rain_mm ? d.rain_mm.toFixed(1) + ' mm' : '–'}${d.rain_chance != null ? ' · ' + d.rain_chance + '%' : ''}</div></div>`).join('');
      if (chart) chart.destroy();
      chart = new Chart($('rainchart'), {
        type: 'bar',
        data: { labels: w.past.map(d => EO.fmtDate(d.date, { day: 'numeric', month: 'short' })),
          datasets: [{ label: 'Rain (mm)', data: w.past.map(d => d.rain_mm), backgroundColor: '#3b7ddd', borderRadius: 3 }] },
        options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: false } },
          scales: { x: { ticks: { maxTicksLimit: 8 } }, y: { title: { display: true, text: 'mm' } } } },
      });
    } catch (err) {
      $('desc').textContent = err.message;
    }
  }

  const sel = $('field');
  if (sel) await EO.fieldSelect(sel, f => load(f.id));
  else load();
})();
