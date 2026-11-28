// Paletas visuales para escenarios climáticos en la escena SVG
const EFECTOS_VISUALES = {
  NORMAL: {
    sky: '#f4ebd8', sun: 0.85, clouds: 0.12, rain: 0, wind: 0, hail: 0, lightning: false, frost: 0,
    desc: 'ΔT 0.0 °C | Rad ×1.00 | factor_retardo=1.00 (Despejado)'
  },
  SOL_INTENSO: {
    sky: '#f4ebd8', sun: 1, clouds: 0, rain: 0, wind: 0, hail: 0, lightning: false, frost: 0,
    desc: 'ΔT +8.0 °C | Rad ×1.25 | factor_retardo=0.90 (Sol pleno)'
  },
  NUBLADO: {
    sky: '#dce5e8', sun: 0.15, clouds: 0.95, rain: 0, wind: 0, hail: 0, lightning: false, frost: 0,
    desc: 'ΔT -2.0 °C | Rad ×0.40 | factor_retardo=1.05 (Nublado)'
  },
  LLUVIA: {
    sky: '#cfdbe0', sun: 0, clouds: 1, rain: 0.7, wind: 0.15, hail: 0, lightning: false, frost: 0,
    desc: 'ΔT -3.5 °C | Rad ×0.25 | factor_retardo=1.30 (Lluvia constante)'
  },
  TORMENTA_ELECTRICA: {
    sky: '#32414a', sun: 0, clouds: 1, rain: 1, wind: 0.75, hail: 0, lightning: true, frost: 0,
    desc: 'ΔT -5.0 °C | Rad ×0.12 | factor_retardo=1.45 (Tormenta eléctrica)'
  },
  TORMENTA: {
    sky: '#495b66', sun: 0, clouds: 1, rain: 0.9, wind: 0.65, hail: 0, lightning: false, frost: 0,
    desc: 'ΔT -4.0 °C | Rad ×0.20 | factor_retardo=1.35 (Tormenta severa)'
  },
  FRIO_INTENSO: {
    sky: '#d5e6f2', sun: 0.75, clouds: 0.1, rain: 0, wind: 0.15, hail: 0, lightning: false, frost: 0.95,
    desc: 'ΔT -12.0 °C | Rad ×0.90 | factor_retardo=1.20 (Riesgo de helada)'
  },
  VENTISCA: {
    sky: '#b8cad6', sun: 0.08, clouds: 1, rain: 0.25, wind: 1, hail: 0, lightning: false, frost: 0.85,
    desc: 'ΔT -6.0 °C | Rampa viento +68 km/h | Riesgo estructural por ráfagas'
  },
  GRANIZO: {
    sky: '#506470', sun: 0, clouds: 1, rain: 0.45, wind: 0.65, hail: 1, lightning: false, frost: 0.55,
    desc: 'ΔT -5.5 °C | Rad ×0.18 | +38 km/h (Precipitación de granizo)'
  }
};

const TIMER_LABELS = {
  desplegar_media_sombra: 'Persistencia Media Sombra (Desplegar)',
  recoger_media_sombra: 'Persistencia Media Sombra (Recoger)',
  encender_ventilacion: 'Persistencia Ventilación (Encender)',
  apagar_ventilacion: 'Persistencia Ventilación (Apagar)'
};

const state = {
  clima: 'NORMAL',
  modo: 'AUTOMATICO',
  cultivo: '—',
  pausado: false,
  timeSpeed: 10,
  horaSim: '12:00:00',
  esNoche: false,
  vientoExterno: 0,
  vientoManual: null,
  // Estados de actuadores (0% a 100% para la animación suave del SVG)
  roof: 0,
  targetRoof: 0,
  sideOpen: 0,
  targetSideOpen: 0,
  fan: 0,
  targetFan: 0,
  fanAngle: 0,
  // Mecanismos booleanos
  techoPrendido: false,
  cortinasPrendido: false,
  ventiladoresPrendido: false,
  // Series de datos para gráficos
  historyLen: 32,
  tempIntSeries: [],
  tempExtSeries: [],
  radIntSeries: [],
  radExtSeries: [],
  vientoSeries: [],
  parametros: {}
};

