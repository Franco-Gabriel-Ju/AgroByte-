from datetime import datetime, timedelta

from django.test import TestCase

from App.models import Alerta, HistorialMecanismo, Mecanismo
from App.services import (
    asegurar_datos_iniciales,
    cambiar_mecanismo_por_tipo,
    cambiar_modo_invernadero,
    establecer_parametros_cultivo,
    registrar_alerta,
)
from Evaluador.evaluador import EvaluadorInvernadero, resetear_evaluador, sincronizar_mecanismo_en_simulador
from Simulador.invernadero import ConfigInvernadero, Medicion, EstadoCortinas, EstadoTecho, Simulador
from Simulador.views import detener_simulator


def _medicion(
    instante: datetime,
    temp_int: float = 24.0,
    rad_int: float = 500.0,
    viento: float = 15.0,
    techo: EstadoTecho = EstadoTecho.CERRADO,
    cortinas: EstadoCortinas = EstadoCortinas.CERRADAS,
    ventiladores: bool = False,
    eventos: tuple[str, ...] = (),
) -> Medicion:
    return Medicion(
        instante=instante,
        seg_simulados=0.0,
        seg_reales=0.0,
        velocidad=30.0,
        pausado=False,
        temp_externa=20.0,
        temp_interna=temp_int,
        rad_externa=rad_int / 0.9,
        rad_interna=rad_int,
        viento_externo=viento,
        techo=techo,
        cortinas=cortinas,
        ventiladores=ventiladores,
        eventos_activos=eventos,
    )


