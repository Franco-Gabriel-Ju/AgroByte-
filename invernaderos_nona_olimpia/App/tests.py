import json
from datetime import datetime, timedelta

from django.test import Client, TestCase, override_settings

from App.models import (
    Alerta,
    HistorialClima,
    HistorialMecanismo,
    HistorialParametro,
    Parametro,
    Reporte,
)
from App.services import (
    asegurar_datos_iniciales,
    cambiar_mecanismo_por_tipo,
    registrar_alerta,
    registrar_clima,
    registrar_lectura_sensores,
)
from Simulador.views import detener_simulator, get_simulator


class AppIntegracionTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.t0 = datetime(2026, 11, 25, 12, 0, 0)
        self.inv = asegurar_datos_iniciales(self.t0)

    def tearDown(self):
        detener_simulator()

    def _login_admin(self):
        return self.client.post('/login/', {'username': 'admin', 'contrasena': 'admin123'})

    def test_proteccion_login_y_autenticacion(self):
        resp_anon = self.client.get('/')
        self.assertEqual(resp_anon.status_code, 302)
        self.assertIn('/login/', resp_anon['Location'])

        resp_api_anon = self.client.get('/api/monitor/')
        self.assertEqual(resp_api_anon.status_code, 401)

        resp_bad = self.client.post('/login/', {'username': 'admin', 'contrasena': 'incorrecta'})
        self.assertEqual(resp_bad.status_code, 200)
        self.assertContains(resp_bad, 'Usuario o contraseña incorrectos')

        resp_ok = self._login_admin()
        self.assertEqual(resp_ok.status_code, 302)

        for ruta in ('/', '/historial/', '/alertas/', '/reportes/', '/configuracion/', '/acerca-de/'):
            r = self.client.get(ruta)
            self.assertEqual(r.status_code, 200, f'Falló ruta protegida {ruta}')

    def test_configuracion_guarda_viento_max_y_persistencia(self):
        self._login_admin()
        payload = {
            'cultivo_id': self.inv.cultivo.id,
            'temp_min': 15.0,
            'temp_max': 27.0,
            'rad_min': 280.0,
            'rad_max': 720.0,
            'viento_max': 35.0,
            'tiempo_persistencia_min': 8,
            'modo': 'AUTOMATICO',
        }
        r = self.client.post('/api/configuracion/', data=json.dumps(payload), content_type='application/json')
        self.assertEqual(r.status_code, 200)
        param = Parametro.objects.get(cultivo=self.inv.cultivo)
        self.assertEqual(param.viento_max, 35.0)
        self.assertEqual(param.tiempo_persistencia_min, 8)
        self.assertTrue(HistorialParametro.objects.filter(parametro=param, viento_max=35.0).exists())

    @override_settings(REPORTES_DIR='/tmp/agrobyte_test_reportes')
    def test_reporte_csv_generar_descargar_y_eliminar(self):
        self._login_admin()
        sim = get_simulator()
        fecha_sim = sim.instante
        hoy_iso = fecha_sim.date().isoformat()

        registrar_lectura_sensores(
            self.inv.id,
            grados=26.5,
            radiacion=640.0,
            viento=32.0,
            temp_externa=22.0,
            rad_externa=720.0,
            fecha=fecha_sim,
        )
        registrar_clima(self.inv.id, estado='GRANIZO', temp_externa=16.0, viento_estimado=48.0, fecha=fecha_sim)
        cambiar_mecanismo_por_tipo(self.inv.id, 'MEDIA_SOMBRA', 'DESPLEGADA', 'AUTOMATICO', fecha=fecha_sim)
        cambiar_mecanismo_por_tipo(self.inv.id, 'CORTINAS_LATERALES', 'ABIERTAS', 'AUTOMATICO', fecha=fecha_sim)
        cambiar_mecanismo_por_tipo(self.inv.id, 'CORTINAS_LATERALES', 'CERRADAS', 'AUTOMATICO', fecha=fecha_sim + timedelta(seconds=10))

        resp_gen = self.client.post(
            '/api/reportes/generar/',
            data=json.dumps({'fecha_desde': hoy_iso, 'fecha_hasta': hoy_iso, 'tipo': 'HISTORICO_CONSOLIDADO'}),
            content_type='application/json',
        )
        self.assertEqual(resp_gen.status_code, 200)
        rep_id = resp_gen.json()['reporte']['id']

        resp_dl = self.client.get(f'/reportes/{rep_id}/descargar/')
        self.assertEqual(resp_dl.status_code, 200)
        self.assertIn('text/csv', resp_dl['Content-Type'])
        contenido = b''.join(resp_dl.streaming_content).decode('utf-8-sig')
        self.assertIn('Temporada', contenido)
        self.assertIn('Despliegues_Media_Sombra', contenido)
        self.assertIn('Despliegues_Cortinas_Laterales', contenido)
        self.assertIn('Viento_Promedio_kmh', contenido)
        self.assertIn('Granizo', contenido)

        resp_del = self.client.post(f'/api/reportes/{rep_id}/eliminar/')
        self.assertEqual(resp_del.status_code, 200)
        self.assertFalse(Reporte.objects.filter(id=rep_id).exists())

    def test_apis_historial_y_alertas(self):
        self._login_admin()
        sim = get_simulator()
        registrar_alerta(
            self.inv.id,
            variable='VIENTO',
            valor=55.0,
            descripcion='Viento crítico de prueba',
            fecha=sim.instante,
            nivel='CRITICO',
            categoria='ALERTA',
            titulo='Ráfaga crítica detectada',
        )

        r_hist = self.client.get('/api/historial/?rango=hour')
        self.assertEqual(r_hist.status_code, 200)
        hist_json = r_hist.json()
        self.assertIn('viento', hist_json['series'])
        self.assertTrue(len(hist_json['pronostico']) > 0)
        self.assertIn('viento_kmh', hist_json['pronostico'][0])

        r_al = self.client.get('/api/alertas/?tipo=alert&q=crítica')
        self.assertEqual(r_al.status_code, 200)
        self.assertGreaterEqual(r_al.json()['total'], 1)