function escapeHtml(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

// -------------------------------------------------------------
// RENDERIZADO DE GRÁFICOS SVG CON UMBRALES
// -------------------------------------------------------------
function renderDualLineChart(svgId, seriesInt, seriesExt, defaultMin, defaultMax, colorInt, colorExt, thresholds = []) {
  const svg = document.getElementById(svgId);
  if (!svg || !seriesInt || seriesInt.length < 2) return;

  const hasExt = Array.isArray(seriesExt) && seriesExt.length === seriesInt.length;
  const validThresholds = (thresholds || []).filter(t => t && Number.isFinite(Number(t.value)));

  const W = 420, H = 150;
  const padL = 38, padR = 14, padT = 14, padB = 20;
  const plotW = W - padL - padR;
  const plotH = H - padT - padB;

  const allVals = [
    ...seriesInt,
    ...(hasExt ? seriesExt : []),
    ...validThresholds.map(t => Number(t.value))
  ];
  let minY = Math.min(...allVals);
  let maxY = Math.max(...allVals);

  if (minY === maxY) {
    minY -= 2;
    maxY += 2;
  }
  const margin = (maxY - minY) * 0.14;
  minY = Math.floor(minY - margin);
  maxY = Math.ceil(maxY + margin);

  const xOf = idx => padL + (idx / (seriesInt.length - 1)) * plotW;
  const yOf = val => {
    const clamped = Math.max(minY, Math.min(maxY, val));
    return padT + plotH - ((clamped - minY) / (maxY - minY)) * plotH;
  };

  const makePath = arr => arr.map((v, i) => `${i === 0 ? 'M' : 'L'} ${xOf(i).toFixed(1)} ${yOf(v).toFixed(1)}`).join(' ');
  const areaPath = `${makePath(seriesInt)} L ${xOf(seriesInt.length - 1).toFixed(1)} ${(padT + plotH).toFixed(1)} L ${padL} ${(padT + plotH).toFixed(1)} Z`;

  const ticks = [minY, Math.round((minY + maxY) / 2), maxY];
  const gridHtml = ticks.map(t => {
    const y = yOf(t).toFixed(1);
    return `
      <line x1="${padL}" y1="${y}" x2="${W - padR}" y2="${y}" stroke="#cbc5b8" stroke-width="1" stroke-dasharray="3 3" />
      <text x="${padL - 6}" y="${Number(y) + 3.5}" text-anchor="end" font-family="ui-monospace, monospace" font-size="9.5" fill="#5c635c">${t}</text>
    `;
  }).join('');

  const thresholdsHtml = validThresholds.map(t => {
    const val = Number(t.value);
    const y = yOf(val);
    const labelY = Math.max(padT + 9, y - 3);
    const labelText = escapeHtml(t.label ?? String(val));
    return `
      <line x1="${padL}" y1="${y.toFixed(1)}" x2="${W - padR}" y2="${y.toFixed(1)}" stroke="${t.color}" stroke-width="1.3" stroke-dasharray="4 3" opacity="0.88" />
      <text x="${W - padR - 2}" y="${labelY.toFixed(1)}" text-anchor="end" font-family="ui-monospace, monospace" font-size="8.8" font-weight="700" fill="${t.color}">${labelText}</text>
    `;
  }).join('');

  const lastIdx = seriesInt.length - 1;
  const extLineHtml = hasExt
    ? `<path d="${makePath(seriesExt)}" fill="none" stroke="${colorExt}" stroke-width="2" stroke-dasharray="5 4" />
       <circle cx="${xOf(lastIdx).toFixed(1)}" cy="${yOf(seriesExt[lastIdx]).toFixed(1)}" r="3.5" fill="${colorExt}" />`
    : '';

  svg.innerHTML = `
    ${gridHtml}
    <path d="${areaPath}" fill="${colorInt}" opacity="0.10" />
    ${thresholdsHtml}
    ${extLineHtml}
    <path d="${makePath(seriesInt)}" fill="none" stroke="${colorInt}" stroke-width="2.5" stroke-linecap="round" />
    <circle cx="${xOf(lastIdx).toFixed(1)}" cy="${yOf(seriesInt[lastIdx]).toFixed(1)}" r="4" fill="${colorInt}" />
  `;
}

// -------------------------------------------------------------
// COMUNICACIÓN CON DJANGO (API REST)
// -------------------------------------------------------------
async function fetchEstado() {
  try {
    const res = await fetch('/simulador/api/estado/');
    if (!res.ok) throw new Error('Error al consultar estado');
    const data = await res.json();
    actualizarInterfaz(data);
  } catch (err) {
    console.warn('Conexión con backend:', err);
  }
}

function resetSeriesLocales() {
  state.tempIntSeries = [];
  state.tempExtSeries = [];
  state.radIntSeries = [];
  state.radExtSeries = [];
  state.vientoSeries = [];
}

function actualizarInterfaz(data) {
  state.horaSim = data.hora;
  state.esNoche = Boolean(data.es_noche);
  state.pausado = Boolean(data.pausado);
  state.timeSpeed = data.velocidad;
  state.clima = data.clima;
  state.modo = data.modo || 'AUTOMATICO';
  state.cultivo = data.cultivo || 'Sin cultivo';
  state.vientoExterno = Number(data.viento_externo ?? 0);
  state.vientoManual = data.viento_manual ?? null;
  state.parametros = data.parametros || {};

  // Actualizar métricas textuales
  document.getElementById('val-temp-int').textContent = `${Number(data.temp_interna).toFixed(1)} °C`;
  document.getElementById('val-temp-ext').textContent = `${Number(data.temp_externa).toFixed(1)} °C`;
  document.getElementById('val-rad-int').textContent = `${Math.round(data.rad_interna)} W/m²`;
  document.getElementById('val-rad-ext').textContent = `${Math.round(data.rad_externa)} W/m²`;
  document.getElementById('val-viento-ext').textContent = `${state.vientoExterno.toFixed(1)} km/h`;

  const vientoOrigen = document.getElementById('val-viento-origen');
  if (vientoOrigen) {
    vientoOrigen.textContent = state.vientoManual !== null ? 'Manual' : 'Auto Clima';
  }

  // Actualizar pills de encabezado
  document.getElementById('tel-cultivo').textContent = `Cultivo: ${state.cultivo}`;
  const pillModo = document.getElementById('tel-modo');
  pillModo.textContent = state.modo;
  pillModo.className = `pill pill-modo ${state.modo === 'MANUAL' ? 'is-manual' : 'is-auto'}`;

  document.getElementById('tel-clock').textContent = `Sim: ${data.hora} (x${data.velocidad})`;
  document.getElementById('tel-clima').textContent = data.clima;
  document.getElementById('tel-retardo').textContent = `Retardo: ${Number(data.factor_retardo).toFixed(2)}x (t90: ${data.t90_min}m)`;
  document.getElementById('sel-clima').value = data.clima;

  const rngSpeed = document.getElementById('rng-speed');
  if (rngSpeed && document.activeElement !== rngSpeed) {
    rngSpeed.value = Math.round(data.velocidad);
    document.getElementById('lbl-speed').textContent = `x${data.velocidad}`;
  }

  // Sincronizar control de viento exterior
  const rngViento = document.getElementById('rng-viento');
  if (rngViento && document.activeElement !== rngViento) {
    rngViento.value = Math.min(120, Math.max(0, Math.round(state.vientoExterno)));
    document.getElementById('lbl-viento').textContent = `${state.vientoExterno.toFixed(1)} km/h`;
  }
  const btnVientoAuto = document.getElementById('btn-viento-auto');
  if (btnVientoAuto) {
    btnVientoAuto.classList.toggle('btn-auto-active', state.vientoManual === null);
  }

  // Actualizar descripción de efecto de clima
  const vis = EFECTOS_VISUALES[data.clima] || EFECTOS_VISUALES.NORMAL;
  document.getElementById('clima-desc').innerHTML =
    `<strong>EfectoClima:</strong> ${vis.desc} | <em>t90</em> actual: <strong>${data.t90_min} min</strong>`;

  // Temporizador de persistencia activo
  actualizarTimerPersistencia(data.evaluador);

  // Actuadores: si están prendidos, el target en el SVG es 100%
  state.techoPrendido = Boolean(data.techo_prendido);
  state.cortinasPrendido = Boolean(data.cortinas_prendido);
  state.ventiladoresPrendido = Boolean(data.ventiladores_prendido);

  state.targetRoof = state.techoPrendido ? 100 : 0;
  state.targetSideOpen = state.cortinasPrendido ? 100 : 0;
  state.targetFan = state.ventiladoresPrendido ? 100 : 0;

  actualizarControlesUI();
  actualizarAtmosphereVisual(data.clima, data.es_noche, state.vientoExterno);

  // Actualizar series de los gráficos con datos reales
  if (state.tempIntSeries.length === 0 && data.historial && data.historial.length > 0) {
    data.historial.forEach(h => {
      state.tempIntSeries.push(h.temp_int);
      state.tempExtSeries.push(h.temp_ext);
      state.radIntSeries.push(h.rad_int);
      state.radExtSeries.push(h.rad_ext);
      state.vientoSeries.push(Number(h.viento ?? 0));
    });
  } else {
    state.tempIntSeries.push(data.temp_interna);
    state.tempExtSeries.push(data.temp_externa);
    state.radIntSeries.push(data.rad_interna);
    state.radExtSeries.push(data.rad_externa);
    state.vientoSeries.push(state.vientoExterno);
  }

  while (state.tempIntSeries.length > state.historyLen) {
    state.tempIntSeries.shift();
    state.tempExtSeries.shift();
    state.radIntSeries.shift();
    state.radExtSeries.shift();
    state.vientoSeries.shift();
  }

  const p = state.parametros;
  renderDualLineChart(
    'chart-temp',
    state.tempIntSeries,
    state.tempExtSeries,
    5,
    36,
    '#a85438',
    '#8f5822',
    [
      { value: p.temp_max, label: `Máx ${p.temp_max}°C`, color: '#c62828' },
      { value: p.temp_min, label: `Mín ${p.temp_min}°C`, color: '#1565c0' }
    ]
  );

  renderDualLineChart(
    'chart-rad',
    state.radIntSeries,
    state.radExtSeries,
    0,
    1050,
    '#366948',
    '#4b6b78',
    [
      { value: p.rad_max, label: `Máx ${p.rad_max}`, color: '#c62828' },
      { value: p.rad_min, label: `Mín ${p.rad_min}`, color: '#2e7d32' }
    ]
  );

  renderDualLineChart(
    'chart-viento',
    state.vientoSeries,
    null,
    0,
    80,
    '#4b6b78',
    '#4b6b78',
    [
      { value: p.viento_max, label: `Máx ${p.viento_max} km/h`, color: '#c62828' }
    ]
  );

  // Botón de pausa
  const btnPause = document.getElementById('btn-pause');
  btnPause.textContent = state.pausado ? '▶ Reanudar' : '⏸ Pausar';

  // Alertas reales del backend
  renderAlerts(data.alertas || []);
}

function actualizarTimerPersistencia(evaluador) {
  const el = document.getElementById('persistence-timer');
  if (!el) return;

  const timers = evaluador && evaluador.timers ? evaluador.timers : null;
  if (!timers) {
    el.style.display = 'none';
    el.textContent = '';
    return;
  }

  const keys = [
    'desplegar_media_sombra',
    'recoger_media_sombra',
    'encender_ventilacion',
    'apagar_ventilacion'
  ];
  const reqS = evaluador.persistencia_requerida_s || 300;
  const activos = [];

  keys.forEach(k => {
    const t = timers[k];
    if (t && t.activo) {
      const label = TIMER_LABELS[k] || k;
      activos.push(`⏳ ${label}: ${t.transcurrido_s}s / ${reqS}s`);
    }
  });

  if (activos.length > 0) {
    el.textContent = activos.join(' · ');
    el.style.display = 'inline-flex';
  } else {
    el.style.display = 'none';
    el.textContent = '';
  }
}

function actualizarControlesUI() {
  // 0. Modo de Operación
  const bModo = document.getElementById('badge-modo');
  const bModoAuto = document.getElementById('btn-modo-auto');
  const bModoManual = document.getElementById('btn-modo-manual');
  const subModo = document.getElementById('sub-modo');
  const esManual = state.modo === 'MANUAL';

  if (bModo && bModoAuto && bModoManual && subModo) {
    if (esManual) {
      bModo.className = 'mech-badge manual';
      bModo.textContent = 'MANUAL';
      bModoAuto.className = 'seg-btn';
      bModoManual.className = 'seg-btn active-off';
      subModo.textContent = 'Control manual directo del operador';
    } else {
      bModo.className = 'mech-badge on';
      bModo.textContent = 'AUTO';
      bModoAuto.className = 'seg-btn active-on';
      bModoManual.className = 'seg-btn';
      subModo.textContent = 'Evaluador automático activo';
    }
  }

  // 1. Media Sombra (Techo)
  const bTecho = document.getElementById('badge-techo');
  const bTechoOff = document.getElementById('btn-techo-off');
  const bTechoOn = document.getElementById('btn-techo-on');
  const subTecho = document.getElementById('sub-techo');

  if (state.techoPrendido) {
    bTecho.className = 'mech-badge on';
    bTecho.textContent = 'DESPLEGADA';
    bTechoOff.className = 'seg-btn';
    bTechoOn.className = 'seg-btn active-on';
    subTecho.textContent = 'DESPLEGADA (42% trans. solar)';
  } else {
    bTecho.className = 'mech-badge off';
    bTecho.textContent = 'RECOGIDA';
    bTechoOff.className = 'seg-btn active-off';
    bTechoOn.className = 'seg-btn';
    subTecho.textContent = 'RECOGIDA (90% trans. solar)';
  }

  // 2. Cortinas Laterales
  const bCort = document.getElementById('badge-cortinas');
  const bCortOff = document.getElementById('btn-cortinas-off');
  const bCortOn = document.getElementById('btn-cortinas-on');
  const subCort = document.getElementById('sub-cortinas');

  if (state.cortinasPrendido) {
    bCort.className = 'mech-badge on';
    bCort.textContent = 'ABIERTAS';
    bCortOff.className = 'seg-btn';
    bCortOn.className = 'seg-btn active-on';
    subCort.textContent = 'ABIERTAS (ventilación natural)';
  } else {
    bCort.className = 'mech-badge off';
    bCort.textContent = 'CERRADAS';
    bCortOff.className = 'seg-btn active-off';
    bCortOn.className = 'seg-btn';
    subCort.textContent = 'CERRADAS (protegidas contra viento)';
  }

  // 3. Ventiladores
  const bVent = document.getElementById('badge-vent');
  const bVentOff = document.getElementById('btn-vent-off');
  const bVentOn = document.getElementById('btn-vent-on');
  const subVent = document.getElementById('sub-vent');

  if (state.ventiladoresPrendido) {
    bVent.className = 'mech-badge on';
    bVent.textContent = 'ENCENDIDOS';
    bVentOff.className = 'seg-btn';
    bVentOn.className = 'seg-btn active-on';
    subVent.textContent = 'ENCENDIDOS (-15% temp.)';
  } else {
    bVent.className = 'mech-badge off';
    bVent.textContent = 'APAGADOS';
    bVentOff.className = 'seg-btn active-off';
    bVentOn.className = 'seg-btn';
    subVent.textContent = 'APAGADOS';
  }

  // HUD en la escena SVG
  document.getElementById('hud-clima').textContent = `CLIMA: ${state.clima} | VIENTO: ${state.vientoExterno.toFixed(1)} km/h`;
  document.getElementById('hud-act1').textContent =
    `Media Sombra: ${state.techoPrendido ? 'DESPLEGADA' : 'RECOGIDA'} | Cortinas: ${state.cortinasPrendido ? 'ABIERTAS' : 'CERRADAS'}`;
  document.getElementById('hud-act2').textContent =
    `Ventiladores: ${state.ventiladoresPrendido ? 'ENCENDIDOS' : 'APAGADOS'} | Modo: ${state.modo}`;
}

// -------------------------------------------------------------
// ACCIONES DEL USUARIO (ENVIAR A DJANGO)
// -------------------------------------------------------------
async function setMecanismo(mecanismo, estado) {
  // Optimismo en UI
  if (mecanismo === 'techo') state.techoPrendido = (estado === 'prendido');
  if (mecanismo === 'cortinas') state.cortinasPrendido = (estado === 'prendido');
  if (mecanismo === 'ventiladores') state.ventiladoresPrendido = (estado === 'prendido');
  actualizarControlesUI();

  try {
    const res = await fetch('/simulador/api/actuador/', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ mecanismo, estado })
    });
    const data = await res.json();
    if (data.ok) {
      fetchEstado();
    }
  } catch (err) {
    console.error('Error enviando mecanismo:', err);
  }
}

