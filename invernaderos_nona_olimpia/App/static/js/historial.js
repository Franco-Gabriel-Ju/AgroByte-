const $ = (selector) => document.querySelector(selector);
const inputFecha = $('#fecha');
const selectorRango = $('#rango');

const ICONOS_CLIMA = {
  NORMAL: '🌤️',
  DESPEJADO: '☀️',
  SOL_INTENSO: '🔆',
  PARCIALMENTE_NUBLADO: '⛅',
  NUBLADO: '☁️',
  LLUVIA: '🌧️',
  TORMENTA: '⛈️',
  TORMENTA_ELECTRICA: '🌩️',
  OLA_DE_CALOR: '🔥',
  FRIO_INTENSO: '❄️',
  VENTISCA: '💨',
  GRANIZO: '🌨️',
};

let estadoHistorial = null;
let historialActivaciones = [];
let desplazamiento = 0;
const barrasVisibles = 14;
let arrastrando = false;
let inicioArrastreX = 0;
let desplazamientoInicial = 0;
let barraResaltada = -1;
let cargaEnCurso = false;

function escaparHtml(texto) {
  return String(texto ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function formatearNumero(valor, decimales = 1) {
  const num = Number(valor);
  if (!Number.isFinite(num)) return '—';
  return decimales === 0 ? String(Math.round(num)) : String(Number(num.toFixed(decimales)));
}

function renderizarPronostico(pronostico, ubicacion) {
  const contUbicacion = $('#ubicacionPronostico');
  const contenedor = $('#pronostico');
  if (contUbicacion) {
    contUbicacion.textContent = ubicacion || 'Invernadero Nona Olimpia';
  }
  if (!contenedor) return;

  if (!Array.isArray(pronostico) || pronostico.length === 0) {
    contenedor.innerHTML = '<div class="pronostico-vacio">Sin pronóstico extendido registrado.</div>';
    return;
  }

  contenedor.innerHTML = pronostico
    .map((d) => {
      const icono = ICONOS_CLIMA[d.estado] || '🌤️';
      const tMax = formatearNumero(d.temp_max, 1);
      const tMin = formatearNumero(d.temp_min, 1);
      const lluvia = Number.isFinite(Number(d.prob_lluvia)) ? Number(d.prob_lluvia) : 0;
      const viento = formatearNumero(d.viento_kmh, 1);
      return `
        <div class="dia-pronostico" title="${escaparHtml(d.etiqueta || d.estado || '')}">
          <div class="dia-nombre">${escaparHtml(d.dia || d.fecha || '')}</div>
          <div class="dia-icono">${icono}</div>
          <div class="dia-temperaturas">${tMax}° <small>${tMin}°</small></div>
          <div class="dia-lluvia">${lluvia}% lluvia</div>
          <div class="dia-viento">💨 ${viento} km/h</div>
        </div>
      `;
    })
    .join('');
}

function dibujarGraficoLinea(config) {
  const { idCanvas, idFlotante, serie, color, fillColor, unidad, decimales, umbrales } = config;
  const canvas = $('#' + idCanvas);
  const flotante = $('#' + idFlotante);
  if (!canvas || !flotante) return [];

  const ctx = canvas.getContext('2d');
  const rect = canvas.getBoundingClientRect();
  if (rect.width <= 0 || rect.height <= 0) return [];

  const dpr = window.devicePixelRatio || 1;
  canvas.width = rect.width * dpr;
  canvas.height = rect.height * dpr;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

  const w = rect.width;
  const h = rect.height;
  const margen = { l: 46, r: 16, t: 16, b: 30 };
  const anchoGrafico = Math.max(10, w - margen.l - margen.r);
  const altoGrafico = Math.max(10, h - margen.t - margen.b);

  const etiquetas = Array.isArray(serie?.etiquetas) ? serie.etiquetas : [];
  const datos = Array.isArray(serie?.datos)
    ? serie.datos.map((v) => Number(v)).filter((v) => Number.isFinite(v))
    : [];

  if (datos.length === 0) {
    ctx.clearRect(0, 0, w, h);
    ctx.fillStyle = '#5a6d60';
    ctx.font = '13px Inter, system-ui, sans-serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText('Sin mediciones registradas para este período', w / 2, h / 2);
    canvas.onmousemove = null;
    canvas.onmouseleave = null;
    flotante.style.display = 'none';
    return [];
  }

  const valoresUmbral = (umbrales || [])
    .map((u) => Number(u?.valor))
    .filter((v) => Number.isFinite(v));

  const todosValores = [...datos, ...valoresUmbral];
  const minRaw = Math.min(...todosValores);
  const maxRaw = Math.max(...todosValores);

  let min = unidad === '°C' ? Math.floor(minRaw - 2) : 0;
  let max = Math.ceil(maxRaw + (unidad === 'W/m²' ? 50 : 3));
  if (unidad !== '°C' && minRaw < 0) {
    min = Math.floor(minRaw - 2);
  }
  if (max <= min) {
    max = min + (unidad === 'W/m²' ? 100 : 10);
  }

  const posX = (i) => {
    if (datos.length === 1) return margen.l + anchoGrafico / 2;
    return margen.l + (i / (datos.length - 1)) * anchoGrafico;
  };
  const posY = (v) => margen.t + ((max - v) / (max - min)) * altoGrafico;

  // Grilla horizontal y eje Y
  ctx.font = '11px Inter, system-ui, sans-serif';
  ctx.textAlign = 'right';
  ctx.textBaseline = 'middle';
  ctx.strokeStyle = '#e5ece6';
  ctx.fillStyle = '#5a6d60';
  ctx.lineWidth = 1;

  for (let k = 0; k <= 4; k++) {
    const val = min + ((max - min) * k) / 4;
    const yy = posY(val);
    ctx.beginPath();
    ctx.moveTo(margen.l, yy);
    ctx.lineTo(w - margen.r, yy);
    ctx.stroke();
    ctx.fillText(unidad === '°C' ? `${Math.round(val)}°` : `${Math.round(val)}`, margen.l - 9, yy);
  }

  // Etiquetas del eje X
  const maxMarcas = Math.min(selectorRango.value === 'day' ? 7 : 6, etiquetas.length);
  ctx.textAlign = 'center';
  ctx.textBaseline = 'top';
  ctx.fillStyle = '#5a6d60';
  if (maxMarcas === 1) {
    ctx.fillText(etiquetas[0] ?? '', posX(0), h - margen.b + 10);
  } else if (maxMarcas > 1) {
    for (let j = 0; j < maxMarcas; j++) {
      const idx = Math.round((j * (etiquetas.length - 1)) / (maxMarcas - 1));
      ctx.fillText(etiquetas[idx] ?? '', posX(idx), h - margen.b + 10);
    }
  }

  // Líneas punteadas de umbrales
  (umbrales || []).forEach((u) => {
    const val = Number(u?.valor);
    if (!Number.isFinite(val)) return;
    const yy = posY(val);
    ctx.save();
    ctx.beginPath();
    ctx.setLineDash([5, 4]);
    ctx.strokeStyle = u.color || '#c94a38';
    ctx.lineWidth = 1.4;
    ctx.moveTo(margen.l, yy);
    ctx.lineTo(w - margen.r, yy);
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = u.color || '#c94a38';
    ctx.font = '10px Inter, system-ui, sans-serif';
    ctx.textAlign = 'right';
    ctx.textBaseline = 'bottom';
    ctx.fillText(`${u.etiqueta}: ${formatearNumero(val, decimales)}`, w - margen.r - 2, yy - 2);
    ctx.restore();
  });

  // Área bajo la curva (si hay 2 o más puntos)
  if (datos.length > 1) {
    ctx.beginPath();
    datos.forEach((v, i) => {
      i ? ctx.lineTo(posX(i), posY(v)) : ctx.moveTo(posX(i), posY(v));
    });
    ctx.lineTo(posX(datos.length - 1), h - margen.b);
    ctx.lineTo(posX(0), h - margen.b);
    ctx.closePath();
    ctx.fillStyle = fillColor;
    ctx.fill();

    // Línea principal
    ctx.beginPath();
    datos.forEach((v, i) => {
      i ? ctx.lineTo(posX(i), posY(v)) : ctx.moveTo(posX(i), posY(v));
    });
    ctx.strokeStyle = color;
    ctx.lineWidth = 2.5;
    ctx.lineJoin = 'round';
    ctx.stroke();
  }

  // Punto final destacado (o punto único)
  const ultimoIdx = datos.length - 1;
  const ultimoX = posX(ultimoIdx);
  const ultimoY = posY(datos[ultimoIdx]);
  ctx.fillStyle = color;
  ctx.beginPath();
  ctx.arc(ultimoX, ultimoY, 4.5, 0, Math.PI * 2);
  ctx.fill();
  ctx.strokeStyle = '#ffffff';
  ctx.lineWidth = 1.5;
  ctx.stroke();

  canvas.onmousemove = (e) => {
    const limites = canvas.getBoundingClientRect();
    const mx = e.clientX - limites.left;
    const idx =
      datos.length === 1
        ? 0
        : Math.max(0, Math.min(datos.length - 1, Math.round(((mx - margen.l) / anchoGrafico) * (datos.length - 1))));
    const etiqueta = etiquetas[idx] ?? '';
    const valor = formatearNumero(datos[idx], decimales);

    flotante.style.display = 'block';
    flotante.innerHTML = `<strong>${escaparHtml(etiqueta)}</strong><br>${valor} ${escaparHtml(unidad)}`;
    flotante.style.left = Math.max(4, Math.min(w - 115, posX(idx) - 42)) + 'px';
    flotante.style.top = Math.max(0, posY(datos[idx]) - 48) + 'px';
  };

  canvas.onmouseleave = () => {
    flotante.style.display = 'none';
  };

  return datos;
}

function actualizarMetricaLinea(idMetrica, idRango, datos, unidad, decimales, sufijoUmbral) {
  const elMetrica = $('#' + idMetrica);
  const elRango = $('#' + idRango);
  if (!datos || datos.length === 0) {
    if (elMetrica) {
      elMetrica.innerHTML = `— <small>${escaparHtml(unidad)}</small>`;
    }
    if (elRango) {
      elRango.textContent = `Mín. — · Máx. —${sufijoUmbral ? ' · ' + sufijoUmbral : ''}`;
    }
    return;
  }

  const ultimo = formatearNumero(datos.at(-1), decimales);
  const min = formatearNumero(Math.min(...datos), decimales);
  const max = formatearNumero(Math.max(...datos), decimales);
  const simbolo = unidad === '°C' ? '°' : '';

  if (elMetrica) {
    elMetrica.innerHTML = `${ultimo}${simbolo} <small>${escaparHtml(unidad)}</small>`;
  }
  if (elRango) {
    const unidadTexto = unidad === '°C' ? '°' : ` ${unidad}`;
    elRango.textContent = `Mín. ${min}${unidadTexto} · Máx. ${max}${unidadTexto}${sufijoUmbral ? ' · ' + sufijoUmbral : ''}`;
  }
}

function limitarDesplazamiento() {
  const maxDesplazamiento = Math.max(0, historialActivaciones.length - barrasVisibles);
  desplazamiento = Math.max(0, Math.min(maxDesplazamiento, desplazamiento));
}

function actualizarResumenActivaciones() {
  const elMetrica = $('#metricaActivaciones');
  const elRango = $('#rangoActivaciones');

  if (!historialActivaciones.length) {
    if (elMetrica) elMetrica.innerHTML = '0 <small>activaciones</small>';
    if (elRango) elRango.textContent = 'Promedio 0/día · Máx. 0';
    return;
  }

  const ultimo = historialActivaciones.at(-1);
  const maxCantidad = Math.max(...historialActivaciones.map((a) => Number(a.cantidad) || 0));
  const total = historialActivaciones.reduce((acc, a) => acc + (Number(a.cantidad) || 0), 0);
  const promedio = (total / historialActivaciones.length).toFixed(1);

  if (elMetrica) {
    elMetrica.innerHTML = `${ultimo.cantidad} <small>activaciones (${escaparHtml(ultimo.fechaCorta)})</small>`;
  }
  if (elRango) {
    elRango.textContent = `Promedio ${promedio}/día · Máx. ${maxCantidad}`;
  }
}

function dibujarGraficoActivaciones() {
  const canvas = $('#graficoActivaciones');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  const rect = canvas.getBoundingClientRect();
  if (rect.width <= 0 || rect.height <= 0) return;

  const dpr = window.devicePixelRatio || 1;
  canvas.width = rect.width * dpr;
  canvas.height = rect.height * dpr;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

  const w = rect.width;
  const h = rect.height;
  const margen = { l: 42, r: 16, t: 16, b: 32 };
  const anchoGrafico = Math.max(10, w - margen.l - margen.r);
  const altoGrafico = Math.max(10, h - margen.t - margen.b);

  if (!historialActivaciones.length) {
    ctx.clearRect(0, 0, w, h);
    ctx.fillStyle = '#5a6d60';
    ctx.font = '13px Inter, system-ui, sans-serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText('Sin activaciones registradas en el período', w / 2, h / 2);
    return;
  }

  const maxData = Math.max(...historialActivaciones.map((d) => Number(d.cantidad) || 0));
  const valorMax = Math.max(4, Math.ceil(maxData / 2) * 2);

  // Grilla horizontal
  ctx.font = '11px Inter, system-ui, sans-serif';
  ctx.textAlign = 'right';
  ctx.textBaseline = 'middle';
  ctx.strokeStyle = '#e5ece6';
  ctx.fillStyle = '#5a6d60';
  ctx.lineWidth = 1;

  for (let k = 0; k <= 4; k++) {
    const val = (valorMax * k) / 4;
    const yy = margen.t + altoGrafico - (val / valorMax) * altoGrafico;
    ctx.beginPath();
    ctx.moveTo(margen.l, yy);
    ctx.lineTo(w - margen.r, yy);
    ctx.stroke();
    ctx.fillText(String(Math.round(val)), margen.l - 9, yy);
  }

  // Área recortada para las barras desplazables
  ctx.save();
  ctx.beginPath();
  ctx.rect(margen.l, margen.t - 4, anchoGrafico, altoGrafico + 28);
  ctx.clip();

  const columnas = Math.min(barrasVisibles, Math.max(1, historialActivaciones.length));
  const anchoRanura = anchoGrafico / barrasVisibles;
  const anchoBarra = Math.min(34, anchoRanura * 0.62);
  const indiceInicio = Math.max(0, Math.floor(desplazamiento) - 1);
  const indiceFin = Math.min(historialActivaciones.length - 1, Math.ceil(desplazamiento + columnas) + 1);

  for (let i = indiceInicio; i <= indiceFin; i++) {
    const item = historialActivaciones[i];
    const cantidad = Number(item.cantidad) || 0;
    const relX = (i - desplazamiento) * anchoRanura;
    const centroX = margen.l + relX + anchoRanura / 2;
    const altoBarra = (cantidad / valorMax) * altoGrafico;
    const barraX = centroX - anchoBarra / 2;
    const barraY = margen.t + altoGrafico - altoBarra;

    const resaltada = i === barraResaltada;
    ctx.fillStyle = resaltada ? '#224c2e' : '#3d7a47';

    if (altoBarra > 0) {
      const radio = Math.min(6, anchoBarra / 2, altoBarra);
      ctx.beginPath();
      ctx.moveTo(barraX, margen.t + altoGrafico);
      ctx.lineTo(barraX, barraY + radio);
      ctx.quadraticCurveTo(barraX, barraY, barraX + radio, barraY);
      ctx.lineTo(barraX + anchoBarra - radio, barraY);
      ctx.quadraticCurveTo(barraX + anchoBarra, barraY, barraX + anchoBarra, barraY + radio);
      ctx.lineTo(barraX + anchoBarra, margen.t + altoGrafico);
      ctx.closePath();
      ctx.fill();
    }

    if (anchoRanura >= 26) {
      ctx.fillStyle = resaltada ? '#224c2e' : '#5a6d60';
      ctx.font = resaltada ? 'bold 11px Inter, system-ui, sans-serif' : '11px Inter, system-ui, sans-serif';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'bottom';
      ctx.fillText(String(cantidad), centroX, Math.max(margen.t + 10, barraY - 4));
    }

    ctx.fillStyle = resaltada ? '#224c2e' : '#5a6d60';
    ctx.font = resaltada ? 'bold 11px Inter, system-ui, sans-serif' : '11px Inter, system-ui, sans-serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'top';
    ctx.fillText(item.fechaCorta || '', centroX, margen.t + altoGrafico + 9);
  }

  ctx.restore();

  // Barra indicadora de desplazamiento
  if (historialActivaciones.length > barrasVisibles) {
    const anchoPista = anchoGrafico;
    const anchoPulgar = Math.max(24, (barrasVisibles / historialActivaciones.length) * anchoPista);
    const maxDesplazamiento = historialActivaciones.length - barrasVisibles;
    const posPulgarX = margen.l + (desplazamiento / maxDesplazamiento) * (anchoPista - anchoPulgar);

    ctx.fillStyle = '#e5ece6';
    ctx.fillRect(margen.l, h - 4, anchoPista, 3);
    ctx.fillStyle = '#8eb396';
    ctx.fillRect(posPulgarX, h - 4, anchoPulgar, 3);
  }
}

const canvasActivaciones = $('#graficoActivaciones');
const flotanteActivaciones = $('#flotanteActivaciones');

if (canvasActivaciones && flotanteActivaciones) {
  canvasActivaciones.addEventListener('pointerdown', (e) => {
    if (!historialActivaciones.length) return;
    arrastrando = true;
    inicioArrastreX = e.clientX;
    desplazamientoInicial = desplazamiento;
    canvasActivaciones.setPointerCapture(e.pointerId);
    flotanteActivaciones.style.display = 'none';
  });

  canvasActivaciones.addEventListener('pointermove', (e) => {
    if (!historialActivaciones.length) return;
    const limites = canvasActivaciones.getBoundingClientRect();
    const anchoGrafico = Math.max(10, limites.width - 42 - 16);
    const anchoRanura = anchoGrafico / barrasVisibles;

    if (arrastrando) {
      const dx = e.clientX - inicioArrastreX;
      desplazamiento = desplazamientoInicial - dx / anchoRanura;
      limitarDesplazamiento();
      dibujarGraficoActivaciones();
      return;
    }

    const mx = e.clientX - limites.left;
    if (mx >= 42 && mx <= limites.width - 16) {
      const idx = Math.floor(desplazamiento + (mx - 42) / anchoRanura);
      if (idx >= 0 && idx < historialActivaciones.length) {
        barraResaltada = idx;
        const item = historialActivaciones[idx];
        const centroX = 42 + (idx - desplazamiento + 0.5) * anchoRanura;
        const ms = Number(item.media_sombra) || 0;
        const cl = Number(item.cortinas) || 0;
        const cant = Number(item.cantidad) || 0;

        flotanteActivaciones.style.display = 'block';
        flotanteActivaciones.innerHTML =
          `<strong>${escaparHtml(item.fechaCompleta)}</strong><br>` +
          `${cant} ${cant === 1 ? 'activación' : 'activaciones'}<br>` +
          `<small>Media sombra: ${ms} · Cortinas: ${cl}</small>`;
        flotanteActivaciones.style.left = Math.max(8, Math.min(limites.width - 175, centroX - 75)) + 'px';
        flotanteActivaciones.style.top = '10px';

        dibujarGraficoActivaciones();
        return;
      }
    }

    if (barraResaltada !== -1) {
      barraResaltada = -1;
      flotanteActivaciones.style.display = 'none';
      dibujarGraficoActivaciones();
    }
  });

  canvasActivaciones.addEventListener('pointerup', (e) => {
    arrastrando = false;
    if (canvasActivaciones.hasPointerCapture(e.pointerId)) {
      canvasActivaciones.releasePointerCapture(e.pointerId);
    }
  });

  canvasActivaciones.addEventListener('pointerleave', () => {
    arrastrando = false;
    barraResaltada = -1;
    flotanteActivaciones.style.display = 'none';
    dibujarGraficoActivaciones();
  });

  canvasActivaciones.addEventListener(
    'wheel',
    (e) => {
      if (historialActivaciones.length <= barrasVisibles) return;
      e.preventDefault();
      const delta = Math.abs(e.deltaX) > Math.abs(e.deltaY) ? e.deltaX : e.deltaY;
      desplazamiento += delta * 0.015;
      limitarDesplazamiento();
      flotanteActivaciones.style.display = 'none';
      dibujarGraficoActivaciones();
    },
    { passive: false }
  );
}

function renderizarDesdeEstado(reiniciarDesplazamiento = false) {
  if (!estadoHistorial) return;

  const modo = selectorRango.value;
  $('#textoAyuda').textContent =
    modo === 'day'
      ? 'Mostrando promedio diario (últimos 7 días)'
      : modo === 'hour'
        ? 'Mostrando promedio por hora (24 horas)'
        : 'Mostrando mediciones cada 10 min (24 horas)';

  if ($('#horaSimulada') && estadoHistorial.hora_simulada) {
    $('#horaSimulada').textContent = estadoHistorial.hora_simulada;
  }

  const p = estadoHistorial.parametros || {};
  const series = estadoHistorial.series || {};

  const datosTemp = dibujarGraficoLinea({
    idCanvas: 'graficoTemperatura',
    idFlotante: 'flotanteTemperatura',
    serie: series.temperatura,
    color: '#d98a2b',
    fillColor: 'rgba(217, 138, 43, 0.16)',
    unidad: '°C',
    decimales: 1,
    umbrales: [
      { valor: p.temp_min, etiqueta: 'Mín', color: '#2b82b8' },
      { valor: p.temp_max, etiqueta: 'Máx', color: '#c94a38' },
    ],
  });

  const datosRad = dibujarGraficoLinea({
    idCanvas: 'graficoRadiacion',
    idFlotante: 'flotanteRadiacion',
    serie: series.radiacion,
    color: '#3d7a47',
    fillColor: 'rgba(61, 122, 71, 0.16)',
    unidad: 'W/m²',
    decimales: 0,
    umbrales: [
      { valor: p.rad_min, etiqueta: 'Mín', color: '#2b82b8' },
      { valor: p.rad_max, etiqueta: 'Máx', color: '#c94a38' },
    ],
  });

  const datosViento = dibujarGraficoLinea({
    idCanvas: 'graficoViento',
    idFlotante: 'flotanteViento',
    serie: series.viento,
    color: '#2b82b8',
    fillColor: 'rgba(43, 130, 184, 0.16)',
    unidad: 'km/h',
    decimales: 1,
    umbrales: [
      { valor: p.viento_max, etiqueta: 'Máx', color: '#c94a38' },
    ],
  });

  const sufTemp = Number.isFinite(Number(p.temp_min)) && Number.isFinite(Number(p.temp_max))
    ? `Umbral ${p.temp_min}–${p.temp_max}°C`
    : '';
  const sufRad = Number.isFinite(Number(p.rad_min)) && Number.isFinite(Number(p.rad_max))
    ? `Umbral ${p.rad_min}–${p.rad_max} W/m²`
    : '';
  const sufViento = Number.isFinite(Number(p.viento_max))
    ? `Límite ${p.viento_max} km/h`
    : '';

  actualizarMetricaLinea('metricaTemperatura', 'rangoTemperatura', datosTemp, '°C', 1, sufTemp);
  actualizarMetricaLinea('metricaRadiacion', 'rangoRadiacion', datosRad, 'W/m²', 0, sufRad);
  actualizarMetricaLinea('metricaViento', 'rangoViento', datosViento, 'km/h', 1, sufViento);

  renderizarPronostico(estadoHistorial.pronostico, estadoHistorial.ubicacion);

  historialActivaciones = Array.isArray(estadoHistorial.activaciones) ? estadoHistorial.activaciones : [];
  if (reiniciarDesplazamiento) {
    desplazamiento = Math.max(0, historialActivaciones.length - barrasVisibles);
  } else {
    limitarDesplazamiento();
  }
  actualizarResumenActivaciones();
  dibujarGraficoActivaciones();
}

async function cargarHistorial({ reiniciarDesplazamiento = false } = {}) {
  if (cargaEnCurso) return;
  cargaEnCurso = true;
  try {
    const params = new URLSearchParams();
    params.set('rango', selectorRango.value || 'hour');
    if (inputFecha.value) {
      params.set('fecha', inputFecha.value);
    }

    const resp = await fetch(`/api/historial/?${params.toString()}`, {
      headers: { Accept: 'application/json' },
    });
    if (!resp.ok) return;

    const data = await resp.json();
    if (!data || !data.ok) return;

    if (!inputFecha.value && data.fecha_referencia) {
      inputFecha.value = data.fecha_referencia;
    }
    estadoHistorial = data;
    renderizarDesdeEstado(reiniciarDesplazamiento);
  } catch (err) {
    console.error('Error al cargar historial:', err);
  } finally {
    cargaEnCurso = false;
  }
}

selectorRango.addEventListener('change', () => cargarHistorial({ reiniciarDesplazamiento: false }));
inputFecha.addEventListener('change', () => cargarHistorial({ reiniciarDesplazamiento: true }));
window.addEventListener('resize', () => renderizarDesdeEstado(false));

cargarHistorial({ reiniciarDesplazamiento: true });
setInterval(() => {
  if (document.visibilityState === 'visible' && !arrastrando) {
    cargarHistorial({ reiniciarDesplazamiento: false });
  }
}, 5000);
