from datetime import datetime, timedelta

from django.test import TestCase

from App.models import Alerta, HistorialMecanismo, Mecanismo
from App.services import (
    asegurar_datos_iniciales,
    cambiar_mecanismo_por_tipo,
    cambiar_modo_invernadero,
    establecer_parametros_cultivo,
)
from Evaluador.evaluador import EvaluadorInvernadero, sincronizar_mecanismo_en_simulador
from Simulador.invernadero import ConfigInvernadero, Medicion, EstadoCortinas, EstadoTecho, Simulador


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