async function setModo(modo) {
  state.modo = modo;
  actualizarControlesUI();
  try {
    await fetch('/simulador/api/modo/', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ modo })
    });
    fetchEstado();
  } catch (err) {
    console.error('Error cambiando modo:', err);
  }
}

async function onClimaChange() {
  const sel = document.getElementById('sel-clima').value;
  try {
    await fetch('/simulador/api/clima/', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ clima: sel })
    });
    fetchEstado();
  } catch (err) {
    console.error('Error cambiando clima:', err);
  }
}

function onVientoInput() {
  const val = Number(document.getElementById('rng-viento').value);
  document.getElementById('lbl-viento').textContent = `${val.toFixed(1)} km/h`;
}

async function onVientoChange() {
  const val = Number(document.getElementById('rng-viento').value);
  document.getElementById('lbl-viento').textContent = `${val.toFixed(1)} km/h`;
  try {
    await fetch('/simulador/api/viento/', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ viento: val })
    });
    fetchEstado();
  } catch (err) {
    console.error('Error ajustando viento:', err);
  }
}

async function setVientoAuto() {
  try {
    await fetch('/simulador/api/viento/', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ viento: null })
    });
    fetchEstado();
  } catch (err) {
    console.error('Error restaurando viento automático:', err);
  }
}

