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
// 1. ESTADO GLOBAL EN TIEMPO REAL
// =========================================================================
const POLL_INTERVAL_MS = 1500;

const state = {
    modo: 'AUTOMATICO',
    parametros: {
        temp_min: 16,
        temp_max: 28,
        rad_min: 300,
        rad_max: 750,
        viento_max: 40,
        tiempo_persistencia_min: 5
    },
    mecanismos: {
        VENTILACION: { estado: 'APAGADO', activo: false },
        MEDIA_SOMBRA: { estado: 'RECOGIDA', activo: false },
        CORTINAS_LATERALES: { estado: 'CERRADAS', activo: false }
    },
    evaluador: { timers: {} },
    series: {
        hoy: {
            temperatura: { labels: [], values: [] },
            radiacion: { labels: [], values: [] },
            viento: { labels: [], values: [] }
        },
        '24h': {
            temperatura: { labels: [], values: [] },
            radiacion: { labels: [], values: [] },
            viento: { labels: [], values: [] }
        },
        '7d': {
            temperatura: { labels: [], values: [] },
            radiacion: { labels: [], values: [] },
            viento: { labels: [], values: [] }
        }
    },
    chartRanges: {
        radiation: 'hoy',
        temperature: 'hoy',
        wind: 'hoy'
    },
    notifFilter: 'all',
    notifications: [],
    expandedNotifIds: new Set(),
    isFetching: false,
    pollTimerId: null
};

