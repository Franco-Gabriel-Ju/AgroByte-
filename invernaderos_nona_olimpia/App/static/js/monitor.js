// =========================================================================
// 0. CONFIGURACIÓN DE TAILWIND CSS
// =========================================================================
if (typeof tailwind !== 'undefined') {
    tailwind.config = {
        theme: {
            extend: {
                fontFamily: {
                    sans: ['Inter', 'system-ui', '-apple-system', 'sans-serif'],
                },
                colors: {
                    brand: {
                        bg: '#f4f6f4',
                        panel: '#ffffff',
                        line: '#dce4dd',
                        forest: '#1f492a',
                        green: '#49982c',
                        greenDark: '#397b21',
                        greenSoft: '#eaf4e7',
                        alertBg: '#f9d7d5',
                        alertBorder: '#e23d28',
                        alertText: '#6f1811',
                    }
                }
            }
        }
    };
}

// =========================================================================
// 1. ESTADO GLOBAL DE LA APLICACIÓN
// =========================================================================
const state = {
    mode: 'auto', // 'auto' | 'manual'
    mechanisms: {
        turbines: { level: 68, active: true, labelOn: 'Funcionando', labelOff: 'Detenidas', unitLabel: 'Velocidad' },
        shade: { level: 70, active: true, labelOn: 'Abierta', labelOff: 'Cerrada', unitLabel: 'Nivel' },
        curtains: { level: 80, active: true, labelOn: 'Abiertas', labelOff: 'Cerradas', unitLabel: 'Nivel' }
    },
    notifFilter: 'all',
    notifications: [
        {
            id: 1,
            type: 'alert',
            tag: 'Alerta',
            title: 'Radiación solar alta sostenida (890 W/m²)',
            time: '14:32',
            unread: true,
            detail: 'La radiación superó el límite superior de 800 W/m² durante más de 15 minutos. Se recomienda verificar el despliegue de la media sombra.'
        },
        {
            id: 2,
            type: 'activation',
            tag: 'Activación',
            title: 'Turbinas ajustadas al 68% automáticamente',
            time: '14:28',
            unread: true,
            detail: 'Al alcanzarse los 31 °C interiores, el controlador elevó el flujo de ventilación para estabilizar la temperatura.'
        },
        {
            id: 3,
            type: 'recommend',
            tag: 'Recomendación',
            title: 'Disminuir intensidad lumínica en sector norte',
            time: '14:15',
            unread: false,
            detail: 'Con cielo despejado y radiación en ascenso, aumentar la cobertura de media sombra al 85% evita estrés térmico.'
        },
        {
            id: 4,
            type: 'activation',
            tag: 'Activación',
            title: 'Cortinas laterales abiertas al 80%',
            time: '13:40',
            unread: false,
            detail: 'Apertura gradual completada sin incidencias para favorecer la renovación de aire natural.'
        }
    ],
    chartRanges: {
        radiation: 'hoy',
        temperature: 'hoy'
    }
};