async function onSpeedInput() {
  const val = Number(document.getElementById('rng-speed').value);
  document.getElementById('lbl-speed').textContent = `x${val}`;
  try {
    await fetch('/simulador/api/velocidad/', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ velocidad: val })
    });
  } catch (err) {
    console.error('Error ajustando velocidad:', err);
  }
}

async function adelantarTiempo(minutos) {
  try {
    await fetch('/simulador/api/velocidad/', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ adelantar_min: minutos })
    });
    resetSeriesLocales();
    fetchEstado();
  } catch (err) {
    console.error('Error adelantando simulación:', err);
  }
}

async function togglePause() {
  const nuevoEstado = !state.pausado;
  try {
    await fetch('/simulador/api/velocidad/', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ pausado: nuevoEstado })
    });
    fetchEstado();
  } catch (err) {
    console.error('Error pausando simulación:', err);
  }
}

async function resetSimulacion() {
  try {
    await fetch('/simulador/api/reset/', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' }
    });
    resetSeriesLocales();
    fetchEstado();
  } catch (err) {
    console.error('Error reiniciando:', err);
  }
}

function actualizarAtmosphereVisual(clima, esNoche, vientoExt = 0) {
  const cfg = EFECTOS_VISUALES[clima] || EFECTOS_VISUALES.NORMAL;
  const scene = document.getElementById('scene');
  if (scene) scene.classList.toggle('is-night', Boolean(esNoche));

  document.getElementById('sky-bg').setAttribute('fill', cfg.sky);
  document.getElementById('sun-group').setAttribute('opacity', esNoche ? 0 : cfg.sun);
  document.getElementById('clouds-group').setAttribute('opacity', cfg.clouds);
  document.getElementById('rain-group').setAttribute('opacity', cfg.rain);
  document.getElementById('frost-ground').setAttribute('opacity', cfg.frost);

  const windGroup = document.getElementById('wind-group');
  if (windGroup) {
    const windOpacity = Math.max(cfg.wind || 0, vientoExt >= 38 ? 0.85 : 0);
    windGroup.setAttribute('opacity', windOpacity.toFixed(2));
  }

  const hailGroup = document.getElementById('hail-group');
  if (hailGroup) {
    hailGroup.setAttribute('opacity', cfg.hail || 0);
  }

  const bolt = document.getElementById('lightning-group');
  if (cfg.lightning) {
    bolt.classList.add('lightning-active');
  } else {
    bolt.classList.remove('lightning-active');
    bolt.setAttribute('opacity', 0);
  }
}

