import json
from datetime import datetime, timedelta

from django.test import Client, SimpleTestCase, TestCase

from Simulador.views import detener_simulator

from .invernadero import (
    AccionInterior,
    ConfigInvernadero,
    Simulador,
    TipoClima,
)


class SimuladorFisicaTests(SimpleTestCase):
    def test_viento_manual_y_independencia_de_mecanismos(self):
        t0 = datetime(2026, 11, 25, 12, 0, 0)
        sim = Simulador(cfg=ConfigInvernadero(), inicio=t0, velocidad=10.0)
        sim.viento_manual = 52.5

        m1 = sim.avanzar(120.0)
        self.assertAlmostEqual(m1.viento_externo, 52.5, places=1)

        sim.accion_ahora(AccionInterior.APERTURA_TECHO)
        sim.accion_ahora(AccionInterior.APERTURA_CORTINAS)
        sim.accion_ahora(AccionInterior.VENTILADORES)
        m2 = sim.avanzar(300.0)
        self.assertAlmostEqual(m2.viento_externo, 52.5, places=1)

    def test_ventisca_aumenta_viento_progresivamente(self):
        t0 = datetime(2026, 11, 25, 12, 0, 0)
        sim = Simulador(cfg=ConfigInvernadero(), inicio=t0, velocidad=10.0)
        viento_inicial = sim.medicion_actual().viento_externo

        sim.clima_ahora(TipoClima.VENTISCA, duracion_h=1.0)
        v_2min = sim.avanzar(120.0).viento_externo
        v_4min = sim.avanzar(120.0).viento_externo
        v_8min = sim.avanzar(240.0).viento_externo

        self.assertGreater(v_2min, viento_inicial)
        self.assertGreater(v_4min, v_2min)
        self.assertGreater(v_8min, v_4min)
        self.assertGreater(v_8min, 60.0)

    def test_mecanismos_reducen_radiacion_y_temperatura(self):
        t0 = datetime(2026, 11, 25, 12, 0, 0)
        cfg = ConfigInvernadero()

        # Caso base cerrado bajo sol del mediodía
        sim_base = Simulador(cfg=cfg, inicio=t0)
        m_cerrado = sim_base.avanzar(3600.0)

        # Caso con media sombra desplegada, cortinas abiertas y ventiladores encendidos
        sim_activo = Simulador(cfg=cfg, inicio=t0)
        sim_activo.accion_ahora(AccionInterior.APERTURA_TECHO)
        sim_activo.accion_ahora(AccionInterior.APERTURA_CORTINAS)
        sim_activo.accion_ahora(AccionInterior.VENTILADORES)
        m_activo = sim_activo.avanzar(3600.0)

        self.assertLess(m_activo.rad_interna, m_cerrado.rad_interna * 0.55)
        self.assertLess(m_activo.temp_interna, m_cerrado.temp_interna)


class SimuladorYEvaluadorApiTests(TestCase):
    def setUp(self):
        self.client = Client()

    def tearDown(self):
        detener_simulator()

    def test_endpoints_simulador_y_evaluador(self):
        r_idx = self.client.get('/simulador/')
        self.assertEqual(r_idx.status_code, 200)

        r_viento = self.client.post(
            '/simulador/api/viento/',
            data=json.dumps({'viento': 55}),
            content_type='application/json',
        )
        self.assertEqual(r_viento.status_code, 200)
        self.assertEqual(r_viento.json()['viento_externo'], 55.0)

        r_est = self.client.get('/simulador/api/estado/')
        self.assertEqual(r_est.status_code, 200)
        est = r_est.json()
        self.assertIn('parametros', est)
        self.assertIn('viento_externo', est)
        self.assertIn('evaluador', est)

        r_ev = self.client.get('/evaluador/api/estado/')
        self.assertEqual(r_ev.status_code, 200)
        self.assertTrue(r_ev.json()['ok'])
