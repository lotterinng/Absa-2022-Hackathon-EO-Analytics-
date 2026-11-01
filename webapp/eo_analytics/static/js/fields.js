/* My Fields: draw, edit and delete field boundaries. */
(async function () {
  const map = EO.baseMap('map');
  const group = L.featureGroup().addTo(map);
  const $ = id => document.getElementById(id);
  const form = $('field-form'), card = $('form-card');
  let fields = [];
  let layers = {};          // field id -> polygon layer
  let current = null;       // { id|null, layer }

  const style = { color: '#ffd400', weight: 2, fillOpacity: 0.08 };
  const selStyle = { color: '#00e5ff', weight: 3, fillOpacity: 0.15 };

  const drawControl = new L.Control.Draw({
    position: 'topleft',
    draw: {
      polygon: { allowIntersection: false, showArea: true, metric: ['ha'], shapeOptions: selStyle },
      polyline: false, rectangle: false, circle: false, marker: false, circlemarker: false,
    },
    edit: false,
  });
  map.addControl(drawControl);

  function toGeoJSON(layer) { return layer.toGeoJSON().geometry; }
  function areaHa(layer) {
    const latlngs = layer.getLatLngs()[0];
    return (L.GeometryUtil.geodesicArea(latlngs) / 10000).toFixed(2);
  }

  function renderList() {
    const el = $('list');
    if (!fields.length) {
      el.innerHTML = '<div class="empty">No fields yet. Draw one on the map.</div>';
      return;
    }
    el.innerHTML = fields.map(f => `
      <div class="row ${current && current.id === f.id ? 'selected' : ''}" data-id="${f.id}">
        <div class="name"><b>${EO.escape(f.name)}</b><br>
          <span class="small muted">${EO.escape(f.crop)} · ${f.area_ha} ha${f.planting_date ? ' · planted ' + EO.fmtDate(f.planting_date) : ''}</span></div>
        <button class="btn ghost sm" data-edit="${f.id}">Edit</button>
        <a class="btn sm" href="/my-farm?field=${f.id}">View</a>
      </div>`).join('');
    el.querySelectorAll('[data-edit]').forEach(b => b.addEventListener('click', () => select(+b.dataset.edit)));
  }

  function drawFields() {
    group.clearLayers();
    layers = {};
    fields.forEach(f => {
      const layer = L.geoJSON(f.geometry, { style }).getLayers()[0];
      layer.bindTooltip(EO.escape(f.name), { permanent: true, direction: 'center', className: 'field-label' });
      layer.on('click', () => select(f.id));
      group.addLayer(layer);
      layers[f.id] = layer;
    });
  }

  function stopEditing() {
    if (!current) return;
    if (current.layer.editing) current.layer.editing.disable();
    if (current.id === null) map.removeLayer(current.layer);
    else current.layer.setStyle(style);
    current = null;
  }

  function openForm(field) {
    card.classList.remove('hidden');
    $('form-title').textContent = field ? 'Edit field' : 'New field';
    $('f-name').value = field ? field.name : '';
    $('f-crop').value = field ? field.crop : 'Maize';
    $('f-yield').value = field && field.expected_yield_t_ha ? field.expected_yield_t_ha : '';
    $('f-plant').value = field && field.planting_date ? field.planting_date : '';
    $('delete').classList.toggle('hidden', !field);
    $('form-error').classList.add('hidden');
    $('f-area').textContent = areaHa(current.layer);
    card.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    $('f-name').focus({ preventScroll: true });
  }

  function select(id) {
    stopEditing();
    const field = fields.find(f => f.id === id);
    const layer = layers[id];
    current = { id, layer };
    layer.setStyle(selStyle);
    layer.editing.enable();
    layer.on('edit', () => { $('f-area').textContent = areaHa(layer); });
    map.fitBounds(layer.getBounds(), { maxZoom: 17, padding: [30, 30] });
    openForm(field);
    renderList();
  }

  map.on(L.Draw.Event.CREATED, e => {
    stopEditing();
    const layer = e.layer;
    layer.addTo(map);
    layer.editing.enable();
    layer.on('edit', () => { $('f-area').textContent = areaHa(layer); });
    current = { id: null, layer };
    openForm(null);
    renderList();
  });

  form.addEventListener('submit', async e => {
    e.preventDefault();
    if (!current) return;
    const body = {
      name: $('f-name').value,
      crop: $('f-crop').value,
      expected_yield_t_ha: $('f-yield').value || null,
      planting_date: $('f-plant').value || null,
      geometry: toGeoJSON(current.layer),
    };
    $('save').disabled = true;
    try {
      const saved = current.id === null
        ? await EO.api('/api/fields', { method: 'POST', body })
        : await EO.api(`/api/fields/${current.id}`, { method: 'PUT', body });
      stopEditing();
      card.classList.add('hidden');
      await reload();
      flash(`Saved "${saved.name}" (${saved.area_ha} ha). Open My Farm to see its satellite analysis.`);
    } catch (err) {
      $('form-error').textContent = err.message;
      $('form-error').classList.remove('hidden');
    } finally {
      $('save').disabled = false;
    }
  });

  $('cancel').addEventListener('click', () => {
    stopEditing(); card.classList.add('hidden'); drawFields(); renderList();
  });

  $('delete').addEventListener('click', async () => {
    if (!current || current.id === null) return;
    const f = fields.find(x => x.id === current.id);
    if (!window.confirm(`Delete "${f.name}"? Its satellite history will be removed too.`)) return;
    try {
      await EO.api(`/api/fields/${current.id}`, { method: 'DELETE' });
      current = null;
      card.classList.add('hidden');
      await reload();
    } catch (err) { alertError(err); }
  });

  $('search').addEventListener('submit', async e => {
    e.preventDefault();
    const q = e.target.q.value.trim();
    if (!q) return;
    try {
      const res = await fetch('https://nominatim.openstreetmap.org/search?format=json&limit=1&countrycodes=bw,za,na,zw,zm&q=' + encodeURIComponent(q));
      const hits = await res.json();
      if (hits.length) map.setView([+hits[0].lat, +hits[0].lon], 15);
      else flash('Place not found. Try a nearby village or town.', 'error');
    } catch (err) { flash('Place search is unavailable right now. Zoom the map by hand instead.', 'error'); }
  });

  $('locate').addEventListener('click', () => {
    if (!navigator.geolocation) return flash('Your browser cannot share its location.', 'error');
    navigator.geolocation.getCurrentPosition(
      p => map.setView([p.coords.latitude, p.coords.longitude], 16),
      () => flash('Location permission was refused.', 'error'));
  });

  function flash(msg, kind = 'success') {
    const div = document.createElement('div');
    div.className = 'flash ' + kind;
    div.textContent = msg;
    document.querySelector('main').prepend(div);
    setTimeout(() => div.remove(), 7000);
  }
  function alertError(err) { flash(err.message, 'error'); }

  async function reload() {
    EO.store.set('eo.fields', '');
    fields = await EO.api('/api/fields');
    drawFields();
    renderList();
    if (fields.length && group.getLayers().length) map.fitBounds(group.getBounds(), { maxZoom: 16, padding: [30, 30] });
  }

  await reload();
})();
