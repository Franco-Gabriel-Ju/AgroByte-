const $ = (selector) => document.querySelector(selector);
const inputFecha = $('#fecha');
const selectorRango = $('#rango');

const hoy = new Date();
inputFecha.value = [
  hoy.getFullYear(),
  String(hoy.getMonth() + 1).padStart(2, '0'),
  String(hoy.getDate()).padStart(2, '0')
].join('-');

const nombresDias = ['dom', 'lun', 'mar', 'mié', 'jue', 'vie', 'sáb'];

function generarPronostico() {
  const fechaBase = new Date(inputFecha.value + 'T12:00:00');
  const iconos = ['🌦️', '🌤️', '☀️', '⛅', '🌧️', '🌤️', '☀️', '⛅'];
  const probabilidadesLluvia = [35, 10, 0, 15, 65, 20, 0, 10];
  const contenedorPronostico = $('#pronostico');

  contenedorPronostico.innerHTML = '';

  for (let i = 0; i < 8; i++) {
    const fechaDia = new Date(fechaBase);
    fechaDia.setDate(fechaDia.getDate() + i);

    const max = Math.round(20 + 7 * Math.sin((i + 1) * 0.8) + ((i % 3) - 1));
    const min = max - (5 + (i % 3));

    const tarjetaDia = document.createElement('div');
    tarjetaDia.className = 'dia-pronostico';
    tarjetaDia.innerHTML = `
      <div class="dia-nombre">${i === 0 ? 'Hoy' : nombresDias[fechaDia.getDay()]}</div>
      <div class="dia-icono">${iconos[i]}</div>
      <div class="dia-temperaturas">${max}° <small>${min}°</small></div>
      <div class="dia-lluvia">${probabilidadesLluvia[i]}% lluvia</div>
    `;
    contenedorPronostico.append(tarjetaDia);
  }
}

function obtenerValores(modo, tipo) {
  const cantidad = modo === 'day' ? 7 : modo === 'hour' ? 24 : 144;
  const etiquetas = [];
  const datos = [];
  const inicio = new Date(inputFecha.value + 'T00:00:00');

  for (let i = 0; i < cantidad; i++) {
    let x;
    if (modo === 'day') {
      const fecha = new Date(inicio);
      fecha.setDate(fecha.getDate() + i);
      etiquetas.push(nombresDias[fecha.getDay()]);
      x = (i / 6) * Math.PI * 2;
    } else {
      const minutos = modo === 'hour' ? i * 60 : i * 10;
      const hh = Math.floor(minutos / 60);
      const mm = minutos % 60;
      etiquetas.push(
        modo === 'hour'
          ? `${String(hh).padStart(2, '0')}:00`
          : `${String(hh).padStart(2, '0')}:${String(mm).padStart(2, '0')}`
      );
      x = (minutos / 1440) * Math.PI * 2 - Math.PI / 2;
    }

    let valor;
    if (tipo === 'temp') {
      valor =
        modo === 'day'
          ? 21 + 5 * Math.sin(x - 0.8) + 1.2 * Math.cos(i * 1.7)
          : 18 + 7 * Math.sin(x - 0.9) + 1.2 * Math.sin(x * 3);
    } else {
      const minutos = modo === 'hour' ? i * 60 : i * 10;
      valor =
        modo === 'day'
          ? Math.max(0, Math.round(650 + 180 * Math.sin(x - 1) + 70 * Math.cos(i * 2)))
          : Math.max(
            0,
            Math.round(
              900 *
              Math.pow(Math.max(0, Math.sin((minutos / 1440) * Math.PI * 2 - Math.PI / 2)), 1.5) *
              (0.92 + 0.08 * Math.sin(i * 0.31))
            )
          );
    }

    datos.push(tipo === 'temp' ? Math.round(valor * 10) / 10 : valor);
  }

  return { etiquetas, datos };
}