// =========================================================================
// 2. UTILIDADES
// =========================================================================
function escapeHtml(str) {
    return String(str ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

function getCookie(name) {
    const match = document.cookie.match(new RegExp('(^| )' + name + '=([^;]+)'));
    return match ? decodeURIComponent(match[2]) : '';
}

function formatSeconds(sec) {
    const s = Math.max(0, Math.round(Number(sec) || 0));
    const min = Math.floor(s / 60);
    const rem = s % 60;
    if (min > 0) {
        return `${min}m ${String(rem).padStart(2, '0')}s`;
    }
    return `${rem}s`;
}

// =========================================================================
// 3. POLLING Y SINCRONIZACIÓN CON BACKEND (/api/monitor/)
// =========================================================================
async function fetchMonitorData() {
    if (state.isFetching) return;
    state.isFetching = true;

    try {
        const res = await fetch('/api/monitor/', {
            headers: { 'Accept': 'application/json' },
            credentials: 'same-origin'
        });

        if (res.status === 401) {
            window.location.href = '/login/';
            return;
        }
        if (!res.ok) {
            throw new Error(`HTTP ${res.status}`);
        }

        const data = await res.json();
        applyMonitorData(data);
    } catch (err) {
        updateConnectionStatus(false);
        console.error('Error al consultar /api/monitor/:', err);
    } finally {
        state.isFetching = false;
    }
}

function updateConnectionStatus(online, reloj) {
    const pill = document.getElementById('sim-status-pill');
    const dot = document.getElementById('sim-status-dot');
    const text = document.getElementById('sim-status-text');
    if (!pill || !dot || !text) return;

    if (!online) {
        pill.className = 'inline-flex items-center gap-2 bg-red-50 border border-red-200 text-red-800 px-3.5 py-1.5 rounded-full text-xs font-medium';
        dot.className = 'w-2 h-2 rounded-full bg-red-500';
        text.textContent = 'Sin conexión';
        return;
    }

    if (reloj && reloj.pausado) {
        pill.className = 'inline-flex items-center gap-2 bg-amber-50 border border-amber-200 text-amber-800 px-3.5 py-1.5 rounded-full text-xs font-medium';
        dot.className = 'w-2 h-2 rounded-full bg-amber-500';
        text.textContent = `Simulador pausado (${reloj.velocidad || 1}x)`;
    } else {
        pill.className = 'inline-flex items-center gap-2 bg-[#ebf5e8] border border-[#c9e3c3] text-brand-forest px-3.5 py-1.5 rounded-full text-xs font-medium';
        dot.className = 'w-2 h-2 rounded-full bg-brand-green animate-pulse';
        const vel = reloj && reloj.velocidad ? ` · ${reloj.velocidad}x` : '';
        text.textContent = `Invernadero en línea${vel}`;
    }
}

function applyMonitorData(data) {
    if (!data) return;

    const inv = data.invernadero || {};
    const reloj = data.reloj || {};
    const kpis = data.kpis || {};
    const banner = data.banner || {};
    const parametros = data.parametros || state.parametros;

    state.modo = inv.modo || kpis.modo || 'AUTOMATICO';
    state.parametros = parametros;
    state.mecanismos = data.mecanismos || state.mecanismos;
    state.evaluador = data.evaluador || { timers: {} };
    if (data.series) {
        state.series = data.series;
    }
    state.notifications = Array.isArray(data.notificaciones) ? data.notificaciones : [];

    // Encabezado
    const titleEl = document.getElementById('header-greenhouse-title');
    if (titleEl && inv.nombre) {
        titleEl.textContent = `${inv.nombre} – Monitor de Invernadero`;
    }
    const dateEl = document.getElementById('header-date');
    if (dateEl) dateEl.textContent = reloj.fecha_texto || '--';

    const timeEl = document.getElementById('header-time');
    if (timeEl) timeEl.textContent = reloj.hora_texto || reloj.hora_corta || '--:--';

    updateConnectionStatus(true, reloj);

    // Banner
    renderBanner(banner);

    // KPIs
    const kpiRad = document.getElementById('kpi-radiation');
    if (kpiRad) kpiRad.textContent = kpis.radiacion !== undefined ? `${kpis.radiacion} W/m²` : '-- W/m²';

    const kpiTemp = document.getElementById('kpi-temp');
    if (kpiTemp) kpiTemp.textContent = kpis.temperatura !== undefined ? `${kpis.temperatura} °C` : '-- °C';

    const kpiWind = document.getElementById('kpi-wind');
    if (kpiWind) kpiWind.textContent = kpis.viento !== undefined ? `${kpis.viento} km/h` : '-- km/h';

    const kpiWindFc = document.getElementById('kpi-wind-forecast');
    if (kpiWindFc) {
        const fc = kpis.viento_pronosticado_hoy !== undefined ? `${kpis.viento_pronosticado_hoy} km/h` : '-- km/h';
        kpiWindFc.textContent = `Pronóstico hoy: ${fc}`;
    }

    const kpiWeather = document.getElementById('kpi-weather');
    if (kpiWeather) kpiWeather.textContent = kpis.clima_etiqueta || '--';

    const kpiCrop = document.getElementById('kpi-crop');
    if (kpiCrop) kpiCrop.textContent = kpis.cultivo || inv.cultivo || '--';

    const kpiLastEvent = document.getElementById('kpi-last-event');
    if (kpiLastEvent) kpiLastEvent.textContent = kpis.ultimo_evento || '--:--';

    // Modo + mecanismos
    renderModeAndMechanisms();

    // Leyendas dinámicas de umbrales
    updateChartLegends();

    // Gráficos + notificaciones
    renderAllCharts();
    renderNotifications();
}

function renderBanner(banner) {
    const section = document.getElementById('alert-banner');
    const iconWrap = document.getElementById('banner-icon-wrap');
    const titleEl = document.getElementById('banner-title');
    const badgeEl = document.getElementById('banner-badge');
    const descEl = document.getElementById('banner-desc');
    if (!section || !titleEl || !badgeEl || !descEl) return;

    const nivel = (banner.nivel || 'INFO').toUpperCase();
    const badge = (banner.badge || '').toUpperCase();
    const esAlertaInfo = nivel === 'INFO' && badge.startsWith('ALERTA');

    if (nivel === 'CRITICO') {
        section.className = 'bg-brand-alertBg border border-[#efb7b2] border-l-[6px] border-l-brand-alertBorder rounded-xl px-4 sm:px-5 py-3.5 flex items-start sm:items-center gap-3.5 shadow-xs';
        iconWrap.className = 'text-brand-alertBorder shrink-0 mt-0.5 sm:mt-0';
        titleEl.className = 'text-sm sm:text-[16px] font-bold text-brand-alertText';
        badgeEl.className = 'inline-flex items-center px-2.5 py-0.5 rounded-full text-[11px] font-bold uppercase tracking-wider bg-brand-alertBorder text-white';
        descEl.className = 'text-xs sm:text-[13.5px] text-[#5e211b] mt-0.5';
        iconWrap.innerHTML = `<svg class="w-7 h-7" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>`;
    } else if (nivel === 'ADVERTENCIA') {
        section.className = 'bg-amber-50 border border-amber-300 border-l-[6px] border-l-amber-500 rounded-xl px-4 sm:px-5 py-3.5 flex items-start sm:items-center gap-3.5 shadow-xs';
        iconWrap.className = 'text-amber-600 shrink-0 mt-0.5 sm:mt-0';
        titleEl.className = 'text-sm sm:text-[16px] font-bold text-amber-900';
        badgeEl.className = 'inline-flex items-center px-2.5 py-0.5 rounded-full text-[11px] font-bold uppercase tracking-wider bg-amber-600 text-white';
        descEl.className = 'text-xs sm:text-[13.5px] text-amber-800 mt-0.5';
        iconWrap.innerHTML = `<svg class="w-7 h-7" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>`;
    } else if (esAlertaInfo) {
        section.className = 'bg-sky-50 border border-sky-300 border-l-[6px] border-l-sky-500 rounded-xl px-4 sm:px-5 py-3.5 flex items-start sm:items-center gap-3.5 shadow-xs';
        iconWrap.className = 'text-sky-600 shrink-0 mt-0.5 sm:mt-0';
        titleEl.className = 'text-sm sm:text-[16px] font-bold text-sky-900';
        badgeEl.className = 'inline-flex items-center px-2.5 py-0.5 rounded-full text-[11px] font-bold uppercase tracking-wider bg-sky-600 text-white';
        descEl.className = 'text-xs sm:text-[13.5px] text-sky-800 mt-0.5';
        iconWrap.innerHTML = `<svg class="w-7 h-7" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>`;
    } else {
        section.className = 'bg-[#eaf4e7] border border-[#c9e3c3] border-l-[6px] border-l-brand-green rounded-xl px-4 sm:px-5 py-3.5 flex items-start sm:items-center gap-3.5 shadow-xs';
        iconWrap.className = 'text-brand-green shrink-0 mt-0.5 sm:mt-0';
        titleEl.className = 'text-sm sm:text-[16px] font-bold text-brand-forest';
        badgeEl.className = 'inline-flex items-center px-2.5 py-0.5 rounded-full text-[11px] font-bold uppercase tracking-wider bg-brand-green text-white';
        descEl.className = 'text-xs sm:text-[13.5px] text-[#35553d] mt-0.5';
        iconWrap.innerHTML = `<svg class="w-7 h-7" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.1" stroke-linecap="round" stroke-linejoin="round"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>`;
    }

    titleEl.textContent = banner.titulo || 'Estado del sistema';
    badgeEl.textContent = banner.badge || nivel;
    descEl.textContent = banner.descripcion || '';

    let extraWrap = document.getElementById('banner-extra-alerts');
    if (!extraWrap && descEl.parentElement) {
        extraWrap = document.createElement('div');
        extraWrap.id = 'banner-extra-alerts';
        extraWrap.className = 'hidden mt-2 pt-2 border-t border-black/10 flex flex-wrap items-center gap-1.5';
        descEl.parentElement.appendChild(extraWrap);
    }

    if (extraWrap) {
        const otras = Array.isArray(banner.otras_activas) ? banner.otras_activas : [];
        if (otras.length > 0) {
            const estilosChip = {
                CRITICO: {
                    cls: 'bg-red-100 text-red-900 border border-red-300',
                    prefijo: 'CRÍTICO',
                },
                ADVERTENCIA: {
                    cls: 'bg-amber-100 text-amber-900 border border-amber-300',
                    prefijo: 'ADVERTENCIA',
                },
                INFO: {
                    cls: 'bg-sky-100 text-sky-900 border border-sky-300',
                    prefijo: 'INFO',
                },
            };

            const chipsHtml = otras
                .map((al) => {
                    const nv = String(al.nivel || 'INFO').toUpperCase();
                    const cfg = estilosChip[nv] || estilosChip.INFO;
                    const titulo = al.titulo || al.variable || 'Alerta';
                    const horaTxt = al.hora ? ` (${al.hora})` : '';
                    return `<span class="inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-medium ${cfg.cls}">${escapeHtml(cfg.prefijo)}: ${escapeHtml(titulo)}${escapeHtml(horaTxt)}</span>`;
                })
                .join('');

            extraWrap.innerHTML = `<span class="text-[11px] font-semibold text-[#3f5044] mr-0.5">Otras alertas activas:</span>${chipsHtml}`;
            extraWrap.classList.remove('hidden');
        } else {
            extraWrap.innerHTML = '';
            extraWrap.classList.add('hidden');
        }
    }
}

function updateChartLegends() {
    const p = state.parametros || {};
    const radMaxEl = document.getElementById('legend-rad-max');
    const radMinEl = document.getElementById('legend-rad-min');
    const tempMaxEl = document.getElementById('legend-temp-max');
    const tempMinEl = document.getElementById('legend-temp-min');
    const windMaxEl = document.getElementById('legend-wind-max');

    if (radMaxEl) radMaxEl.textContent = `Límite superior (${p.rad_max ?? '--'} W/m²)`;
    if (radMinEl) radMinEl.textContent = `Límite inferior (${p.rad_min ?? '--'} W/m²)`;
    if (tempMaxEl) tempMaxEl.textContent = `Máxima (${p.temp_max ?? '--'} °C)`;
    if (tempMinEl) tempMinEl.textContent = `Mínima (${p.temp_min ?? '--'} °C)`;
    if (windMaxEl) windMaxEl.textContent = `Límite máximo (${p.viento_max ?? '--'} km/h)`;
}

// =========================================================================
// 4. MODO AUTOMÁTICO / MANUAL Y CONTROL DE MECANISMOS
// =========================================================================
function renderModeAndMechanisms() {
    const isAuto = state.modo === 'AUTOMATICO';
    const btnAuto = document.getElementById('btn-auto');
    const btnManual = document.getElementById('btn-manual');
    const kpiMode = document.getElementById('kpi-mode-value');
    const mechHint = document.getElementById('mech-mode-hint');

    if (btnAuto && btnManual) {
        if (isAuto) {
            btnAuto.className = 'flex items-center gap-1.5 px-3.5 py-1.5 rounded-full text-xs sm:text-[13px] font-semibold transition-all duration-150 bg-brand-green text-white shadow-xs cursor-pointer';
            btnManual.className = 'flex items-center gap-1.5 px-3.5 py-1.5 rounded-full text-xs sm:text-[13px] font-medium text-[#526356] hover:text-brand-forest transition-all duration-150 cursor-pointer';
        } else {
            btnManual.className = 'flex items-center gap-1.5 px-3.5 py-1.5 rounded-full text-xs sm:text-[13px] font-semibold transition-all duration-150 bg-brand-forest text-white shadow-xs cursor-pointer';
            btnAuto.className = 'flex items-center gap-1.5 px-3.5 py-1.5 rounded-full text-xs sm:text-[13px] font-medium text-[#526356] hover:text-brand-forest transition-all duration-150 cursor-pointer';
        }
    }

    if (kpiMode) {
        kpiMode.textContent = isAuto ? 'Automático' : 'Manual';
        kpiMode.className = isAuto
            ? 'text-xl sm:text-[22px] font-bold text-[#19241c] tracking-tight mt-0.5 truncate'
            : 'text-xl sm:text-[22px] font-bold text-amber-600 tracking-tight mt-0.5 truncate';
    }

    if (mechHint) {
        mechHint.textContent = isAuto ? 'Control automático activo' : 'Control manual habilitado';
        mechHint.className = isAuto
            ? 'text-xs font-medium px-2.5 py-1 rounded-full bg-[#f4f6f4] text-[#56685b] border border-brand-line'
            : 'text-xs font-semibold px-2.5 py-1 rounded-full bg-amber-50 text-amber-800 border border-amber-200';
    }

    const timers = (state.evaluador && state.evaluador.timers) || {};

    const configs = [
        {
            key: 'VENTILACION',
            timerOn: timers.encender_ventilacion,
            timerOff: timers.apagar_ventilacion,
            timerOnLabel: 'Encendiendo',
            timerOffLabel: 'Apagando'
        },
        {
            key: 'MEDIA_SOMBRA',
            timerOn: timers.desplegar_media_sombra,
            timerOff: timers.recoger_media_sombra,
            timerOnLabel: 'Desplegando',
            timerOffLabel: 'Recogiendo'
        },
        {
            key: 'CORTINAS_LATERALES',
            timerOn: null,
            timerOff: null,
            timerOnLabel: '',
            timerOffLabel: ''
        }
    ];

    configs.forEach(({ key, timerOn, timerOff, timerOnLabel, timerOffLabel }) => {
        const info = state.mecanismos[key] || { estado: '--', activo: false };
        const active = Boolean(info.activo);

        const dotEl = document.getElementById(`dot-${key}`);
        const statusEl = document.getElementById(`status-${key}`);
        const iconWrap = document.getElementById(`icon-wrap-${key}`);
        const autoPanel = document.getElementById(`auto-panel-${key}`);
        const manualPanel = document.getElementById(`manual-panel-${key}`);
        const pctEl = document.getElementById(`pct-${key}`);
        const barEl = document.getElementById(`bar-${key}`);
        const timerEl = document.getElementById(`timer-${key}`);
        const btnOn = document.getElementById(`btn-on-${key}`);
        const btnOff = document.getElementById(`btn-off-${key}`);

        if (dotEl) {
            dotEl.className = active ? 'w-2 h-2 rounded-full bg-brand-green' : 'w-2 h-2 rounded-full bg-slate-400';
        }
        if (statusEl) {
            statusEl.textContent = info.estado || '--';
            statusEl.className = active ? 'text-xs font-semibold text-brand-green' : 'text-xs font-semibold text-slate-500';
        }
        if (iconWrap) {
            const shapeClass = key === 'VENTILACION' ? 'rounded-full' : 'rounded-xl';
            iconWrap.className = active
                ? `w-11 h-11 ${shapeClass} bg-[#e4f2e1] text-brand-green flex items-center justify-center shrink-0`
                : `w-11 h-11 ${shapeClass} bg-slate-100 text-slate-500 flex items-center justify-center shrink-0`;
        }

        if (autoPanel && manualPanel) {
            autoPanel.classList.toggle('hidden', !isAuto);
            manualPanel.classList.toggle('hidden', isAuto);
        }

        const pct = active ? 100 : 0;
        if (pctEl) pctEl.textContent = `${pct}%`;
        if (barEl) {
            barEl.style.width = `${pct}%`;
            barEl.className = active
                ? 'h-full bg-brand-green rounded-full transition-all duration-300'
                : 'h-full bg-slate-300 rounded-full transition-all duration-300';
        }

        if (timerEl) {
            const activeTimer = (timerOn && timerOn.activo)
                ? { label: timerOnLabel, ...timerOn }
                : ((timerOff && timerOff.activo) ? { label: timerOffLabel, ...timerOff } : null);

            if (isAuto && activeTimer) {
                timerEl.classList.remove('hidden');
                timerEl.textContent = `⏱ ${activeTimer.label} por persistencia (${formatSeconds(activeTimer.restante_s)} restantes)`;
            } else {
                timerEl.classList.add('hidden');
                timerEl.textContent = '';
            }
        }

        if (btnOn && btnOff) {
            btnOn.className = active
                ? 'px-2.5 py-1.5 rounded-lg text-xs font-semibold border border-brand-green bg-brand-green text-white shadow-xs transition cursor-pointer'
                : 'px-2.5 py-1.5 rounded-lg text-xs font-semibold border border-brand-line bg-white text-brand-forest hover:bg-[#eaf4e7] transition cursor-pointer';

            btnOff.className = !active
                ? 'px-2.5 py-1.5 rounded-lg text-xs font-semibold border border-slate-400 bg-slate-600 text-white shadow-xs transition cursor-pointer'
                : 'px-2.5 py-1.5 rounded-lg text-xs font-semibold border border-brand-line bg-white text-[#526356] hover:bg-slate-100 transition cursor-pointer';
        }
    });
}

async function setOperationMode(mode) {
    const modoApi = (mode === 'MANUAL' || mode === 'manual') ? 'MANUAL' : 'AUTOMATICO';
    try {
        const res = await fetch('/api/modo/', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCookie('csrftoken')
            },
            credentials: 'same-origin',
            body: JSON.stringify({ modo: modoApi })
        });
        if (!res.ok) {
            const errData = await res.json().catch(() => ({}));
            throw new Error(errData.error || `HTTP ${res.status}`);
        }
        await fetchMonitorData();
    } catch (err) {
        console.error('Error al cambiar modo:', err);
    }
}