class EvaluadorTests(TestCase):
    def setUp(self):
        self.t0 = datetime(2026, 11, 25, 12, 0, 0)
        self.inv = asegurar_datos_iniciales(self.t0)
        establecer_parametros_cultivo(
            id_cultivo=self.inv.cultivo.id,
            temp_min=16.0,
            temp_max=28.0,
            rad_min=300.0,
            rad_max=750.0,
            viento_max=40.0,
            persistencia_min=5,
            fecha=self.t0,
        )
        self.evaluador = EvaluadorInvernadero()
        self.sim = Simulador(cfg=ConfigInvernadero(), inicio=self.t0)

    def tearDown(self):
        detener_simulator()
        resetear_evaluador()

    def test_viento_critico_cierra_cortinas_y_recoge_media_sombra_de_emergencia(self):
        cambiar_mecanismo_por_tipo(self.inv.id, 'MEDIA_SOMBRA', 'DESPLEGADA', 'MANUAL', self.t0)
        cambiar_mecanismo_por_tipo(self.inv.id, 'CORTINAS_LATERALES', 'ABIERTAS', 'MANUAL', self.t0)
        sincronizar_mecanismo_en_simulador(self.sim, 'MEDIA_SOMBRA', 'DESPLEGADA')
        sincronizar_mecanismo_en_simulador(self.sim, 'CORTINAS_LATERALES', 'ABIERTAS')

        # Viento supera umbral de 40 km/h -> acción inmediata de seguridad
        t1 = self.t0 + timedelta(seconds=30)
        self.evaluador.evaluar(_medicion(t1, viento=55.0), sim=self.sim, invernadero_id=self.inv.id)

        sombra = Mecanismo.objects.get(invernadero=self.inv, tipo='MEDIA_SOMBRA')
        cortinas = Mecanismo.objects.get(invernadero=self.inv, tipo='CORTINAS_LATERALES')
        self.assertEqual(sombra.estado, 'RECOGIDA')
        self.assertEqual(cortinas.estado, 'CERRADAS')
        self.assertEqual(self.sim.invernadero.techo, EstadoTecho.CERRADO)
        self.assertEqual(self.sim.invernadero.cortinas, EstadoCortinas.CERRADAS)
        self.assertTrue(Alerta.objects.filter(invernadero=self.inv, variable='VIENTO', nivel='CRITICO').exists())
        self.assertTrue(HistorialMecanismo.objects.filter(mecanismo=sombra, origen='AUTOMATICO', fecha=t1).exists())

        # Cuando el viento baja <= 40 km/h, cortinas laterales se abren automáticamente
        t2 = t1 + timedelta(minutes=2)
        self.evaluador.evaluar(_medicion(t2, viento=20.0), sim=self.sim, invernadero_id=self.inv.id)
        cortinas.refresh_from_db()
        self.assertEqual(cortinas.estado, 'ABIERTAS')

    def test_persistencia_temporal_filtra_fluctuacion_y_despliega_cuando_persiste(self):
        # 1. Nube/pico pasajero de 3 min (< 5 min): NO debe desplegar media sombra
        self.evaluador.evaluar(_medicion(self.t0, rad_int=820.0, viento=15.0), sim=self.sim, invernadero_id=self.inv.id)
        self.evaluador.evaluar(_medicion(self.t0 + timedelta(minutes=3), rad_int=820.0, viento=15.0), sim=self.sim, invernadero_id=self.inv.id)
        sombra = Mecanismo.objects.get(invernadero=self.inv, tipo='MEDIA_SOMBRA')
        self.assertEqual(sombra.estado, 'RECOGIDA')
        self.assertIsNotNone(self.evaluador.timer_desplegar_sombra)

        # Vuelve a valores normales -> cancela timer
        self.evaluador.evaluar(_medicion(self.t0 + timedelta(minutes=4), rad_int=600.0, viento=15.0), sim=self.sim, invernadero_id=self.inv.id)
        self.assertIsNone(self.evaluador.timer_desplegar_sombra)
        sombra.refresh_from_db()
        self.assertEqual(sombra.estado, 'RECOGIDA')

        # 2. Exceso sostenido >= 5 min -> despliega automáticamente
        t_ini = self.t0 + timedelta(minutes=10)
        self.evaluador.evaluar(_medicion(t_ini, rad_int=830.0, viento=15.0), sim=self.sim, invernadero_id=self.inv.id)
        t_fin = t_ini + timedelta(minutes=5, seconds=10)
        self.evaluador.evaluar(_medicion(t_fin, rad_int=830.0, viento=15.0), sim=self.sim, invernadero_id=self.inv.id)

        sombra.refresh_from_db()
        self.assertEqual(sombra.estado, 'DESPLEGADA')
        self.assertEqual(self.sim.invernadero.techo, EstadoTecho.ABIERTO)

        # 3. Condición por debajo de rad_min y temp_min sostenida >= 5 min -> recoge automáticamente
        t_bajo_ini = t_fin + timedelta(minutes=1)
        self.evaluador.evaluar(_medicion(t_bajo_ini, temp_int=14.0, rad_int=200.0, viento=15.0), sim=self.sim, invernadero_id=self.inv.id)
        t_bajo_fin = t_bajo_ini + timedelta(minutes=5, seconds=10)
        self.evaluador.evaluar(_medicion(t_bajo_fin, temp_int=14.0, rad_int=200.0, viento=15.0), sim=self.sim, invernadero_id=self.inv.id)
        sombra.refresh_from_db()
        self.assertEqual(sombra.estado, 'RECOGIDA')

    def test_modo_manual_no_acciona_mecanismos_pero_genera_alertas_y_recomendaciones(self):
        cambiar_modo_invernadero(self.inv.id, 'MANUAL', fecha=self.t0)
        t1 = self.t0 + timedelta(minutes=6)
        self.evaluador.evaluar(_medicion(t1, temp_int=32.0, viento=50.0), sim=self.sim, invernadero_id=self.inv.id)

        cortinas = Mecanismo.objects.get(invernadero=self.inv, tipo='CORTINAS_LATERALES')
        self.assertEqual(cortinas.estado, 'CERRADAS')
        self.assertTrue(Alerta.objects.filter(invernadero=self.inv, categoria='ALERTA').exists())
        self.assertTrue(Alerta.objects.filter(invernadero=self.inv, categoria='RECOMENDACION').exists())

    def test_radiacion_baja_advertencia_y_recogido_sombra_tarde_nublada(self):
        cambiar_mecanismo_por_tipo(self.inv.id, 'MEDIA_SOMBRA', 'DESPLEGADA', 'MANUAL', self.t0)
        sincronizar_mecanismo_en_simulador(self.sim, 'MEDIA_SOMBRA', 'DESPLEGADA')

        # Tarde nublada: rad_int < rad_min (300) con temperatura normal dentro de [temp_min, temp_max]
        t_ini = self.t0 + timedelta(minutes=1)
        self.evaluador.evaluar(_medicion(t_ini, temp_int=22.0, rad_int=200.0, viento=15.0), sim=self.sim, invernadero_id=self.inv.id)

        alerta_rad = Alerta.objects.filter(invernadero=self.inv, variable='RADIACION', categoria='ALERTA').first()
        self.assertIsNotNone(alerta_rad)
        self.assertEqual(alerta_rad.nivel, 'ADVERTENCIA')

        # Tras persistencia >= 5 min con temp_int <= temp_max, la media sombra se recoge automáticamente
        t_fin = t_ini + timedelta(minutes=5, seconds=10)
        self.evaluador.evaluar(_medicion(t_fin, temp_int=22.0, rad_int=200.0, viento=15.0), sim=self.sim, invernadero_id=self.inv.id)

        sombra = Mecanismo.objects.get(invernadero=self.inv, tipo='MEDIA_SOMBRA')
        self.assertEqual(sombra.estado, 'RECOGIDA')
        self.assertEqual(self.sim.invernadero.techo, EstadoTecho.CERRADO)

    def test_alertas_se_resuelven_al_volver_a_rango_y_tras_reinicio_evaluador(self):
        # 1. Alerta de temperatura alta
        self.evaluador.evaluar(
            _medicion(self.t0, temp_int=30.0, rad_int=500.0, viento=15.0),
            sim=self.sim,
            invernadero_id=self.inv.id,
        )
        alerta_temp = Alerta.objects.get(invernadero=self.inv, variable='TEMPERATURA', categoria='ALERTA')
        self.assertFalse(alerta_temp.resuelta)

        # 2. Dentro de la banda de histéresis (> temp_max - 0.5 = 27.5) sigue abierta
        self.evaluador.evaluar(
            _medicion(self.t0 + timedelta(minutes=1), temp_int=27.8, rad_int=500.0, viento=15.0),
            sim=self.sim,
            invernadero_id=self.inv.id,
        )
        alerta_temp.refresh_from_db()
        self.assertFalse(alerta_temp.resuelta)

        # 3. Al bajar a rango normal (<= 27.5), se resuelve sin borrarse del historial
        self.evaluador.evaluar(
            _medicion(self.t0 + timedelta(minutes=2), temp_int=24.0, rad_int=500.0, viento=15.0),
            sim=self.sim,
            invernadero_id=self.inv.id,
        )
        alerta_temp.refresh_from_db()
        self.assertTrue(alerta_temp.resuelta)
        self.assertTrue(Alerta.objects.filter(id=alerta_temp.id).exists())

        # 4. Alerta vieja persistida en BD (p. ej. tras reinicio del servidor) se resuelve con lectura normal
        alerta_viento = registrar_alerta(
            id_invernadero=self.inv.id,
            variable='VIENTO',
            valor=55.0,
            descripcion='Alerta vieja de viento antes de reiniciar',
            fecha=self.t0,
            nivel='CRITICO',
            categoria='ALERTA',
            titulo='Viento crítico previo',
        )
        nuevo_evaluador = EvaluadorInvernadero()
        nuevo_evaluador.evaluar(
            _medicion(self.t0 + timedelta(minutes=3), temp_int=24.0, rad_int=500.0, viento=12.0),
            sim=self.sim,
            invernadero_id=self.inv.id,
        )
        alerta_viento.refresh_from_db()
        self.assertTrue(alerta_viento.resuelta)

        # 5. Alerta de radiación baja diurna se resuelve automáticamente al llegar la noche
        t_dia = datetime(2026, 11, 25, 12, 0, 0)
        nuevo_evaluador.evaluar(
            _medicion(t_dia, temp_int=22.0, rad_int=200.0, viento=12.0),
            sim=self.sim,
            invernadero_id=self.inv.id,
        )
        alerta_rad = Alerta.objects.get(invernadero=self.inv, variable='RADIACION', categoria='ALERTA')
        self.assertFalse(alerta_rad.resuelta)

        t_noche = datetime(2026, 11, 25, 21, 0, 0)
        nuevo_evaluador.evaluar(
            _medicion(t_noche, temp_int=20.0, rad_int=0.0, viento=12.0),
            sim=self.sim,
            invernadero_id=self.inv.id,
        )
        alerta_rad.refresh_from_db()
        self.assertTrue(alerta_rad.resuelta)

    def test_ciclo_alertas_niveles_e_histeresis_todas_las_variables(self):
        t = self.t0
        # Temperatura alta moderada (ADVERTENCIA) -> normaliza
        self.evaluador.evaluar(_medicion(t, temp_int=29.0), sim=self.sim, invernadero_id=self.inv.id)
        al_t_mod = Alerta.objects.filter(invernadero=self.inv, variable='TEMPERATURA', categoria='ALERTA').latest('id')
        self.assertEqual(al_t_mod.nivel, 'ADVERTENCIA')
        self.assertFalse(al_t_mod.resuelta)

        t += timedelta(minutes=1)
        self.evaluador.evaluar(_medicion(t, temp_int=24.0), sim=self.sim, invernadero_id=self.inv.id)
        al_t_mod.refresh_from_db()
        self.assertTrue(al_t_mod.resuelta)

        # Temperatura alta crítica (CRITICO) -> normaliza
        t += timedelta(minutes=1)
        self.evaluador.evaluar(_medicion(t, temp_int=31.5), sim=self.sim, invernadero_id=self.inv.id)
        al_t_crit = Alerta.objects.filter(invernadero=self.inv, variable='TEMPERATURA', categoria='ALERTA').latest('id')
        self.assertEqual(al_t_crit.nivel, 'CRITICO')
        self.assertFalse(al_t_crit.resuelta)

        t += timedelta(minutes=1)
        self.evaluador.evaluar(_medicion(t, temp_int=24.0), sim=self.sim, invernadero_id=self.inv.id)
        al_t_crit.refresh_from_db()
        self.assertTrue(al_t_crit.resuelta)

        # Temperatura baja moderada (ADVERTENCIA), histéresis (< 16.5), normal (>= 16.5)
        t += timedelta(minutes=1)
        self.evaluador.evaluar(_medicion(t, temp_int=15.0), sim=self.sim, invernadero_id=self.inv.id)
        al_tb_mod = Alerta.objects.filter(invernadero=self.inv, variable='TEMPERATURA', categoria='ALERTA').latest('id')
        self.assertEqual(al_tb_mod.nivel, 'ADVERTENCIA')
        self.assertFalse(al_tb_mod.resuelta)

        t += timedelta(minutes=1)
        self.evaluador.evaluar(_medicion(t, temp_int=16.3), sim=self.sim, invernadero_id=self.inv.id)
        al_tb_mod.refresh_from_db()
        self.assertFalse(al_tb_mod.resuelta)

        t += timedelta(minutes=1)
        self.evaluador.evaluar(_medicion(t, temp_int=17.0), sim=self.sim, invernadero_id=self.inv.id)
        al_tb_mod.refresh_from_db()
        self.assertTrue(al_tb_mod.resuelta)

        # Temperatura baja crítica (CRITICO) -> normaliza
        t += timedelta(minutes=1)
        self.evaluador.evaluar(_medicion(t, temp_int=12.5), sim=self.sim, invernadero_id=self.inv.id)
        al_tb_crit = Alerta.objects.filter(invernadero=self.inv, variable='TEMPERATURA', categoria='ALERTA').latest('id')
        self.assertEqual(al_tb_crit.nivel, 'CRITICO')
        t += timedelta(minutes=1)
        self.evaluador.evaluar(_medicion(t, temp_int=17.0), sim=self.sim, invernadero_id=self.inv.id)
        al_tb_crit.refresh_from_db()
        self.assertTrue(al_tb_crit.resuelta)

        # Radiación alta (> 750), histéresis (> 720), normal (<= 720)
        t += timedelta(minutes=1)
        self.evaluador.evaluar(_medicion(t, rad_int=800.0), sim=self.sim, invernadero_id=self.inv.id)
        al_ra = Alerta.objects.filter(invernadero=self.inv, variable='RADIACION', categoria='ALERTA').latest('id')
        self.assertEqual(al_ra.nivel, 'ADVERTENCIA')
        t += timedelta(minutes=1)
        self.evaluador.evaluar(_medicion(t, rad_int=730.0), sim=self.sim, invernadero_id=self.inv.id)
        al_ra.refresh_from_db()
        self.assertFalse(al_ra.resuelta)
        t += timedelta(minutes=1)
        self.evaluador.evaluar(_medicion(t, rad_int=700.0), sim=self.sim, invernadero_id=self.inv.id)
        al_ra.refresh_from_db()
        self.assertTrue(al_ra.resuelta)

        # Radiación baja diurna (< 300), histéresis (< 315), normal (>= 315)
        t += timedelta(minutes=1)
        self.evaluador.evaluar(_medicion(t, rad_int=200.0), sim=self.sim, invernadero_id=self.inv.id)
        al_rb = Alerta.objects.filter(invernadero=self.inv, variable='RADIACION', categoria='ALERTA').latest('id')
        self.assertEqual(al_rb.nivel, 'ADVERTENCIA')
        t += timedelta(minutes=1)
        self.evaluador.evaluar(_medicion(t, rad_int=310.0), sim=self.sim, invernadero_id=self.inv.id)
        al_rb.refresh_from_db()
        self.assertFalse(al_rb.resuelta)
        t += timedelta(minutes=1)
        self.evaluador.evaluar(_medicion(t, rad_int=320.0), sim=self.sim, invernadero_id=self.inv.id)
        al_rb.refresh_from_db()
        self.assertTrue(al_rb.resuelta)

        # Viento crítico (> 40), histéresis (> 38), normal (<= 38)
        t += timedelta(minutes=1)
        self.evaluador.evaluar(_medicion(t, viento=45.0), sim=self.sim, invernadero_id=self.inv.id)
        al_v = Alerta.objects.filter(invernadero=self.inv, variable='VIENTO', categoria='ALERTA').latest('id')
        self.assertEqual(al_v.nivel, 'CRITICO')
        t += timedelta(minutes=1)
        self.evaluador.evaluar(_medicion(t, viento=39.0), sim=self.sim, invernadero_id=self.inv.id)
        al_v.refresh_from_db()
        self.assertFalse(al_v.resuelta)
        t += timedelta(minutes=1)
        self.evaluador.evaluar(_medicion(t, viento=35.0), sim=self.sim, invernadero_id=self.inv.id)
        al_v.refresh_from_db()
        self.assertTrue(al_v.resuelta)

        # Clima severo: Ventisca y Granizo
        for ev in ('Ventisca', 'Granizo'):
            t += timedelta(minutes=1)
            self.evaluador.evaluar(_medicion(t, eventos=(ev,)), sim=self.sim, invernadero_id=self.inv.id)
            al_c = Alerta.objects.filter(invernadero=self.inv, variable='CLIMA', categoria='ALERTA').latest('id')
            self.assertEqual(al_c.nivel, 'CRITICO')
            self.assertFalse(al_c.resuelta)

            t += timedelta(minutes=1)
            self.evaluador.evaluar(_medicion(t, eventos=()), sim=self.sim, invernadero_id=self.inv.id)
            al_c.refresh_from_db()
            self.assertTrue(al_c.resuelta)

        # Todas las alertas permanecen en historial
        self.assertEqual(
            Alerta.objects.filter(invernadero=self.inv, categoria='ALERTA', resuelta=True).count(),
            9,
        )

    def test_radiacion_baja_no_dispara_alertas_en_horario_nocturno(self):
        for hora, minuto in ((5, 30), (6, 29), (19, 30), (22, 15)):
            t_noche = datetime(2026, 11, 25, hora, minuto, 0)
            self.evaluador.evaluar(
                _medicion(t_noche, temp_int=20.0, rad_int=0.0, viento=10.0),
                sim=self.sim,
                invernadero_id=self.inv.id,
            )
        self.assertEqual(Alerta.objects.filter(invernadero=self.inv, variable='RADIACION').count(), 0)

        t_amanecer = datetime(2026, 11, 25, 6, 30, 0)
        self.evaluador.evaluar(
            _medicion(t_amanecer, temp_int=20.0, rad_int=100.0, viento=10.0),
            sim=self.sim,
            invernadero_id=self.inv.id,
        )
        al = Alerta.objects.get(invernadero=self.inv, variable='RADIACION', categoria='ALERTA')
        self.assertEqual(al.nivel, 'ADVERTENCIA')

    def test_ventilacion_persistencia_fluctuacion_y_apagado_en_temp_media(self):
        # 1. Pico pasajero < 5 min no enciende ventilación
        self.evaluador.evaluar(_medicion(self.t0, temp_int=30.0), sim=self.sim, invernadero_id=self.inv.id)
        self.evaluador.evaluar(_medicion(self.t0 + timedelta(minutes=3), temp_int=30.0), sim=self.sim, invernadero_id=self.inv.id)
        vent = Mecanismo.objects.get(invernadero=self.inv, tipo='VENTILACION')
        self.assertEqual(vent.estado, 'APAGADO')
        self.assertIsNotNone(self.evaluador.timer_encender_vent)

        # Vuelve a rango normal -> reinicia timer
        self.evaluador.evaluar(_medicion(self.t0 + timedelta(minutes=4), temp_int=25.0), sim=self.sim, invernadero_id=self.inv.id)
        self.assertIsNone(self.evaluador.timer_encender_vent)
        vent.refresh_from_db()
        self.assertEqual(vent.estado, 'APAGADO')

        # 2. Exceso sostenido >= 5 min -> enciende ventilación
        t_ini = self.t0 + timedelta(minutes=10)
        self.evaluador.evaluar(_medicion(t_ini, temp_int=30.0), sim=self.sim, invernadero_id=self.inv.id)
        t_on = t_ini + timedelta(minutes=5, seconds=10)
        self.evaluador.evaluar(_medicion(t_on, temp_int=30.0), sim=self.sim, invernadero_id=self.inv.id)
        vent.refresh_from_db()
        self.assertEqual(vent.estado, 'ENCENDIDO')
        self.assertTrue(self.sim.invernadero.ventiladores)

        # 3. Temperatura por encima de temp_media (22.0) no inicia apagado
        self.evaluador.evaluar(_medicion(t_on + timedelta(minutes=1), temp_int=23.0), sim=self.sim, invernadero_id=self.inv.id)
        self.assertIsNone(self.evaluador.timer_apagar_vent)

        # 4. Temperatura <= temp_media durante 3 min inicia timer, pero no apaga aún
        t_baja = t_on + timedelta(minutes=2)
        self.evaluador.evaluar(_medicion(t_baja, temp_int=21.5), sim=self.sim, invernadero_id=self.inv.id)
        self.evaluador.evaluar(_medicion(t_baja + timedelta(minutes=3), temp_int=21.5), sim=self.sim, invernadero_id=self.inv.id)
        vent.refresh_from_db()
        self.assertEqual(vent.estado, 'ENCENDIDO')
        self.assertIsNotNone(self.evaluador.timer_apagar_vent)

        # 5. Cumplida persistencia >= 5 min -> apaga ventilación
        self.evaluador.evaluar(_medicion(t_baja + timedelta(minutes=5, seconds=10), temp_int=21.5), sim=self.sim, invernadero_id=self.inv.id)
        vent.refresh_from_db()
        self.assertEqual(vent.estado, 'APAGADO')
        self.assertFalse(self.sim.invernadero.ventiladores)

    def test_emergencia_viento_cancela_timers_y_actua_inmediatamente(self):
        cambiar_mecanismo_por_tipo(self.inv.id, 'CORTINAS_LATERALES', 'ABIERTAS', 'MANUAL', self.t0)
        sincronizar_mecanismo_en_simulador(self.sim, 'CORTINAS_LATERALES', 'ABIERTAS')

        # Inicia timer de despliegue de media sombra y es interrumpido por viento crítico
        self.evaluador.evaluar(_medicion(self.t0, rad_int=820.0, viento=15.0), sim=self.sim, invernadero_id=self.inv.id)
        self.assertIsNotNone(self.evaluador.timer_desplegar_sombra)

        t1 = self.t0 + timedelta(seconds=30)
        self.evaluador.evaluar(_medicion(t1, rad_int=820.0, viento=55.0), sim=self.sim, invernadero_id=self.inv.id)
        self.assertIsNone(self.evaluador.timer_desplegar_sombra)
        self.assertEqual(Mecanismo.objects.get(invernadero=self.inv, tipo='CORTINAS_LATERALES').estado, 'CERRADAS')

        # Con media sombra desplegada y timer de recogido iniciado, viento crítico la recoge de inmediato
        cambiar_mecanismo_por_tipo(self.inv.id, 'MEDIA_SOMBRA', 'DESPLEGADA', 'MANUAL', t1)
        sincronizar_mecanismo_en_simulador(self.sim, 'MEDIA_SOMBRA', 'DESPLEGADA')
        t2 = t1 + timedelta(minutes=2)
        self.evaluador.evaluar(_medicion(t2, temp_int=22.0, rad_int=200.0, viento=15.0), sim=self.sim, invernadero_id=self.inv.id)
        self.assertIsNotNone(self.evaluador.timer_recoger_sombra)

        t3 = t2 + timedelta(seconds=20)
        self.evaluador.evaluar(_medicion(t3, temp_int=22.0, rad_int=200.0, viento=55.0), sim=self.sim, invernadero_id=self.inv.id)
        self.assertIsNone(self.evaluador.timer_recoger_sombra)
        self.assertEqual(Mecanismo.objects.get(invernadero=self.inv, tipo='MEDIA_SOMBRA').estado, 'RECOGIDA')

    def test_modo_manual_limpia_timers_y_genera_recomendaciones_por_umbral(self):
        # Activar timers en modo AUTOMATICO (en viento=15 abre cortinas automáticamente)
        self.evaluador.evaluar(_medicion(self.t0, temp_int=30.0, rad_int=820.0, viento=15.0), sim=self.sim, invernadero_id=self.inv.id)
        self.assertIsNotNone(self.evaluador.timer_desplegar_sombra)
        self.assertIsNotNone(self.evaluador.timer_encender_vent)
        estado_cortinas_previo = Mecanismo.objects.get(invernadero=self.inv, tipo='CORTINAS_LATERALES').estado
        self.assertEqual(estado_cortinas_previo, 'ABIERTAS')

        # Cambiar a MANUAL: debe limpiar timers, no modificar mecanismos y crear recomendaciones
        cambiar_modo_invernadero(self.inv.id, 'MANUAL', fecha=self.t0 + timedelta(minutes=1))
        t1 = self.t0 + timedelta(minutes=6)
        self.evaluador.evaluar(_medicion(t1, temp_int=31.0, rad_int=820.0, viento=55.0), sim=self.sim, invernadero_id=self.inv.id)

        self.assertIsNone(self.evaluador.timer_desplegar_sombra)
        self.assertIsNone(self.evaluador.timer_encender_vent)
        self.assertEqual(Mecanismo.objects.get(invernadero=self.inv, tipo='MEDIA_SOMBRA').estado, 'RECOGIDA')
        self.assertEqual(Mecanismo.objects.get(invernadero=self.inv, tipo='VENTILACION').estado, 'APAGADO')
        self.assertEqual(Mecanismo.objects.get(invernadero=self.inv, tipo='CORTINAS_LATERALES').estado, estado_cortinas_previo)

        for var in ('TEMPERATURA', 'RADIACION', 'VIENTO'):
            self.assertTrue(
                Alerta.objects.filter(invernadero=self.inv, variable=var, categoria='RECOMENDACION').exists(),
                f'Falta recomendación para {var}',
            )

        # Temperatura baja también genera recomendación en modo MANUAL
        self.evaluador.evaluar(_medicion(t1 + timedelta(minutes=1), temp_int=12.0, rad_int=500.0, viento=15.0), sim=self.sim, invernadero_id=self.inv.id)
        self.assertTrue(
            Alerta.objects.filter(
                invernadero=self.inv,
                variable='TEMPERATURA',
                categoria='RECOMENDACION',
                titulo='Sugerencia: conservar calor interior',
            ).exists()
        )