function dibujarGraficoLinea(idCanvas, idFlotante, modo, tipo) {
  const canvas = $('#' + idCanvas);
  const ctx = canvas.getContext('2d');
  const flotante = $('#' + idFlotante);

  const rect = canvas.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  canvas.width = rect.width * dpr;
  canvas.height = rect.height * dpr;
  ctx.scale(dpr, dpr);

  const w = rect.width;
  const h = rect.height;
  const margen = { l: 42, r: 14, t: 14, b: 30 };
  const anchoGrafico = w - margen.l - margen.r;
  const altoGrafico = h - margen.t - margen.b;

  const { etiquetas, datos } = obtenerValores(modo, tipo);
  const min = tipo === 'temp' ? Math.floor(Math.min(...datos) - 2) : 0;
  const max = tipo === 'temp' ? Math.ceil(Math.max(...datos) + 2) : 1000;

  const posX = (i) => margen.l + (i / (datos.length - 1)) * anchoGrafico;
  const posY = (v) => margen.t + ((max - v) / (max - min)) * altoGrafico;

  ctx.font = '11px Inter, system-ui, sans-serif';
  ctx.textAlign = 'right';
  ctx.textBaseline = 'middle';
  ctx.strokeStyle = '#e5ece6';
  ctx.fillStyle = '#5a6d60';

  for (let k = 0; k <= 4; k++) {
    const val = min + ((max - min) * k) / 4;
    const yy = posY(val);
    ctx.beginPath();
    ctx.moveTo(margen.l, yy);
    ctx.lineTo(w - margen.r, yy);
    ctx.stroke();
    ctx.fillText(tipo === 'temp' ? `${Math.round(val)}°` : `${Math.round(val)}`, margen.l - 9, yy);
  }

  const marcasX = Math.min(modo === '10m' ? 6 : modo === 'hour' ? 6 : 7, etiquetas.length);
  ctx.textAlign = 'center';
  ctx.textBaseline = 'top';
  for (let j = 0; j < marcasX; j++) {
    const idx = Math.round((j * (etiquetas.length - 1)) / (marcasX - 1));
    ctx.fillText(etiquetas[idx], posX(idx), h - margen.b + 10);
  }

  // Área bajo la curva
  ctx.beginPath();
  datos.forEach((v, i) => {
    i ? ctx.lineTo(posX(i), posY(v)) : ctx.moveTo(posX(i), posY(v));
  });
  ctx.lineTo(posX(datos.length - 1), h - margen.b);
  ctx.lineTo(posX(0), h - margen.b);
  ctx.closePath();
  ctx.fillStyle = tipo === 'temp' ? 'rgba(217, 138, 43, 0.16)' : 'rgba(61, 122, 71, 0.16)';
  ctx.fill();

  // Línea principal
  ctx.beginPath();
  datos.forEach((v, i) => {
    i ? ctx.lineTo(posX(i), posY(v)) : ctx.moveTo(posX(i), posY(v));
  });
  ctx.strokeStyle = tipo === 'temp' ? '#d98a2b' : '#3d7a47';
  ctx.lineWidth = 2.5;
  ctx.lineJoin = 'round';
  ctx.stroke();

  // Punto final destacado
  const ultimoX = posX(datos.length - 1);
  const ultimoY = posY(datos.at(-1));
  ctx.fillStyle = tipo === 'temp' ? '#d98a2b' : '#224c2e';
  ctx.beginPath();
  ctx.arc(ultimoX, ultimoY, 4.5, 0, Math.PI * 2);
  ctx.fill();
  ctx.strokeStyle = '#ffffff';
  ctx.lineWidth = 1.5;
  ctx.stroke();

  canvas.onmousemove = (e) => {
    const limites = canvas.getBoundingClientRect();
    const mx = e.clientX - limites.left;
    const idx = Math.max(0, Math.min(datos.length - 1, Math.round(((mx - margen.l) / anchoGrafico) * (datos.length - 1))));
    const etiqueta = etiquetas[idx];
    const valor = datos[idx];

    flotante.style.display = 'block';
    flotante.innerHTML = `<strong>${etiqueta}</strong><br>${tipo === 'temp' ? valor + ' °C' : valor + ' W/m²'}`;
    flotante.style.left = Math.max(4, Math.min(w - 105, posX(idx) - 40)) + 'px';
    flotante.style.top = Math.max(0, posY(valor) - 48) + 'px';
  };

  canvas.onmouseleave = () => {
    flotante.style.display = 'none';
  };

  return datos;
}