// -------------------------------------------------------------
// ANIMACIÓN VISUAL SVG (60 FPS SUAVE)
// -------------------------------------------------------------
function animate() {
  // Interpolación suave de actuadores
  state.roof += (state.targetRoof - state.roof) * 0.08;
  state.sideOpen += (state.targetSideOpen - state.sideOpen) * 0.08;
  state.fan += (state.targetFan - state.fan) * 0.08;

  // 1. Cortinas de Techo (Media Sombra)
  const rRatio = state.roof / 100;
  const lx = 400 - (400 - 170) * rRatio;
  const ly = 78 + (145 - 78) * rRatio;
  const rx = 400 + (630 - 400) * rRatio;
  const ry = 78 + (145 - 78) * rRatio;

  const ptsLeft = `400,78 ${lx.toFixed(1)},${ly.toFixed(1)} ${lx.toFixed(1)},${(ly + 8).toFixed(1)} 400,86`;
  const ptsRight = `400,78 ${rx.toFixed(1)},${ry.toFixed(1)} ${rx.toFixed(1)},${(ry + 8).toFixed(1)} 400,86`;

  document.getElementById('roof-shade-left').setAttribute('points', ptsLeft);
  document.getElementById('roof-mesh-left').setAttribute('points', ptsLeft);
  document.getElementById('roof-roller-left').setAttribute('cx', lx.toFixed(1));
  document.getElementById('roof-roller-left').setAttribute('cy', (ly + 4).toFixed(1));

  document.getElementById('roof-shade-right').setAttribute('points', ptsRight);
  document.getElementById('roof-mesh-right').setAttribute('points', ptsRight);
  document.getElementById('roof-roller-right').setAttribute('cx', rx.toFixed(1));
  document.getElementById('roof-roller-right').setAttribute('cy', (ry + 4).toFixed(1));

  // 2. Cortinas Laterales
  const closedRatio = 1 - (state.sideOpen / 100);
  const curtainHeight = Math.max(4, 103 * closedRatio);
  const rollerY = 145 + curtainHeight - 2;

  document.getElementById('side-curtain-left').setAttribute('height', curtainHeight.toFixed(1));
  document.getElementById('side-roller-left').setAttribute('y', rollerY.toFixed(1));
  document.getElementById('side-curtain-right').setAttribute('height', curtainHeight.toFixed(1));
  document.getElementById('side-roller-right').setAttribute('y', rollerY.toFixed(1));

  // 3. Rotación de Ventiladores y Flujo de Aire
  if (state.fan > 1) {
    state.fanAngle = (state.fanAngle + (state.fan / 100) * 14) % 360;
    document.getElementById('fan-blades-1').setAttribute('transform', `rotate(${state.fanAngle.toFixed(1)})`);
    document.getElementById('fan-blades-2').setAttribute('transform', `rotate(${state.fanAngle.toFixed(1)})`);
  }

  const airOpacity = (state.fan / 100) * 0.75;
  document.getElementById('airflow-lines').setAttribute('opacity', airOpacity.toFixed(2));

  requestAnimationFrame(animate);
}