// =========================================================================
// 2. DATOS PARA LOS GRÁFICOS HISTÓRICOS (Hoy / 24 h / 7 días)
// =========================================================================
const chartDatasets = {
    radiation: {
        hoy: {
            labels: ['08:00', '', '', '', '09:00', '', '', '', '10:00', '', '', '', '11:00', '', '', '', '12:00', '', '', '', '13:00', '', '', '', '14:00', '', '14:32', '15:00'],
            values: [215, 228, 240, 265, 295, 290, 325, 345, 340, 385, 375, 410, 445, 455, 510, 520, 565, 540, 580, 575, 620, 665, 675, 650, 645, 710, 745, 730, 770, 815, 845, 810, 865, 890, 805],
            highlightIndex: 33,
            highlightTime: '14:32',
            highlightText: '890 W/m²',
            xAxisTitle: 'Hora'
        },
        '24h': {
            labels: ['16:00', '18:00', '20:00', '22:00', '00:00', '02:00', '04:00', '06:00', '08:00', '10:00', '12:00', '14:32'],
            values: [640, 310, 45, 0, 0, 0, 0, 85, 295, 455, 675, 890],
            highlightIndex: 11,
            highlightTime: '14:32',
            highlightText: '890 W/m²',
            xAxisTitle: 'Últimas 24 horas'
        },
        '7d': {
            labels: ['Jue', 'Vie', 'Sáb', 'Dom', 'Lun', 'Mar', 'Mié'],
            values: [760, 810, 690, 720, 840, 865, 890],
            highlightIndex: 6,
            highlightTime: 'Mié 14:32',
            highlightText: '890 W/m²',
            xAxisTitle: 'Últimos 7 días (pico diario)'
        }
    },
    temperature: {
        hoy: {
            labels: ['08:00', '', '', '', '09:00', '', '', '', '10:00', '', '', '', '11:00', '', '', '', '12:00', '', '', '', '13:00', '', '', '', '14:00', '', '14:32', '15:00'],
            values: [24.2, 24.7, 24.8, 25.4, 25.6, 26.4, 26.6, 27.5, 27.9, 27.4, 27.9, 27.7, 28.2, 28.6, 28.2, 28.1, 29.0, 29.1, 28.8, 29.5, 29.9, 29.5, 30.2, 30.0, 30.2, 30.1, 30.3, 30.4, 30.5, 30.6, 30.7, 30.8, 30.9, 31.0, 30.8],
            highlightIndex: 33,
            highlightTime: '14:32',
            highlightText: '31 °C',
            xAxisTitle: 'Hora'
        },
        '24h': {
            labels: ['16:00', '18:00', '20:00', '22:00', '00:00', '02:00', '04:00', '06:00', '08:00', '10:00', '12:00', '14:32'],
            values: [29.8, 27.2, 24.5, 22.8, 21.5, 20.8, 20.4, 21.6, 24.6, 27.8, 29.9, 31.0],
            highlightIndex: 11,
            highlightTime: '14:32',
            highlightText: '31 °C',
            xAxisTitle: 'Últimas 24 horas'
        },
        '7d': {
            labels: ['Jue', 'Vie', 'Sáb', 'Dom', 'Lun', 'Mar', 'Mié'],
            values: [28.5, 29.2, 27.4, 28.0, 30.1, 30.5, 31.0],
            highlightIndex: 6,
            highlightTime: 'Mié 14:32',
            highlightText: '31 °C',
            xAxisTitle: 'Últimos 7 días (máxima)'
        }
    }
};

// =========================================================================
// 3. MODO AUTOMÁTICO / MANUAL Y CONTROL DE MECANISMOS
// =========================================================================
function setOperationMode(mode) {
    state.mode = mode;
    const isAuto = mode === 'auto';

    const btnAuto = document.getElementById('btn-auto');
    const btnManual = document.getElementById('btn-manual');
    const kpiMode = document.getElementById('kpi-mode-value');
    const mechHint = document.getElementById('mech-mode-hint');

    if (isAuto) {
        btnAuto.className = 'flex items-center gap-1.5 px-3.5 py-1.5 rounded-full text-xs sm:text-[13px] font-semibold transition-all duration-150 bg-brand-green text-white shadow-xs cursor-pointer';
        btnManual.className = 'flex items-center gap-1.5 px-3.5 py-1.5 rounded-full text-xs sm:text-[13px] font-medium text-[#526356] hover:text-brand-forest transition-all duration-150 cursor-pointer';
        kpiMode.textContent = 'Automático';
        kpiMode.classList.remove('text-amber-600');
        kpiMode.classList.add('text-[#19241c]');
        mechHint.textContent = 'Control automático activo';
        mechHint.className = 'text-xs font-medium px-2.5 py-1 rounded-full bg-[#f4f6f4] text-[#56685b] border border-brand-line';
    } else {
        btnManual.className = 'flex items-center gap-1.5 px-3.5 py-1.5 rounded-full text-xs sm:text-[13px] font-semibold transition-all duration-150 bg-brand-forest text-white shadow-xs cursor-pointer';
        btnAuto.className = 'flex items-center gap-1.5 px-3.5 py-1.5 rounded-full text-xs sm:text-[13px] font-medium text-[#526356] hover:text-brand-forest transition-all duration-150 cursor-pointer';
        kpiMode.textContent = 'Manual';
        kpiMode.classList.remove('text-[#19241c]');
        kpiMode.classList.add('text-amber-600');
        mechHint.textContent = 'Ajuste manual habilitado';
        mechHint.className = 'text-xs font-semibold px-2.5 py-1 rounded-full bg-amber-50 text-amber-800 border border-amber-200';
    }

    // Alternar entre barras de progreso (Automático) y sliders interactivos (Manual)
    ['turbines', 'shade', 'curtains'].forEach((key) => {
        const barWrap = document.getElementById(`bar-wrap-${key}`);
        const slider = document.getElementById(`slider-${key}`);
        const toggleBtn = document.getElementById(`toggle-${key}`);

        if (isAuto) {
            barWrap.classList.remove('hidden');
            slider.classList.add('hidden');
            toggleBtn.classList.add('hidden');
        } else {
            barWrap.classList.add('hidden');
            slider.classList.remove('hidden');
            toggleBtn.classList.remove('hidden');
        }
    });

    // Registrar evento en notificaciones
    const nowTime = getCurrentShortTime();
    addNotification({
        type: 'activation',
        tag: 'Cambio de modo',
        title: isAuto ? 'Modo Automático activado' : 'Modo Manual activado por operador',
        time: nowTime,
        unread: true,
        detail: isAuto
            ? 'El sistema retoma la regulación automática de turbinas, media sombra y cortinas según umbrales.'
            : 'El operador habilitó el ajuste manual directo sobre los actuadores del invernadero.'
    });
}