// --- Gráfico de barras movible (Historial de activaciones) ---
let historialActivaciones = [];
let desplazamiento = 0;
const barrasVisibles = 14;
let arrastrando = false;
let inicioArrastreX = 0;
let desplazamientoInicial = 0;
let barraResaltada = -1;

function generarHistorialActivaciones() {
  const totalDias = 45;
  const fechaBase = new Date(inputFecha.value + 'T12:00:00');
  historialActivaciones = [];

  for (let i = totalDias - 1; i >= 0; i--) {
    const fecha = new Date(fechaBase);
    fecha.setDate(fecha.getDate() - i);

    const semilla = fecha.getDate() * 7 + (fecha.getMonth() + 1) * 13;
    const cantidad = Math.max(1, Math.round(6 + 4.5 * Math.sin(semilla * 0.45) + 2.5 * Math.cos(semilla * 0.9)));
    const dd = String(fecha.getDate()).padStart(2, '0');
    const mm = String(fecha.getMonth() + 1).padStart(2, '0');

    historialActivaciones.push({
      fechaCorta: `${dd}/${mm}`,
      fechaCompleta: `${nombresDias[fecha.getDay()]} ${dd}/${mm}/${fecha.getFullYear()}`,
      cantidad
    });
  }

  desplazamiento = Math.max(0, historialActivaciones.length - barrasVisibles);

  const ultimaCantidad = historialActivaciones.at(-1).cantidad;
  const maxCantidad = Math.max(...historialActivaciones.map((a) => a.cantidad));
  const promedio = (
    historialActivaciones.reduce((acc, a) => acc + a.cantidad, 0) / historialActivaciones.length
  ).toFixed(1);

  $('#metricaActivaciones').innerHTML = `${ultimaCantidad} <small>aperturas (${historialActivaciones.at(-1).fechaCorta})</small>`;
  $('#rangoActivaciones').textContent = `Promedio ${promedio}/día · Máx. ${maxCantidad}`;
}

