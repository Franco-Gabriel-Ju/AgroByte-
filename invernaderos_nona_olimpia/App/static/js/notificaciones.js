let tipoActivo = 'all';
let temporizadorBusqueda = null;
let cargaEnCurso = false;
const detallesAbiertos = new Set();

const obtenerElemento = (id) => document.getElementById(id);

function escaparHtml(texto) {
  return String(texto ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function normalizarNivel(nivel) {
  const n = String(nivel || 'INFO').toUpperCase();
  if (n === 'CRITICO' || n === 'ADVERTENCIA' || n === 'INFO') return n;
  return 'INFO';
}

function renderizarLista(notificaciones) {
  const listaEl = obtenerElemento('lista');
  const vacioEl = obtenerElemento('vacio');
  const contadorEl = obtenerElemento('contador');

  const items = Array.isArray(notificaciones) ? notificaciones : [];

  listaEl.innerHTML = items
    .map((item) => {
      const id = String(item.id);
      const tipo = item.type || 'alert';
      const nivel = normalizarNivel(item.nivel);
      const abierta = detallesAbiertos.has(id);
      const tag = item.tag || (tipo === 'recommend' ? 'Recomendación' : tipo === 'activation' ? 'Activación' : 'Alerta');

      return `
      <article class="tarjeta">
        <div class="icono ${escaparHtml(tipo)}">${escaparHtml(item.icon || '🔔')}</div>
        <div>
          <div class="encabezado-tarjeta-alerta">
            <div class="tipo ${escaparHtml(tipo)}">${escaparHtml(tag)}</div>
            <span class="badge-nivel nivel-${nivel}">${nivel}</span>
            ${item.variable ? `<span class="badge-variable">${escaparHtml(item.variable)}</span>` : ''}
          </div>
          <p class="motivo">${escaparHtml(item.titulo)}</p>
          <div class="fecha">${escaparHtml(item.fecha_texto || '')}</div>
          <div class="detalle" id="detalle-${id}" ${abierta ? '' : 'hidden'}>${escaparHtml(item.descripcion || '')}</div>
          <button class="btn-detalle" data-id="${id}" aria-expanded="${String(abierta)}">
            ${abierta ? 'Ocultar descripción ↑' : 'Ver descripción completa ↓'}
          </button>
        </div>
        <div class="hora">${escaparHtml(item.hora_texto || '')}</div>
      </article>
      `;
    })
    .join('');

  contadorEl.textContent = `${items.length} ${items.length === 1 ? 'notificación' : 'notificaciones'}`;
  vacioEl.style.display = items.length ? 'none' : 'block';
  listaEl.style.display = items.length ? 'flex' : 'none';
}

async function cargarAlertas() {
  if (cargaEnCurso) return;
  cargaEnCurso = true;
  try {
    const params = new URLSearchParams();
    const q = obtenerElemento('buscar').value.trim();
    const desde = obtenerElemento('desde').value.trim();
    const hasta = obtenerElemento('hasta').value.trim();

    params.set('tipo', tipoActivo);
    if (q) params.set('q', q);
    if (desde) params.set('desde', desde);
    if (hasta) params.set('hasta', hasta);

    const resp = await fetch(`/api/alertas/?${params.toString()}`, {
      headers: { Accept: 'application/json' },
    });
    if (!resp.ok) return;

    const data = await resp.json();
    if (!data || !data.ok) return;

    const horaEl = obtenerElemento('horaSimulada');
    if (horaEl && data.hora_simulada) {
      horaEl.textContent = data.hora_simulada;
    }

    renderizarLista(data.notificaciones);
  } catch (err) {
    console.error('Error al cargar alertas:', err);
  } finally {
    cargaEnCurso = false;
  }
}

obtenerElemento('lista').addEventListener('click', (e) => {
  const boton = e.target.closest('[data-id]');
  if (!boton) return;

  const id = boton.dataset.id;
  const detalle = obtenerElemento(`detalle-${id}`);
  if (!detalle) return;

  const estaOculto = detalle.hidden;
  detalle.hidden = !estaOculto;
  if (estaOculto) {
    detallesAbiertos.add(id);
  } else {
    detallesAbiertos.delete(id);
  }

  boton.textContent = estaOculto ? 'Ocultar descripción ↑' : 'Ver descripción completa ↓';
  boton.setAttribute('aria-expanded', String(estaOculto));
});

obtenerElemento('buscar').addEventListener('input', () => {
  clearTimeout(temporizadorBusqueda);
  temporizadorBusqueda = setTimeout(cargarAlertas, 200);
});

['desde', 'hasta'].forEach((id) => {
  obtenerElemento(id).addEventListener('change', cargarAlertas);
});

document.querySelectorAll('[data-tipo]').forEach((boton) => {
  boton.addEventListener('click', () => {
    tipoActivo = boton.dataset.tipo;
    document.querySelectorAll('[data-tipo]').forEach((b) => {
      b.classList.toggle('activo', b === boton);
    });
    cargarAlertas();
  });
});

obtenerElemento('limpiar').addEventListener('click', () => {
  obtenerElemento('buscar').value = '';
  obtenerElemento('desde').value = '';
  obtenerElemento('hasta').value = '';
  tipoActivo = 'all';

  document.querySelectorAll('[data-tipo]').forEach((b) => {
    b.classList.toggle('activo', b.dataset.tipo === 'all');
  });

  cargarAlertas();
});

cargarAlertas();
setInterval(() => {
  if (document.visibilityState === 'visible') {
    cargarAlertas();
  }
}, 5000);