function updateMechanismLevel(key, value) {
    const numVal = parseInt(value, 10);
    const mech = state.mechanisms[key];
    mech.level = numVal;
    mech.active = numVal > 0;

    document.getElementById(`val-${key}`).textContent = `${numVal}%`;
    document.getElementById(`bar-${key}`).style.width = `${numVal}%`;
    document.getElementById(`slider-${key}`).value = numVal;

    const statusEl = document.getElementById(`status-${key}`);
    const dotEl = document.getElementById(`dot-${key}`);
    const toggleBtn = document.getElementById(`toggle-${key}`);

    if (mech.active) {
        statusEl.textContent = mech.labelOn;
        statusEl.className = 'text-xs font-semibold text-brand-green';
        dotEl.className = 'w-2 h-2 rounded-full bg-brand-green';
        toggleBtn.textContent = key === 'turbines' ? 'Apagar' : 'Cerrar';
    } else {
        statusEl.textContent = mech.labelOff;
        statusEl.className = 'text-xs font-semibold text-slate-500';
        dotEl.className = 'w-2 h-2 rounded-full bg-slate-400';
        toggleBtn.textContent = key === 'turbines' ? 'Encender' : 'Abrir';
    }

    // Sincronizar KPI de Media Sombra si corresponde
    if (key === 'shade') {
        const kpiShade = document.getElementById('kpi-shade-status');
        kpiShade.textContent = mech.active ? 'Abierta' : 'Cerrada';
        kpiShade.className = mech.active
            ? 'text-xl sm:text-[22px] font-bold text-brand-green tracking-tight mt-0.5'
            : 'text-xl sm:text-[22px] font-bold text-slate-600 tracking-tight mt-0.5';
    }

    document.getElementById('kpi-last-event').textContent = getCurrentShortTime();
}

function toggleMechanism(key) {
    const mech = state.mechanisms[key];
    const nextLevel = mech.active ? 0 : (key === 'turbines' ? 65 : 75);
    updateMechanismLevel(key, nextLevel);
}

function getCurrentShortTime() {
    const now = new Date();
    return now.toLocaleTimeString('es-AR', { hour: '2-digit', minute: '2-digit' });
}

// =========================================================================
// 4. PANEL DE NOTIFICACIONES
// =========================================================================
function addNotification(notif) {
    state.notifications.unshift({
        id: Date.now(),
        ...notif
    });
    if (state.notifications.length > 15) state.notifications.pop();
    document.getElementById('kpi-last-event').textContent = notif.time;
    renderNotifications();
}

function markAllRead() {
    state.notifications.forEach((n) => (n.unread = false));
    renderNotifications();
}

function toggleNotifDetail(id) {
    const detailEl = document.getElementById(`notif-detail-${id}`);
    const btnEl = document.getElementById(`notif-btn-${id}`);
    if (!detailEl || !btnEl) return;

    const isHidden = detailEl.classList.contains('hidden');
    detailEl.classList.toggle('hidden', !isHidden);
    btnEl.textContent = isHidden ? 'Ocultar ▲' : 'Detalle ▼';

    const target = state.notifications.find((n) => n.id === id);
    if (target && target.unread) {
        target.unread = false;
        updateUnreadBadge();
    }
}

