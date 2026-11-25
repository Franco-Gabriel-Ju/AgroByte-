// =========================================================================
// CONFIGURACIÓN DEL INVERNADERO Y CULTIVOS (conectado a /api/configuracion/)
// =========================================================================
const configState = {
    cultivos: [],
    selectedCultivoId: null
};

function getCookie(name) {
    const match = document.cookie.match(new RegExp('(^| )' + name + '=([^;]+)'));
    return match ? decodeURIComponent(match[2]) : '';
}

function showBanner(message, isError = false) {
    const banner = document.getElementById('configAlertBanner');
    if (!banner) return;

    banner.textContent = message;
    banner.className = `alerta-estado activo ${isError ? 'error' : 'exito'}`;
    banner.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

function hideBanner() {
    const banner = document.getElementById('configAlertBanner');
    if (banner) {
        banner.className = 'alerta-estado';
        banner.textContent = '';
    }
}

function mostrarMensajeCultivo(texto, isError = false) {
    const mensajeCultivo = document.getElementById('mensajeCultivo');
    if (!mensajeCultivo) return;
    mensajeCultivo.textContent = texto;
    mensajeCultivo.style.color = isError ? '#c0392b' : '#49982c';
    mensajeCultivo.style.display = 'block';
}

function getFormParamValues() {
    return {
        temp_min: parseFloat(document.getElementById('inputTempMin').value),
        temp_max: parseFloat(document.getElementById('inputTempMax').value),
        rad_min: parseFloat(document.getElementById('inputRadMin').value),
        rad_max: parseFloat(document.getElementById('inputRadMax').value),
        viento_max: parseFloat(document.getElementById('inputVientoMax').value),
        tiempo_persistencia_min: parseInt(document.getElementById('inputPersistencia').value, 10)
    };
}

function applyParamValues(params) {
    if (!params) return;
    document.getElementById('inputTempMin').value = params.temp_min ?? 16;
    document.getElementById('inputTempMax').value = params.temp_max ?? 28;
    document.getElementById('inputRadMin').value = params.rad_min ?? 300;
    document.getElementById('inputRadMax').value = params.rad_max ?? 750;
    document.getElementById('inputVientoMax').value = params.viento_max ?? 40;
    document.getElementById('inputPersistencia').value = params.tiempo_persistencia_min ?? 5;
}

function renderCultivosSelect(cultivos, activeId) {
    const selector = document.getElementById('selectorCultivo');
    if (!selector) return;

    selector.innerHTML = '';
    cultivos.forEach((c) => {
        const opt = document.createElement('option');
        opt.value = String(c.id);
        opt.textContent = `🌱 ${c.nombre}`;
        selector.appendChild(opt);
    });

    const addOpt = document.createElement('option');
    addOpt.value = 'agregar';
    addOpt.textContent = '＋ Agregar nuevo cultivo';
    selector.appendChild(addOpt);

    if (activeId !== null && activeId !== undefined) {
        selector.value = String(activeId);
        configState.selectedCultivoId = String(activeId);
    } else if (cultivos.length > 0) {
        selector.value = String(cultivos[0].id);
        configState.selectedCultivoId = String(cultivos[0].id);
    }
}

async function cargarConfiguracion() {
    try {
        const res = await fetch('/api/configuracion/', {
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
        configState.cultivos = Array.isArray(data.cultivos) ? data.cultivos : [];

        const inv = data.invernadero || {};
        const activeId = inv.cultivo_id || (configState.cultivos[0] && configState.cultivos[0].id);
        renderCultivosSelect(configState.cultivos, activeId);

        if (data.parametros) {
            applyParamValues(data.parametros);
        } else {
            const activeCultivo = configState.cultivos.find((c) => String(c.id) === String(activeId));
            if (activeCultivo && activeCultivo.parametros) {
                applyParamValues(activeCultivo.parametros);
            }
        }

        const selectModo = document.getElementById('selectModo');
        if (selectModo && inv.modo) {
            selectModo.value = inv.modo;
        }
    } catch (err) {
        console.error('Error al cargar configuración:', err);
        showBanner('No se pudo cargar la configuración desde el servidor.', true);
    }
}

async function agregarCultivo() {
    const inputNuevo = document.getElementById('nombreNuevoCultivo');
    const formularioCultivo = document.getElementById('formAgregarCultivo');
    const btnAgregar = document.getElementById('btnAgregarCultivo');
    const nombre = (inputNuevo.value || '').trim();

    if (!nombre) {
        mostrarMensajeCultivo('Ingresá un nombre para el cultivo.', true);
        return;
    }

    const params = getFormParamValues();
    btnAgregar.disabled = true;

    try {
        const res = await fetch('/api/cultivos/', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCookie('csrftoken')
            },
            credentials: 'same-origin',
            body: JSON.stringify({
                nombre,
                ...params
            })
        });

        const data = await res.json().catch(() => ({}));
        if (!res.ok || !data.ok) {
            mostrarMensajeCultivo(data.error || 'No se pudo registrar el cultivo.', true);
            return;
        }

        const nuevoCultivo = data.cultivo;
        configState.cultivos.push(nuevoCultivo);
        configState.cultivos.sort((a, b) => a.nombre.localeCompare(b.nombre, 'es'));

        renderCultivosSelect(configState.cultivos, nuevoCultivo.id);
        applyParamValues(nuevoCultivo.parametros);

        inputNuevo.value = '';
        formularioCultivo.classList.remove('activo');
        mostrarMensajeCultivo('', false);
        document.getElementById('mensajeCultivo').style.display = 'none';
        showBanner(`Cultivo "${nuevoCultivo.nombre}" agregado y seleccionado. Guardá cambios para aplicarlo al invernadero.`, false);
    } catch (err) {
        console.error('Error al agregar cultivo:', err);
        mostrarMensajeCultivo('Error de conexión al registrar el cultivo.', true);
    } finally {
        btnAgregar.disabled = false;
    }
}

async function guardarConfiguracion() {
    hideBanner();
    const selector = document.getElementById('selectorCultivo');
    const btnGuardar = document.getElementById('btnGuardarConfig');

    if (!selector || selector.value === 'agregar' || !selector.value) {
        showBanner('Primero seleccioná o registrá un cultivo válido.', true);
        return;
    }

    const cultivoId = parseInt(selector.value, 10);
    const params = getFormParamValues();
    const modo = document.getElementById('selectModo').value;

    if (
        Number.isNaN(params.temp_min) ||
        Number.isNaN(params.temp_max) ||
        Number.isNaN(params.rad_min) ||
        Number.isNaN(params.rad_max) ||
        Number.isNaN(params.viento_max) ||
        Number.isNaN(params.tiempo_persistencia_min)
    ) {
        showBanner('Completá todos los campos numéricos con valores válidos.', true);
        return;
    }

    if (params.temp_min >= params.temp_max || params.rad_min >= params.rad_max || params.viento_max <= 0 || params.tiempo_persistencia_min < 1) {
        showBanner('Verificá que los mínimos sean menores a los máximos, viento > 0 y persistencia >= 1 min.', true);
        return;
    }

    btnGuardar.disabled = true;

    try {
        const res = await fetch('/api/configuracion/', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': getCookie('csrftoken')
            },
            credentials: 'same-origin',
            body: JSON.stringify({
                cultivo_id: cultivoId,
                ...params,
                modo
            })
        });

        const data = await res.json().catch(() => ({}));
        if (!res.ok || !data.ok) {
            showBanner(data.error || 'No se pudo guardar la configuración.', true);
            return;
        }

        // Actualizar cache local del cultivo modificado
        const target = configState.cultivos.find((c) => c.id === cultivoId);
        if (target) {
            target.parametros = { ...params };
        }

        showBanner(data.mensaje || 'Configuración guardada correctamente en la base de datos.', false);
    } catch (err) {
        console.error('Error al guardar configuración:', err);
        showBanner('Error de conexión al intentar guardar la configuración.', true);
    } finally {
        btnGuardar.disabled = false;
    }
}

window.addEventListener('DOMContentLoaded', () => {
    const selectorCultivo = document.getElementById('selectorCultivo');
    const formularioCultivo = document.getElementById('formAgregarCultivo');
    const inputNuevoCultivo = document.getElementById('nombreNuevoCultivo');

    if (selectorCultivo) {
        selectorCultivo.addEventListener('change', function () {
            hideBanner();
            if (this.value === 'agregar') {
                formularioCultivo.classList.add('activo');
                inputNuevoCultivo.focus();
                if (configState.selectedCultivoId) {
                    this.value = configState.selectedCultivoId;
                }
                return;
            }

            formularioCultivo.classList.remove('activo');
            configState.selectedCultivoId = this.value;
            const selected = configState.cultivos.find((c) => String(c.id) === String(this.value));
            if (selected && selected.parametros) {
                applyParamValues(selected.parametros);
            }
        });
    }

    cargarConfiguracion();
});