async function controlMechanism(mecanismo, activo) {
    try {
        const res = await fetch('/api/mecanismo/', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCookie('csrftoken')
            },
            credentials: 'same-origin',
            body: JSON.stringify({ mecanismo, activo: Boolean(activo) })
        });
        if (!res.ok) {
            const errData = await res.json().catch(() => ({}));
            throw new Error(errData.error || `HTTP ${res.status}`);
        }
        await fetchMonitorData();
    } catch (err) {
        console.error('Error al operar mecanismo:', err);
    }
}

// =========================================================================
// 5. PANEL DE NOTIFICACIONES
// =========================================================================
async function markAllRead() {
    try {
        const res = await fetch('/api/alertas/leer/', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCookie('csrftoken')
            },
            credentials: 'same-origin'
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        await fetchMonitorData();
    } catch (err) {
        console.error('Error al marcar alertas leídas:', err);
    }
}

function toggleNotifDetail(id) {
    const detailEl = document.getElementById(`notif-detail-${id}`);
    const btnEl = document.getElementById(`notif-btn-${id}`);
    if (!detailEl || !btnEl) return;

    const isHidden = detailEl.classList.contains('hidden');
    detailEl.classList.toggle('hidden', !isHidden);
    btnEl.textContent = isHidden ? 'Ocultar ▲' : 'Detalle ▼';

    if (isHidden) {
        state.expandedNotifIds.add(id);
    } else {
        state.expandedNotifIds.delete(id);
    }
}