function updateUnreadBadge() {
    const unreadCount = state.notifications.filter((n) => n.unread).length;
    const badge = document.getElementById('notif-badge');
    badge.textContent = unreadCount > 0 ? unreadCount : state.notifications.length;
    badge.className = unreadCount > 0
        ? 'inline-flex items-center justify-center px-2 py-0.5 text-[11px] font-bold rounded-full bg-brand-alertBorder text-white'
        : 'inline-flex items-center justify-center px-2 py-0.5 text-[11px] font-bold rounded-full bg-brand-forest text-white';
}

function renderNotifications() {
    const container = document.getElementById('notif-list');
    const filtered = state.notifications.filter(
        (n) => state.notifFilter === 'all' || n.type === state.notifFilter
    );

    updateUnreadBadge();

    if (!filtered.length) {
        container.innerHTML = `
      <div class="text-center py-6 text-xs text-[#647569] bg-[#f9fbf9] rounded-xl border border-dashed border-brand-line">
        No hay notificaciones en esta categoría.
      </div>
    `;
        return;
    }

    const stylesByType = {
        alert: {
            bg: 'bg-[#fdf4f3] border-[#f4c9c5]',
            badge: 'text-[#c94a38] bg-[#fce8e6]',
            icon: `<svg class="w-4 h-4 text-[#c94a38]" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>`
        },
        recommend: {
            bg: 'bg-[#fdf9f2] border-[#f3e1c3]',
            badge: 'text-[#b86f19] bg-[#fdf3e3]',
            icon: `<svg class="w-4 h-4 text-[#d98a2b]" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><path d="M9 18h6"/><path d="M10 22h4"/><path d="M12 2a7 7 0 0 0-4 12.7V17h8v-2.3A7 7 0 0 0 12 2z"/></svg>`
        },
        activation: {
            bg: 'bg-[#f6fbf5] border-[#d3e6d0]',
            badge: 'text-brand-green bg-[#e6f2e8]',
            icon: `<svg class="w-4 h-4 text-brand-green" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><polyline points="20 6 9 17 4 12"/></svg>`
        }
    };

    container.innerHTML = filtered
        .map((item) => {
            const st = stylesByType[item.type] || stylesByType.activation;
            return `
        <div class="border ${st.bg} rounded-xl p-2.5 transition">
          <div class="flex items-start justify-between gap-2">
            <div class="flex items-start gap-2.5 min-w-0">
              <div class="mt-0.5 shrink-0">${st.icon}</div>
              <div class="min-w-0">
                <div class="flex items-center gap-1.5 flex-wrap">
                  <span class="text-[10px] font-bold uppercase tracking-wider px-1.5 py-0.2 rounded ${st.badge}">${item.tag}</span>
                  <span class="text-[11px] text-[#647569] font-medium">${item.time}</span>
                  ${item.unread ? '<span class="w-1.5 h-1.5 rounded-full bg-brand-alertBorder" title="Nueva"></span>' : ''}
                </div>
                <p class="text-xs sm:text-[13px] font-semibold text-[#1c2b21] mt-0.5 leading-snug">
                  ${item.title}
                </p>
              </div>
            </div>
            <button
              id="notif-btn-${item.id}"
              type="button"
              onclick="toggleNotifDetail(${item.id})"
              class="text-[11px] font-semibold text-brand-green hover:underline shrink-0 cursor-pointer"
            >
              Detalle ▼
            </button>
          </div>
          <p id="notif-detail-${item.id}" class="hidden text-xs text-[#4b5c50] mt-2 pt-2 border-t border-black/5 leading-relaxed">
            ${item.detail}
          </p>
        </div>
      `;
        })
        .join('');
}