// -------------------------------------------------------------
// SISTEMA DE ALERTAS (SOLO DATOS REALES DE DJANGO)
// -------------------------------------------------------------
function renderAlerts(alertas) {
  const tbody = document.getElementById('alerts-tbody');
  const counter = document.getElementById('alerts-counter');
  const lista = Array.isArray(alertas) ? alertas : [];

  counter.textContent = `(${lista.length} / 10)`;

  if (lista.length === 0) {
    tbody.innerHTML = '<tr class="empty-row"><td colspan="5">Sin alertas registradas actualmente.</td></tr>';
    return;
  }

  tbody.innerHTML = lista.map(a => `
    <tr>
      <td style="font-family: ui-monospace, monospace;">${escapeHtml(a.hora)}</td>
      <td><strong>${escapeHtml(a.clima)}</strong></td>
      <td><span class="badge-cat">${escapeHtml(a.categoria || 'SISTEMA')}</span></td>
      <td><span class="badge-alert ${a.es_critico ? 'alert-danger' : ''}">${escapeHtml(a.tipo)}</span></td>
      <td>${escapeHtml(a.detalle)}</td>
    </tr>
  `).join('');
}

// -------------------------------------------------------------
// INICIALIZACIÓN
// -------------------------------------------------------------
actualizarControlesUI();
actualizarAtmosphereVisual('NORMAL', false, 0);
fetchEstado();
setInterval(fetchEstado, 750); // Muestreo periódico conectado al modelo físico Django
requestAnimationFrame(animate);
