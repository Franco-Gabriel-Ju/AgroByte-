import json
from datetime import datetime, timedelta

from django.test import Client, SimpleTestCase, TestCase

from App.models import (
    Alerta,
    Cultivo,
    HistorialClima,
    HistorialMecanismo,
    HistorialParametro,
    HistorialRadiacion,
    HistorialTemperatura,
    HistorialViento,
    Invernadero,
    Mecanismo,
    Parametro,
    Usuario,
)
from App.services import (
    asegurar_datos_iniciales,
    cambiar_mecanismo_por_tipo,
    establecer_parametros_cultivo,
    registrar_alerta,
    registrar_clima,
    registrar_lectura_sensores,
)
from Evaluador.evaluador import resetear_evaluador
from Simulador.views import detener_simulator, reset_simulator

from .invernadero import (
    AccionInterior,
    ConfigInvernadero,
    EstadoCortinas,
    EstadoTecho,
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
        resetear_evaluador()

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

    def test_api_reset_limpia_historiales_y_alertas(self):
        inv = asegurar_datos_iniciales()
        conteos_config = (
            Usuario.objects.count(),
            Cultivo.objects.count(),
            Parametro.objects.count(),
            HistorialParametro.objects.count(),
            Invernadero.objects.count(),
        )

        t_viejo = datetime(2026, 11, 20, 10, 0, 0)
        registrar_lectura_sensores(
            inv.id,
            grados=25.0,
            radiacion=500.0,
            viento=18.0,
            temp_externa=21.0,
            rad_externa=600.0,
            fecha=t_viejo,
        )
        registrar_clima(inv.id, estado='TORMENTA', temp_externa=19.0, viento_estimado=45.0, fecha=t_viejo)
        cambiar_mecanismo_por_tipo(inv.id, 'MEDIA_SOMBRA', 'DESPLEGADA', 'MANUAL', fecha=t_viejo)
        cambiar_mecanismo_por_tipo(inv.id, 'VENTILACION', 'ENCENDIDO', 'MANUAL', fecha=t_viejo)
        registrar_alerta(
            inv.id,
            variable='VIENTO',
            valor=65.0,
            descripcion='Alerta vieja de prueba antes del reinicio',
            fecha=t_viejo,
            nivel='CRITICO',
            categoria='ALERTA',
            titulo='Alerta vieja pre-reinicio',
        )

        resp_reset = self.client.post('/simulador/api/reset/')
        self.assertEqual(resp_reset.status_code, 200)
        self.assertTrue(resp_reset.json()['ok'])

        self.assertFalse(HistorialTemperatura.objects.filter(invernadero=inv, fecha=t_viejo).exists())
        self.assertFalse(HistorialRadiacion.objects.filter(invernadero=inv, fecha=t_viejo).exists())
        self.assertFalse(HistorialViento.objects.filter(invernadero=inv, fecha=t_viejo).exists())
        self.assertFalse(HistorialClima.objects.filter(invernadero=inv, fecha=t_viejo).exists())
        self.assertFalse(HistorialMecanismo.objects.filter(mecanismo__invernadero=inv, fecha=t_viejo).exists())
        self.assertFalse(Alerta.objects.filter(invernadero=inv, titulo='Alerta vieja pre-reinicio').exists())

        self.assertEqual(Mecanismo.objects.get(invernadero=inv, tipo='MEDIA_SOMBRA').estado, 'RECOGIDA')
        self.assertEqual(Mecanismo.objects.get(invernadero=inv, tipo='VENTILACION').estado, 'APAGADO')

        self.assertEqual(
            (
                Usuario.objects.count(),
                Cultivo.objects.count(),
                Parametro.objects.count(),
                HistorialParametro.objects.count(),
                Invernadero.objects.count(),
            ),
            conteos_config,
        )

        # Con rad_max por encima de la radiación inicial de mediodía, /api/monitor/ debe mostrar estado NORMAL
        establecer_parametros_cultivo(
            id_cultivo=inv.cultivo_id,
            temp_min=16.0,
            temp_max=28.0,
            rad_min=300.0,
            rad_max=950.0,
            viento_max=40.0,
            persistencia_min=5,
        )
        resp_reset_normal = self.client.post('/simulador/api/reset/')
        self.assertEqual(resp_reset_normal.status_code, 200)

        self.client.post('/login/', {'username': 'admin', 'contrasena': 'admin123'})
        resp_monitor = self.client.get('/api/monitor/')
        self.assertEqual(resp_monitor.status_code, 200)
        banner = resp_monitor.json()['banner']
        self.assertEqual(banner['nivel'], 'INFO')
        self.assertEqual(banner['badge'], 'NORMAL')

    def test_api_actuador_pasa_a_manual_actualiza_bd_y_registra_historial(self):
        sim = reset_simulator()
        sim.pausar()
        inv = Invernadero.objects.first()
        self.assertEqual(inv.modo, 'AUTOMATICO')

        # Al iniciar en AUTOMATICO con viento seguro, cortinas quedan ABIERTAS; probamos cerrar cortinas y activar techo/ventiladores
        for mec, estado_req, tipo_bd, estado_bd in (
            ('techo', 'prendido', 'MEDIA_SOMBRA', 'DESPLEGADA'),
            ('cortinas', 'apagado', 'CORTINAS_LATERALES', 'CERRADAS'),
            ('ventiladores', 'prendido', 'VENTILACION', 'ENCENDIDO'),
        ):
            r = self.client.post(
                '/simulador/api/actuador/',
                data=json.dumps({'mecanismo': mec, 'estado': estado_req}),
                content_type='application/json',
            )
            self.assertEqual(r.status_code, 200)
            self.assertEqual(Mecanismo.objects.get(invernadero=inv, tipo=tipo_bd).estado, estado_bd)
            self.assertTrue(
                HistorialMecanismo.objects.filter(
                    mecanismo__invernadero=inv,
                    mecanismo__tipo=tipo_bd,
                    a_que_estado_paso=estado_bd,
                    origen='SIMULADOR',
                ).exists()
            )
            self.assertTrue(
                Alerta.objects.filter(invernadero=inv, variable=tipo_bd, categoria='ACTIVACION').exists()
            )

        inv.refresh_from_db()
        self.assertEqual(inv.modo, 'MANUAL')
        self.assertEqual(sim.invernadero.techo, EstadoTecho.ABIERTO)
        self.assertEqual(sim.invernadero.cortinas, EstadoCortinas.CERRADAS)
        self.assertTrue(sim.invernadero.ventiladores)

    def test_api_clima_severo_genera_alerta_critica_y_se_resuelve_al_volver_a_normal(self):
        sim = reset_simulator()
        sim.pausar()
        inv = Invernadero.objects.first()

        r_granizo = self.client.post(
            '/simulador/api/clima/',
            data=json.dumps({'clima': 'GRANIZO'}),
            content_type='application/json',
        )
        self.assertEqual(r_granizo.status_code, 200)
        self.assertTrue(HistorialClima.objects.filter(invernadero=inv, estado='GRANIZO', es_pronostico=False).exists())
        alerta = Alerta.objects.filter(invernadero=inv, variable='CLIMA', categoria='ALERTA').latest('id')
        self.assertEqual(alerta.nivel, 'CRITICO')
        self.assertFalse(alerta.resuelta)

        r_normal = self.client.post(
            '/simulador/api/clima/',
            data=json.dumps({'clima': 'NORMAL'}),
            content_type='application/json',
        )
        self.assertEqual(r_normal.status_code, 200)
        alerta.refresh_from_db()
        self.assertTrue(alerta.resuelta)
        self.assertTrue(Alerta.objects.filter(id=alerta.id).exists())