// =========================================================================
// 5. RENDERIZADO DE GRÁFICOS CANVAS DE ALTA PRECISIÓN (HIDPI)
// =========================================================================
function drawLineChart(canvasId, config) {
    const canvas = document.getElementById(canvasId);
    if (!canvas) return;
    const parent = canvas.parentElement;
    const dpr = window.devicePixelRatio || 1;
    const rect = parent.getBoundingClientRect();

    canvas.width = rect.width * dpr;
    canvas.height = rect.height * dpr;

    const ctx = canvas.getContext('2d');
    ctx.scale(dpr, dpr);

    const W = rect.width;
    const H = rect.height;

    // Márgenes internos para ejes y etiquetas
    const pad = { top: 28, right: 24, bottom: 38, left: 54 };
    const plotW = W - pad.left - pad.right;
    const plotH = H - pad.top - pad.bottom;

    ctx.clearRect(0, 0, W, H);

    const { minY, maxY, stepY, values, labels, lineColor, fillTop, fillBottom, thresholds, highlightIndex, highlightTime, highlightText, yTitle, xTitle } = config;

    const getX = (idx) => pad.left + (idx / Math.max(1, values.length - 1)) * plotW;
    const getY = (val) => pad.top + plotH - ((val - minY) / (maxY - minY)) * plotH;

    // 1. Grilla horizontal y etiquetas Y
    ctx.font = '500 11px Inter, sans-serif';
    ctx.textAlign = 'right';
    ctx.textBaseline = 'middle';

    for (let v = minY; v <= maxY; v += stepY) {
        const y = getY(v);
        ctx.strokeStyle = '#edf1ee';
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(pad.left, y);
        ctx.lineTo(W - pad.right, y);
        ctx.stroke();

        ctx.fillStyle = '#5a6d60';
        ctx.fillText(v.toLocaleString('es-AR'), pad.left - 8, y);
    }

    // Título vertical del eje Y
    ctx.save();
    ctx.translate(14, pad.top + plotH / 2);
    ctx.rotate(-Math.PI / 2);
    ctx.textAlign = 'center';
    ctx.fillStyle = '#3f5044';
    ctx.font = '600 11px Inter, sans-serif';
    ctx.fillText(yTitle, 0, 0);
    ctx.restore();

    // 2. Etiquetas del eje X
    ctx.textAlign = 'center';
    ctx.textBaseline = 'top';
    ctx.fillStyle = '#5a6d60';
    ctx.font = '500 11px Inter, sans-serif';

    const labelCount = labels.length;
    labels.forEach((lbl, i) => {
        if (!lbl) return;
        const x = pad.left + (i / Math.max(1, labelCount - 1)) * plotW;
        ctx.fillText(lbl, x, pad.top + plotH + 8);
    });

    // Título del eje X
    ctx.fillStyle = '#3f5044';
    ctx.font = '600 11px Inter, sans-serif';
    ctx.fillText(xTitle, pad.left + plotW / 2, pad.top + plotH + 24);

    // 3. Área sombreada degradada bajo la curva
    const grad = ctx.createLinearGradient(0, pad.top, 0, pad.top + plotH);
    grad.addColorStop(0, fillTop);
    grad.addColorStop(1, fillBottom);

    ctx.beginPath();
    ctx.moveTo(getX(0), pad.top + plotH);
    values.forEach((val, i) => ctx.lineTo(getX(i), getY(val)));
    ctx.lineTo(getX(values.length - 1), pad.top + plotH);
    ctx.closePath();
    ctx.fillStyle = grad;
    ctx.fill();

    // 4. Líneas punteadas de umbrales
    thresholds.forEach((t) => {
        const y = getY(t.value);
        ctx.save();
        ctx.setLineDash([4, 4]);
        ctx.strokeStyle = t.color;
        ctx.lineWidth = 1.4;
        ctx.beginPath();
        ctx.moveTo(pad.left, y);
        ctx.lineTo(W - pad.right, y);
        ctx.stroke();
        ctx.restore();
    });

    // 5. Línea principal de datos
    ctx.strokeStyle = lineColor;
    ctx.lineWidth = 2.2;
    ctx.lineJoin = 'round';
    ctx.lineCap = 'round';
    ctx.beginPath();
    values.forEach((val, i) => {
        const x = getX(i);
        const y = getY(val);
        if (i === 0) ctx.moveTo(x, y);
        else ctx.lineTo(x, y);
    });
    ctx.stroke();

    // 6. Punto destacado y etiqueta flotante estilo tarjeta
    const hx = getX(highlightIndex);
    const hy = getY(values[highlightIndex]);

    ctx.beginPath();
    ctx.arc(hx, hy, 4.5, 0, Math.PI * 2);
    ctx.fillStyle = lineColor;
    ctx.fill();
    ctx.lineWidth = 2;
    ctx.strokeStyle = '#ffffff';
    ctx.stroke();

    // Caja tooltip flotante
    const boxW = 74;
    const boxH = 34;
    let boxX = hx - boxW / 2;
    if (boxX + boxW > W - 4) boxX = W - boxW - 4;
    if (boxX < pad.left) boxX = pad.left;
    const boxY = Math.max(4, hy - boxH - 10);

    // Sombra sutil del tooltip
    ctx.save();
    ctx.shadowColor = 'rgba(0,0,0,0.08)';
    ctx.shadowBlur = 6;
    ctx.shadowOffsetY = 2;
    ctx.fillStyle = '#ffffff';
    roundRect(ctx, boxX, boxY, boxW, boxH, 6);
    ctx.fill();
    ctx.restore();

    ctx.strokeStyle = '#d6e0d8';
    ctx.lineWidth = 1;
    roundRect(ctx, boxX, boxY, boxW, boxH, 6);
    ctx.stroke();

    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillStyle = '#5a6d60';
    ctx.font = '500 10px Inter, sans-serif';
    ctx.fillText(highlightTime, boxX + boxW / 2, boxY + 11);

    ctx.fillStyle = '#19241c';
    ctx.font = '700 11px Inter, sans-serif';
    ctx.fillText(highlightText, boxX + boxW / 2, boxY + 24);
}