function updateUnreadBadge() {
    const unreadCount = state.notifications.filter((n) => n.unread).length;
    const badge = document.getElementById('notif-badge');
    if (!badge) return;

    badge.textContent = unreadCount;
    badge.className = unreadCount > 0
        ? 'inline-flex items-center justify-center px-2 py-0.5 text-[11px] font-bold rounded-full bg-brand-alertBorder text-white'
        : 'inline-flex items-center justify-center px-2 py-0.5 text-[11px] font-bold rounded-full bg-brand-forest text-white';
}

function renderNotifications() {
    const container = document.getElementById('notif-list');
    if (!container) return;

    const filtered = state.notifications.filter(
        (n) => state.notifFilter === 'all' || n.type === state.notifFilter
    );

    updateUnreadBadge();

    if (!filtered.length) {
        container.innerHTML = `
      <div class="text-center py-6 text-xs text-[#647569] bg-[#f9fbf9] rounded-xl border border-dashed border-brand-line">
        No hay notificaciones registradas en esta categoría.
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
            const isExpanded = state.expandedNotifIds.has(item.id);
            const displayTime = item.fecha || item.time || '';
            return `
        <div class="border ${st.bg} rounded-xl p-2.5 transition">
          <div class="flex items-start justify-between gap-2">
            <div class="flex items-start gap-2.5 min-w-0">
              <div class="mt-0.5 shrink-0">${st.icon}</div>
              <div class="min-w-0">
                <div class="flex items-center gap-1.5 flex-wrap">
                  <span class="text-[10px] font-bold uppercase tracking-wider px-1.5 py-0.2 rounded ${st.badge}">${escapeHtml(item.tag)}</span>
                  <span class="text-[11px] text-[#647569] font-medium">${escapeHtml(displayTime)}</span>
                  ${item.unread ? '<span class="w-1.5 h-1.5 rounded-full bg-brand-alertBorder" title="Sin leer"></span>' : ''}
                </div>
                <p class="text-xs sm:text-[13px] font-semibold text-[#1c2b21] mt-0.5 leading-snug">
                  ${escapeHtml(item.title)}
                </p>
              </div>
            </div>
            <button
              id="notif-btn-${item.id}"
              type="button"
              onclick="toggleNotifDetail(${item.id})"
              class="text-[11px] font-semibold text-brand-green hover:underline shrink-0 cursor-pointer"
            >
              ${isExpanded ? 'Ocultar ▲' : 'Detalle ▼'}
            </button>
          </div>
          <p id="notif-detail-${item.id}" class="${isExpanded ? '' : 'hidden'} text-xs text-[#4b5c50] mt-2 pt-2 border-t border-black/5 leading-relaxed">
            ${escapeHtml(item.detail)}
          </p>
        </div>
      `;
        })
        .join('');
}

// =========================================================================
// 6. RENDERIZADO DE GRÁFICOS CANVAS DE ALTA PRECISIÓN (HIDPI)
// =========================================================================
function computeAxisBounds(values, thresholds, defaultMin, defaultMax, targetSteps = 5) {
    const allNums = [...values];
    (thresholds || []).forEach((t) => {
        if (Number.isFinite(t.value)) allNums.push(t.value);
    });

    let minVal = allNums.length ? Math.min(...allNums, defaultMin) : defaultMin;
    let maxVal = allNums.length ? Math.max(...allNums, defaultMax) : defaultMax;

    if (minVal === maxVal) {
        minVal = Math.max(0, minVal - 5);
        maxVal = maxVal + 5;
    }

    const range = maxVal - minVal;
    const rawStep = range / targetSteps;
    const mag = Math.pow(10, Math.floor(Math.log10(rawStep || 1)));
    const norm = rawStep / mag;
    let step;
    if (norm <= 1) step = 1 * mag;
    else if (norm <= 2) step = 2 * mag;
    else if (norm <= 5) step = 5 * mag;
    else step = 10 * mag;

    const minY = Math.floor(minVal / step) * step;
    const maxY = Math.ceil(maxVal / step) * step;
    return { minY, maxY: maxY <= minY ? minY + step : maxY, stepY: step };
}

function drawLineChart(canvasId, config) {
    const canvas = document.getElementById(canvasId);
    if (!canvas) return;
    const parent = canvas.parentElement;
    const dpr = window.devicePixelRatio || 1;
    const rect = parent.getBoundingClientRect();
    if (!rect.width || !rect.height) return;

    canvas.width = rect.width * dpr;
    canvas.height = rect.height * dpr;

    const ctx = canvas.getContext('2d');
    ctx.scale(dpr, dpr);

    const W = rect.width;
    const H = rect.height;

    const pad = { top: 28, right: 20, bottom: 38, left: 54 };
    const plotW = Math.max(10, W - pad.left - pad.right);
    const plotH = Math.max(10, H - pad.top - pad.bottom);

    ctx.clearRect(0, 0, W, H);

    const rawValues = Array.isArray(config.values) ? config.values : [];
    const rawLabels = Array.isArray(config.labels) ? config.labels : [];

    // Manejo seguro cuando aún no hay mediciones
    if (rawValues.length === 0) {
        ctx.fillStyle = '#f9fbf9';
        ctx.fillRect(pad.left, pad.top, plotW, plotH);
        ctx.strokeStyle = '#dce4dd';
        ctx.setLineDash([4, 4]);
        ctx.strokeRect(pad.left, pad.top, plotW, plotH);
        ctx.setLineDash([]);

        ctx.textAlign = 'center';
        ctx.textBaseline = 'middle';
        ctx.fillStyle = '#647569';
        ctx.font = '500 12px Inter, sans-serif';
        ctx.fillText('Esperando mediciones...', pad.left + plotW / 2, pad.top + plotH / 2);
        return;
    }

    // Duplicar único punto para trazar línea sin NaN
    const values = rawValues.length === 1 ? [rawValues[0], rawValues[0]] : rawValues;
    const labels = rawLabels.length === 1
        ? [rawLabels[0] || '', rawLabels[0] || '']
        : rawLabels;

    const thresholds = config.thresholds || [];
    const bounds = computeAxisBounds(values, thresholds, config.defaultMin, config.defaultMax, 5);
    const { minY, maxY, stepY } = bounds;

    const getX = (idx) => pad.left + (idx / Math.max(1, values.length - 1)) * plotW;
    const getY = (val) => pad.top + plotH - ((val - minY) / Math.max(1e-6, maxY - minY)) * plotH;

    // 1. Grilla horizontal y etiquetas Y
    ctx.font = '500 11px Inter, sans-serif';
    ctx.textAlign = 'right';
    ctx.textBaseline = 'middle';

    for (let v = minY; v <= maxY + stepY * 0.001; v += stepY) {
        const y = getY(v);
        ctx.strokeStyle = '#edf1ee';
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(pad.left, y);
        ctx.lineTo(W - pad.right, y);
        ctx.stroke();

        ctx.fillStyle = '#5a6d60';
        const rounded = Math.round(v * 10) / 10;
        ctx.fillText(rounded.toLocaleString('es-AR'), pad.left - 8, y);
    }

    // Título vertical del eje Y
    ctx.save();
    ctx.translate(14, pad.top + plotH / 2);
    ctx.rotate(-Math.PI / 2);
    ctx.textAlign = 'center';
    ctx.fillStyle = '#3f5044';
    ctx.font = '600 11px Inter, sans-serif';
    ctx.fillText(config.yTitle, 0, 0);
    ctx.restore();

    // 2. Etiquetas del eje X (espaciadas para evitar superposición)
    ctx.textAlign = 'center';
    ctx.textBaseline = 'top';
    ctx.fillStyle = '#5a6d60';
    ctx.font = '500 11px Inter, sans-serif';

    const labelCount = labels.length;
    const maxLabels = Math.max(2, Math.floor(plotW / 54));
    const labelStride = Math.max(1, Math.ceil(labelCount / maxLabels));
    labels.forEach((lbl, i) => {
        if (!lbl) return;
        const isFirstOrLast = i === 0 || i === labelCount - 1;
        if (!isFirstOrLast && i % labelStride !== 0) return;
        const x = getX(i);
        ctx.fillText(lbl, x, pad.top + plotH + 8);
    });

    // Título del eje X
    ctx.fillStyle = '#3f5044';
    ctx.font = '600 11px Inter, sans-serif';
    ctx.fillText(config.xTitle, pad.left + plotW / 2, pad.top + plotH + 24);

    // 3. Área sombreada degradada bajo la curva
    const grad = ctx.createLinearGradient(0, pad.top, 0, pad.top + plotH);
    grad.addColorStop(0, config.fillTop);
    grad.addColorStop(1, config.fillBottom);

    ctx.beginPath();
    ctx.moveTo(getX(0), pad.top + plotH);
    values.forEach((val, i) => ctx.lineTo(getX(i), getY(val)));
    ctx.lineTo(getX(values.length - 1), pad.top + plotH);
    ctx.closePath();
    ctx.fillStyle = grad;
    ctx.fill();

    // 4. Líneas punteadas de umbrales
    thresholds.forEach((t) => {
        if (!Number.isFinite(t.value)) return;
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
    ctx.strokeStyle = config.lineColor;
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

    // 6. Punto destacado (último punto) y tooltip flotante
    const highlightIndex = values.length - 1;
    const hx = getX(highlightIndex);
    const hy = getY(values[highlightIndex]);

    ctx.beginPath();
    ctx.arc(hx, hy, 4.5, 0, Math.PI * 2);
    ctx.fillStyle = config.lineColor;
    ctx.fill();
    ctx.lineWidth = 2;
    ctx.strokeStyle = '#ffffff';
    ctx.stroke();

    const lastLabel = rawLabels[rawLabels.length - 1] || '--:--';
    const lastVal = rawValues[rawValues.length - 1];
    const highlightText = `${lastVal} ${config.unit}`;

    const boxW = Math.max(76, highlightText.length * 7 + 16);
    const boxH = 34;
    let boxX = hx - boxW / 2;
    if (boxX + boxW > W - 4) boxX = W - boxW - 4;
    if (boxX < pad.left) boxX = pad.left;
    const boxY = Math.max(4, hy - boxH - 10);

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
    ctx.fillText(lastLabel, boxX + boxW / 2, boxY + 11);

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

function getRangeTitle(rangeKey, suffix7d) {
    if (rangeKey === '24h') return 'Últimas 24 horas';
    if (rangeKey === '7d') return `Últimos 7 días (${suffix7d})`;
    return 'Hoy';
}

function renderAllCharts() {
    const p = state.parametros || {};

    // 1. Radiación
    const radRange = state.chartRanges.radiation;
    const radSerie = (state.series[radRange] && state.series[radRange].radiacion) || { labels: [], values: [] };
    drawLineChart('chart-radiation', {
        defaultMin: 0,
        defaultMax: Math.max(900, (p.rad_max || 750) + 100),
        values: radSerie.values || [],
        labels: radSerie.labels || [],
        lineColor: '#3f8f29',
        fillTop: 'rgba(73, 152, 44, 0.35)',
        fillBottom: 'rgba(73, 152, 44, 0.02)',
        thresholds: [
            { value: Number(p.rad_max), color: '#ef4444' },
            { value: Number(p.rad_min), color: '#49982c' }
        ],
        unit: 'W/m²',
        yTitle: 'Radiación (W/m²)',
        xTitle: getRangeTitle(radRange, 'máxima diaria')
    });

    // 2. Temperatura
    const tempRange = state.chartRanges.temperature;
    const tempSerie = (state.series[tempRange] && state.series[tempRange].temperatura) || { labels: [], values: [] };
    drawLineChart('chart-temperature', {
        defaultMin: Math.min(10, (p.temp_min || 16) - 4),
        defaultMax: Math.max(34, (p.temp_max || 28) + 4),
        values: tempSerie.values || [],
        labels: tempSerie.labels || [],
        lineColor: '#f97316',
        fillTop: 'rgba(249, 115, 22, 0.32)',
        fillBottom: 'rgba(249, 115, 22, 0.02)',
        thresholds: [
            { value: Number(p.temp_max), color: '#ef4444' },
            { value: Number(p.temp_min), color: '#0284c7' }
        ],
        unit: '°C',
        yTitle: 'Temperatura (°C)',
        xTitle: getRangeTitle(tempRange, 'máxima diaria')
    });

    // 3. Viento
    const windRange = state.chartRanges.wind;
    const windSerie = (state.series[windRange] && state.series[windRange].viento) || { labels: [], values: [] };
    drawLineChart('chart-wind', {
        defaultMin: 0,
        defaultMax: Math.max(50, (p.viento_max || 40) + 10),
        values: windSerie.values || [],
        labels: windSerie.labels || [],
        lineColor: '#0284c7',
        fillTop: 'rgba(2, 132, 199, 0.28)',
        fillBottom: 'rgba(2, 132, 199, 0.02)',
        thresholds: [
            { value: Number(p.viento_max), color: '#ef4444' }
        ],
        unit: 'km/h',
        yTitle: 'Viento (km/h)',
        xTitle: getRangeTitle(windRange, 'ráfaga máxima')
    });
}

// =========================================================================
// 7. INICIALIZACIÓN Y EVENTOS GLOBALES
// =========================================================================
window.addEventListener('resize', () => {
    renderAllCharts();
});

window.addEventListener('DOMContentLoaded', () => {
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

    fetchMonitorData();
    state.pollTimerId = setInterval(fetchMonitorData, POLL_INTERVAL_MS);
});
