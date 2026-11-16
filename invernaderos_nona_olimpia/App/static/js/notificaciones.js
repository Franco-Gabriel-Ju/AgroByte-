const notificaciones = [
  ['alert', '⚠️', 'Temperatura por encima del umbral', '2026-11-14T14:32', 'La temperatura registrada alcanzó los 31,8 °C y superó el umbral configurado de 30 °C. Se recomienda comprobar la ventilación y revisar la evolución durante los próximos minutos.'],
  ['activation', '⚡', 'Ventilación automática activada', '2026-11-14T14:35', 'El sistema activó la ventilación al detectar que la temperatura superó el valor de referencia. La activación se mantendrá mientras continúe la condición.'],
  ['recommend', '💡', 'Aprovechar la radiación solar disponible', '2026-11-14T12:10', 'La radiación solar se encuentra en un nivel favorable. Se recomienda priorizar el uso de energía solar durante esta franja horaria y reducir consumos no esenciales más tarde.'],
  ['alert', '☀️', 'Radiación solar baja', '2026-11-14T08:20', 'La radiación medida está por debajo del nivel esperado para esta hora. Puede deberse a nubosidad o sombra temporal. No se requiere una acción inmediata.'],
  ['activation', '🔄', 'Ciclo de control completado', '2026-11-13T21:48', 'Finalizó correctamente el ciclo automático programado. Todos los parámetros quedaron dentro de los rangos de funcionamiento definidos.'],
  ['recommend', '🌡️', 'Revisar el umbral de temperatura', '2026-11-13T16:05', 'Durante los últimos días se observaron varios picos de temperatura cercanos al límite configurado. Podrías revisar el umbral o ajustar los horarios de funcionamiento.'],
  ['alert', '💧', 'Cambio brusco en las condiciones ambientales', '2026-11-12T11:26', 'Se detectó una variación rápida respecto de la medición anterior. El sistema continuará observando los valores para determinar si la condición persiste.'],
  ['activation', '⏱️', 'Programación horaria ejecutada', '2026-11-12T07:00', 'Se ejecutó la programación correspondiente al horario establecido. La operación terminó sin errores.'],
  ['recommend', '🌤️', 'Condiciones estables para las próximas horas', '2026-11-11T18:40', 'Las mediciones recientes muestran una tendencia estable. Se recomienda mantener la configuración actual y volver a evaluar al finalizar el día.'],
  ['alert', '🔔', 'Señal de sensor intermitente', '2026-11-10T09:14', 'Se registraron interrupciones breves en la recepción de datos del sensor. Comprueba la conexión si el problema vuelve a aparecer.']
];

const etiquetasTipo = {
  alert: 'Alerta',
  recommend: 'Recomendación',
  activation: 'Activación'
};

let tipoActivo = 'all';

const obtenerElemento = (id) => document.getElementById(id);

const formatearFecha = (fechaStr) =>
  new Intl.DateTimeFormat('es-AR', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit'
  }).format(new Date(fechaStr));

function renderizar() {
  const textoBusqueda = obtenerElemento('buscar').value.trim().toLocaleLowerCase('es');
  const fechaDesde = obtenerElemento('desde').value ? new Date(obtenerElemento('desde').value) : null;
  const fechaHasta = obtenerElemento('hasta').value ? new Date(obtenerElemento('hasta').value) : null;

  const filtradas = notificaciones
    .filter((item) => {
      const fechaItem = new Date(item[3]);
      const contenido = `${item[2]} ${item[4]} ${etiquetasTipo[item[0]]}`.toLocaleLowerCase('es');
      const coincideTipo = tipoActivo === 'all' || item[0] === tipoActivo;
      const coincideTexto = !textoBusqueda || contenido.includes(textoBusqueda);
      const coincideDesde = !fechaDesde || fechaItem >= fechaDesde;
      const coincideHasta = !fechaHasta || fechaItem <= fechaHasta;

      return coincideTipo && coincideTexto && coincideDesde && coincideHasta;
    })
    .sort((a, b) => new Date(b[3]) - new Date(a[3]));

  obtenerElemento('lista').innerHTML = filtradas
    .map(
      (item, indice) => `
      <article class="tarjeta">
        <div class="icono ${item[0]}">${item[1]}</div>
        <div>
          <div class="tipo ${item[0]}">${etiquetasTipo[item[0]]}</div>
          <p class="motivo">${item[2]}</p>
          <div class="fecha">${formatearFecha(item[3])}</div>
          <div class="detalle" id="detalle-${indice}" hidden>${item[4]}</div>
          <button class="btn-detalle" data-indice="${indice}" aria-expanded="false">Ver descripción completa ↓</button>
        </div>
        <div class="hora">${new Date(item[3]).toLocaleTimeString('es-AR', { hour: '2-digit', minute: '2-digit' })}</div>
      </article>
    `
    )
    .join('');

  obtenerElemento('contador').textContent =
    `${filtradas.length} ${filtradas.length === 1 ? 'notificación' : 'notificaciones'}`;
  obtenerElemento('vacio').style.display = filtradas.length ? 'none' : 'block';
  obtenerElemento('lista').style.display = filtradas.length ? 'flex' : 'none';
}

obtenerElemento('lista').addEventListener('click', (e) => {
  const boton = e.target.closest('[data-indice]');
  if (!boton) return;

  const detalle = obtenerElemento(`detalle-${boton.dataset.indice}`);
  const estaOculto = detalle.hidden;

  detalle.hidden = !estaOculto;
  boton.textContent = estaOculto ? 'Ocultar descripción ↑' : 'Ver descripción completa ↓';
  boton.setAttribute('aria-expanded', String(estaOculto));
});

['buscar', 'desde', 'hasta'].forEach((id) => {
  obtenerElemento(id).addEventListener('input', renderizar);
});

document.querySelectorAll('[data-tipo]').forEach((boton) => {
  boton.addEventListener('click', () => {
    tipoActivo = boton.dataset.tipo;
    document.querySelectorAll('[data-tipo]').forEach((b) => {
      b.classList.toggle('activo', b === boton);
    });
    renderizar();
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

  renderizar();
});

renderizar();