function roundRect(ctx, x, y, w, h, r) {
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.arcTo(x + w, y, x + w, y + h, r);
    ctx.arcTo(x + w, y + h, x, y + h, r);
    ctx.arcTo(x, y + h, x, y, r);
    ctx.arcTo(x, y, x + w, y, r);
    ctx.closePath();
}

function renderAllCharts() {
    const radData = chartDatasets.radiation[state.chartRanges.radiation];
    drawLineChart('chart-radiation', {
        minY: 0,
        maxY: 1000,
        stepY: 100,
        values: radData.values,
        labels: radData.labels,
        lineColor: '#3f8f29',
        fillTop: 'rgba(73, 152, 44, 0.35)',
        fillBottom: 'rgba(73, 152, 44, 0.02)',
        thresholds: [
            { value: 800, color: '#ef4444' },
            { value: 350, color: '#49982c' }
        ],
        highlightIndex: radData.highlightIndex,
        highlightTime: radData.highlightTime,
        highlightText: radData.highlightText,
        yTitle: 'Radiación (W/m²)',
        xTitle: radData.xAxisTitle
    });

    const tempData = chartDatasets.temperature[state.chartRanges.temperature];
    drawLineChart('chart-temperature', {
        minY: 20,
        maxY: 34,
        stepY: 2,
        values: tempData.values,
        labels: tempData.labels,
        lineColor: '#f97316',
        fillTop: 'rgba(249, 115, 22, 0.32)',
        fillBottom: 'rgba(249, 115, 22, 0.02)',
        thresholds: [{ value: 26, color: '#f59e0b' }],
        highlightIndex: tempData.highlightIndex,
        highlightTime: tempData.highlightTime,
        highlightText: tempData.highlightText,
        yTitle: 'Temperatura (°C)',
        xTitle: tempData.xAxisTitle
    });
}

// =========================================================================
// 6. INICIALIZACIÓN Y EVENTOS GLOBALES
// =========================================================================
window.addEventListener('resize', () => {
    renderAllCharts();
});

window.addEventListener('DOMContentLoaded', () => {
    // Configurar filtros de notificaciones
    const notifFilters = document.getElementById('notif-filters');
    if (notifFilters) {
        notifFilters.addEventListener('click', (e) => {
            const btn = e.target.closest('button[data-filter]');
            if (!btn) return;
            state.notifFilter = btn.dataset.filter;
            document.querySelectorAll('#notif-filters button').forEach((b) => {
                const active = b === btn;
                b.className = active
                    ? 'px-2.5 py-0.5 rounded-full font-semibold bg-brand-forest text-white transition cursor-pointer'
                    : 'px-2.5 py-0.5 rounded-full font-medium text-[#526356] hover:text-brand-forest transition cursor-pointer';
            });
            renderNotifications();
        });
    }

    // Eventos de pestañas en los gráficos (Hoy / 24 h / 7 días)
    document.querySelectorAll('[data-chart-tabs]').forEach((group) => {
        const chartKey = group.dataset.chartTabs;
        group.addEventListener('click', (e) => {
            const btn = e.target.closest('button[data-range]');
            if (!btn) return;
            state.chartRanges[chartKey] = btn.dataset.range;
            group.querySelectorAll('button').forEach((b) => {
                const active = b === btn;
                b.className = active
                    ? 'px-2.5 py-1 rounded-md text-xs font-semibold bg-brand-green text-white transition cursor-pointer'
                    : 'px-2.5 py-1 rounded-md text-xs font-medium text-[#526356] hover:text-brand-forest transition cursor-pointer';
            });
            renderAllCharts();
        });
    });

    renderNotifications();
    renderAllCharts();
});