function dibujarGraficoActivaciones() {
  const canvas = $('#graficoActivaciones');
  const ctx = canvas.getContext('2d');
  const rect = canvas.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;

  canvas.width = rect.width * dpr;
  canvas.height = rect.height * dpr;
  ctx.scale(dpr, dpr);

  const w = rect.width;
  const h = rect.height;
  const margen = { l: 42, r: 16, t: 16, b: 32 };
  const anchoGrafico = w - margen.l - margen.r;
  const altoGrafico = h - margen.t - margen.b;

  const valorMax = Math.max(12, Math.ceil(Math.max(...historialActivaciones.map((d) => d.cantidad)) / 2) * 2);

  // Grilla horizontal
  ctx.font = '11px Inter, system-ui, sans-serif';
  ctx.textAlign = 'right';
  ctx.textBaseline = 'middle';
  ctx.strokeStyle = '#e5ece6';
  ctx.fillStyle = '#5a6d60';

  for (let k = 0; k <= 4; k++) {
    const val = (valorMax * k) / 4;
    const yy = margen.t + altoGrafico - (val / valorMax) * altoGrafico;
    ctx.beginPath();
    ctx.moveTo(margen.l, yy);
    ctx.lineTo(w - margen.r, yy);
    ctx.stroke();
    ctx.fillText(Math.round(val), margen.l - 9, yy);
  }

  // Área recortada para las barras desplazables
  ctx.save();
  ctx.beginPath();
  ctx.rect(margen.l, margen.t - 4, anchoGrafico, altoGrafico + 28);
  ctx.clip();

  const anchoRanura = anchoGrafico / barrasVisibles;
  const anchoBarra = Math.min(34, anchoRanura * 0.62);
  const indiceInicio = Math.max(0, Math.floor(desplazamiento) - 1);
  const indiceFin = Math.min(historialActivaciones.length - 1, Math.ceil(desplazamiento + barrasVisibles) + 1);

  for (let i = indiceInicio; i <= indiceFin; i++) {
    const item = historialActivaciones[i];
    const relX = (i - desplazamiento) * anchoRanura;
    const centroX = margen.l + relX + anchoRanura / 2;
    const altoBarra = (item.cantidad / valorMax) * altoGrafico;
    const barraX = centroX - anchoBarra / 2;
    const barraY = margen.t + altoGrafico - altoBarra;

    const resaltada = i === barraResaltada;
    ctx.fillStyle = resaltada ? '#224c2e' : '#3d7a47';

    // Barra con bordes superiores redondeados
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

    // Valor encima de la barra
    if (anchoRanura >= 26) {
      ctx.fillStyle = resaltada ? '#224c2e' : '#5a6d60';
      ctx.font = resaltada ? 'bold 11px Inter, system-ui, sans-serif' : '11px Inter, system-ui, sans-serif';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'bottom';
      ctx.fillText(item.cantidad, centroX, barraY - 4);
    }

    // Etiqueta de fecha en el eje X
    ctx.fillStyle = resaltada ? '#224c2e' : '#5a6d60';
    ctx.font = resaltada ? 'bold 11px Inter, system-ui, sans-serif' : '11px Inter, system-ui, sans-serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'top';
    ctx.fillText(item.fechaCorta, centroX, margen.t + altoGrafico + 9);
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

function limitarDesplazamiento() {
  const maxDesplazamiento = Math.max(0, historialActivaciones.length - barrasVisibles);
  desplazamiento = Math.max(0, Math.min(maxDesplazamiento, desplazamiento));
}

canvasActivaciones.addEventListener('pointerdown', (e) => {
  arrastrando = true;
  inicioArrastreX = e.clientX;
  desplazamientoInicial = desplazamiento;
  canvasActivaciones.setPointerCapture(e.pointerId);
  flotanteActivaciones.style.display = 'none';
});

canvasActivaciones.addEventListener('pointermove', (e) => {
  const limites = canvasActivaciones.getBoundingClientRect();
  const anchoGrafico = limites.width - 42 - 16;
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

      flotanteActivaciones.style.display = 'block';
      flotanteActivaciones.innerHTML = `<strong>${item.fechaCompleta}</strong><br>${item.cantidad} ${item.cantidad === 1 ? 'apertura' : 'aperturas'
        }`;
      flotanteActivaciones.style.left = Math.max(8, Math.min(limites.width - 125, centroX - 55)) + 'px';
      flotanteActivaciones.style.top = '12px';

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
  canvasActivaciones.releasePointerCapture(e.pointerId);
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
    e.preventDefault();
    const delta = Math.abs(e.deltaX) > Math.abs(e.deltaY) ? e.deltaX : e.deltaY;
    desplazamiento += delta * 0.015;
    limitarDesplazamiento();
    flotanteActivaciones.style.display = 'none';
    dibujarGraficoActivaciones();
  },
  { passive: false }
);

function renderizar(reiniciarHistorial = false) {
  const modo = selectorRango.value;
  $('#textoAyuda').textContent =
    modo === 'day'
      ? 'Mostrando 7 días'
      : modo === 'hour'
        ? 'Mostrando 24 horas'
        : 'Mostrando 144 mediciones · intervalos de 10 min';

  const datosTemp = dibujarGraficoLinea('graficoTemperatura', 'flotanteTemperatura', modo, 'temp');
  const datosSolar = dibujarGraficoLinea('graficoRadiacion', 'flotanteRadiacion', modo, 'solar');

  $('#metricaTemperatura').innerHTML = `${datosTemp.at(-1)}° <small>°C</small>`;
  $('#metricaRadiacion').innerHTML = `${datosSolar.at(-1)} <small>W/m²</small>`;
  $('#rangoTemperatura').textContent = `Mín. ${Math.min(...datosTemp)}° · Máx. ${Math.max(...datosTemp)}°`;
  $('#rangoRadiacion').textContent = `Mín. ${Math.min(...datosSolar)} · Máx. ${Math.max(...datosSolar)} W/m²`;

  generarPronostico();
  if (reiniciarHistorial) generarHistorialActivaciones();
  dibujarGraficoActivaciones();
}

selectorRango.addEventListener('change', () => renderizar(false));
inputFecha.addEventListener('change', () => renderizar(true));
window.addEventListener('resize', () => renderizar(false));

renderizar(true);