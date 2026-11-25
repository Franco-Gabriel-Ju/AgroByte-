import json
import shutil
import tempfile
from datetime import datetime, timedelta

from django.test import Client, TestCase, override_settings

from App.models import (
    Alerta,
    Cultivo,
    HistorialClima,
    HistorialMecanismo,
    HistorialParametro,
    Invernadero,
    Mecanismo,
    Parametro,
    Reporte,
)
from App.services import (
    asegurar_datos_iniciales,
    cambiar_mecanismo_por_tipo,
    establecer_parametros_cultivo,
    registrar_alerta,
    registrar_clima,
    registrar_lectura_sensores,
    reiniciar_datos_simulacion,
)
from Evaluador.evaluador import obtener_evaluador, resetear_evaluador
from Simulador.invernadero import EstadoCortinas, EstadoTecho, Medicion
from Simulador.views import detener_simulator, get_simulator, reset_simulator


class AppIntegracionTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.t0 = datetime(2026, 11, 25, 12, 0, 0)
        self.inv = asegurar_datos_iniciales(self.t0)

    def tearDown(self):
        detener_simulator()
        resetear_evaluador()

    def _login_admin(self):
        return self.client.post('/login/', {'username': 'admin', 'contrasena': 'admin123'})

    def _crear_medicion(self, instante, temp_int=22.0, rad_int=500.0, viento=15.0, eventos=()):
        return Medicion(
            instante=instante,
            seg_simulados=0.0,
            seg_reales=0.0,
            velocidad=30.0,
            pausado=True,
            temp_externa=22.0,
            temp_interna=temp_int,
            rad_externa=rad_int / 0.9,
            rad_interna=rad_int,
            viento_externo=viento,
            techo=EstadoTecho.CERRADO,
            cortinas=EstadoCortinas.CERRADAS,
            ventiladores=False,
            eventos_activos=eventos,
        )

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

    def test_banner_monitor_vuelve_a_normal_al_normalizarse_temperatura(self):
        self._login_admin()
        establecer_parametros_cultivo(
            id_cultivo=self.inv.cultivo_id,
            temp_min=16.0,
            temp_max=28.0,
            rad_min=300.0,
            rad_max=950.0,
            viento_max=40.0,
            persistencia_min=5,
            fecha=self.t0,
        )
        sim = reset_simulator()
        sim.pausar()
        evaluador = obtener_evaluador()

        def _med(instante, temp_int):
            return Medicion(
                instante=instante,
                seg_simulados=0.0,
                seg_reales=0.0,
                velocidad=30.0,
                pausado=True,
                temp_externa=22.0,
                temp_interna=temp_int,
                rad_externa=550.0,
                rad_interna=500.0,
                viento_externo=15.0,
                techo=EstadoTecho.CERRADO,
                cortinas=EstadoCortinas.CERRADAS,
                ventiladores=False,
                eventos_activos=(),
            )

        t_alta = sim.instante + timedelta(minutes=1)
        evaluador.evaluar(_med(t_alta, 31.0), sim=sim, invernadero_id=self.inv.id)

        alerta = Alerta.objects.get(invernadero=self.inv, variable='TEMPERATURA', categoria='ALERTA')
        self.assertFalse(alerta.resuelta)

        r_alerta = self.client.get('/api/monitor/')
        self.assertEqual(r_alerta.status_code, 200)
        banner_alerta = r_alerta.json()['banner']
        self.assertIn(banner_alerta['badge'], ('ALERTA', 'CRÍTICO'))
        self.assertIn(banner_alerta['nivel'], ('ADVERTENCIA', 'CRITICO'))

        t_normal = sim.instante + timedelta(minutes=3)
        evaluador.evaluar(_med(t_normal, 23.0), sim=sim, invernadero_id=self.inv.id)

        alerta.refresh_from_db()
        self.assertTrue(alerta.resuelta)

        r_hist_alertas = self.client.get('/api/alertas/?tipo=alert')
        self.assertEqual(r_hist_alertas.status_code, 200)
        ids_hist = [a['id'] for a in r_hist_alertas.json()['notificaciones']]
        self.assertIn(alerta.id, ids_hist)

        r_normal = self.client.get('/api/monitor/')
        self.assertEqual(r_normal.status_code, 200)
        banner_normal = r_normal.json()['banner']
        self.assertEqual(banner_normal['nivel'], 'INFO')
        self.assertEqual(banner_normal['badge'], 'NORMAL')

    def test_banner_dos_alertas_simultaneas_permanece_activo_hasta_resolver_ambas(self):
        self._login_admin()
        establecer_parametros_cultivo(
            id_cultivo=self.inv.cultivo_id,
            temp_min=16.0,
            temp_max=28.0,
            rad_min=300.0,
            rad_max=950.0,
            viento_max=40.0,
            persistencia_min=5,
            fecha=self.t0,
        )
        sim = reset_simulator()
        sim.pausar()
        evaluador = obtener_evaluador()

        t1 = sim.instante + timedelta(minutes=1)
        evaluador.evaluar(self._crear_medicion(t1, temp_int=30.5, viento=55.0), sim=sim, invernadero_id=self.inv.id)
        al_temp = Alerta.objects.get(invernadero=self.inv, variable='TEMPERATURA', categoria='ALERTA')
        al_viento = Alerta.objects.get(invernadero=self.inv, variable='VIENTO', categoria='ALERTA')
        self.assertFalse(al_temp.resuelta)
        self.assertFalse(al_viento.resuelta)

        # Se resuelve solo viento, pero temperatura sigue alta -> banner debe seguir mostrando alerta
        t2 = sim.instante + timedelta(minutes=2)
        evaluador.evaluar(self._crear_medicion(t2, temp_int=30.5, viento=15.0), sim=sim, invernadero_id=self.inv.id)
        al_viento.refresh_from_db()
        al_temp.refresh_from_db()
        self.assertTrue(al_viento.resuelta)
        self.assertFalse(al_temp.resuelta)

        banner_parcial = self.client.get('/api/monitor/').json()['banner']
        self.assertNotEqual(banner_parcial['badge'], 'NORMAL')
        self.assertIn('Temperatura', banner_parcial['titulo'])

        # Se normaliza temperatura -> ambas resueltas y banner vuelve a NORMAL
        t3 = sim.instante + timedelta(minutes=3)
        evaluador.evaluar(self._crear_medicion(t3, temp_int=22.0, viento=15.0), sim=sim, invernadero_id=self.inv.id)
        al_temp.refresh_from_db()
        self.assertTrue(al_temp.resuelta)
        self.assertTrue(Alerta.objects.filter(id=al_viento.id).exists())
        self.assertTrue(Alerta.objects.filter(id=al_temp.id).exists())

        banner_final = self.client.get('/api/monitor/').json()['banner']
        self.assertEqual(banner_final['nivel'], 'INFO')
        self.assertEqual(banner_final['badge'], 'NORMAL')

    def test_banner_resuelve_alerta_persistida_tras_reinicio_servidor(self):
        self._login_admin()
        establecer_parametros_cultivo(
            id_cultivo=self.inv.cultivo_id,
            temp_min=16.0,
            temp_max=28.0,
            rad_min=300.0,
            rad_max=950.0,
            viento_max=40.0,
            persistencia_min=5,
            fecha=self.t0,
        )
        sim = reset_simulator()
        sim.pausar()

        alerta_vieja = registrar_alerta(
            self.inv.id,
            variable='TEMPERATURA',
            valor=31.0,
            descripcion='Alerta previa al reinicio del servidor',
            fecha=sim.instante,
            nivel='ADVERTENCIA',
            categoria='ALERTA',
            titulo='Temperatura previa elevada',
        )
        resetear_evaluador()

        banner_pre = self.client.get('/api/monitor/').json()['banner']
        self.assertEqual(banner_pre['badge'], 'ALERTA')

        obtener_evaluador().evaluar(
            self._crear_medicion(sim.instante + timedelta(minutes=1), temp_int=22.0, rad_int=500.0, viento=15.0),
            sim=sim,
            invernadero_id=self.inv.id,
        )
        alerta_vieja.refresh_from_db()
        self.assertTrue(alerta_vieja.resuelta)

        banner_post = self.client.get('/api/monitor/').json()['banner']
        self.assertEqual(banner_post['nivel'], 'INFO')
        self.assertEqual(banner_post['badge'], 'NORMAL')

    def test_api_modo_y_mecanismo_sincronizan_bd_y_simulador(self):
        self._login_admin()
        sim = reset_simulator()
        sim.pausar()
        inv = Invernadero.objects.get(id=self.inv.id)

        # En modo AUTOMATICO no permite operar mecanismos directamente
        r_block = self.client.post(
            '/api/mecanismo/',
            data=json.dumps({'mecanismo': 'VENTILACION', 'activo': True}),
            content_type='application/json',
        )
        self.assertEqual(r_block.status_code, 400)

        r_manual = self.client.post(
            '/api/modo/',
            data=json.dumps({'modo': 'MANUAL'}),
            content_type='application/json',
        )
        self.assertEqual(r_manual.status_code, 200)
        inv.refresh_from_db()
        self.assertEqual(inv.modo, 'MANUAL')

        for mec, activo_req, estado_esp in (
            ('VENTILACION', True, 'ENCENDIDO'),
            ('MEDIA_SOMBRA', True, 'DESPLEGADA'),
            ('CORTINAS_LATERALES', False, 'CERRADAS'),
        ):
            r_op = self.client.post(
                '/api/mecanismo/',
                data=json.dumps({'mecanismo': mec, 'activo': activo_req}),
                content_type='application/json',
            )
            self.assertEqual(r_op.status_code, 200)
            self.assertEqual(Mecanismo.objects.get(invernadero=inv, tipo=mec).estado, estado_esp)
            self.assertTrue(
                HistorialMecanismo.objects.filter(
                    mecanismo__invernadero=inv,
                    mecanismo__tipo=mec,
                    a_que_estado_paso=estado_esp,
                    origen='MANUAL',
                ).exists()
            )
            self.assertTrue(Alerta.objects.filter(invernadero=inv, variable=mec, categoria='ACTIVACION').exists())

        self.assertTrue(sim.invernadero.ventiladores)
        self.assertEqual(sim.invernadero.techo, EstadoTecho.ABIERTO)
        self.assertEqual(sim.invernadero.cortinas, EstadoCortinas.CERRADAS)

        r_off = self.client.post(
            '/api/mecanismo/',
            data=json.dumps({'mecanismo': 'VENTILACION', 'activo': False}),
            content_type='application/json',
        )
        self.assertEqual(r_off.status_code, 200)
        self.assertEqual(Mecanismo.objects.get(invernadero=inv, tipo='VENTILACION').estado, 'APAGADO')
        self.assertFalse(sim.invernadero.ventiladores)

        r_auto = self.client.post(
            '/api/modo/',
            data=json.dumps({'modo': 'AUTOMATICO'}),
            content_type='application/json',
        )
        self.assertEqual(r_auto.status_code, 200)
        inv.refresh_from_db()
        self.assertEqual(inv.modo, 'AUTOMATICO')

    def test_cambio_cultivo_y_parametros_evalua_inmediatamente_nuevos_umbrales(self):
        self._login_admin()
        sim = reset_simulator()
        sim.pausar()
        tomate = Cultivo.objects.get(nombre='Tomate Cherry')

        # Con temp_max=18.0 (< ~20 °C iniciales al mediodía), el Evaluador debe disparar alerta inmediatamente
        payload = {
            'cultivo_id': tomate.id,
            'temp_min': 10.0,
            'temp_max': 18.0,
            'rad_min': 300.0,
            'rad_max': 950.0,
            'viento_max': 40.0,
            'tiempo_persistencia_min': 5,
            'modo': 'AUTOMATICO',
        }
        r_cfg = self.client.post('/api/configuracion/', data=json.dumps(payload), content_type='application/json')
        self.assertEqual(r_cfg.status_code, 200)

        inv = Invernadero.objects.get(id=self.inv.id)
        self.assertEqual(inv.cultivo_id, tomate.id)
        self.assertTrue(Alerta.objects.filter(invernadero=inv, variable='TEMPERATURA', categoria='ALERTA', umbral=18.0, resuelta=False).exists())

        mon = self.client.get('/api/monitor/').json()
        self.assertEqual(mon['invernadero']['cultivo'], 'Tomate Cherry')
        self.assertEqual(mon['parametros']['temp_max'], 18.0)
        self.assertIn(mon['banner']['badge'], ('ALERTA', 'CRÍTICO'))

        ev_estado = self.client.get('/evaluador/api/estado/').json()
        self.assertEqual(ev_estado['cultivo'], 'Tomate Cherry')
        self.assertEqual(ev_estado['parametros']['temp_max'], 18.0)

    def test_endpoints_y_reportes_csv_tras_reinicio_y_sin_mediciones(self):
        tmp_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp_dir, ignore_errors=True)
        self._login_admin()

        with override_settings(REPORTES_DIR=tmp_dir):
            # Escenario A: inmediatamente tras api_reset
            r_reset = self.client.post('/simulador/api/reset/')
            self.assertEqual(r_reset.status_code, 200)
            sim = get_simulator()
            sim.pausar()
            hoy_iso = sim.instante.date().isoformat()

            for url in (
                '/api/monitor/',
                '/historial/',
                '/api/historial/?rango=hour',
                '/api/historial/?rango=day',
                '/api/historial/?rango=minute',
                '/alertas/',
                '/api/alertas/',
            ):
                resp = self.client.get(url)
                self.assertEqual(resp.status_code, 200, f'Error en {url} tras reset')

            for tipo_rep in ('HISTORICO_CONSOLIDADO', 'DETALLE_EVENTOS'):
                r_gen = self.client.post(
                    '/api/reportes/generar/',
                    data=json.dumps({'fecha_desde': hoy_iso, 'fecha_hasta': hoy_iso, 'tipo': tipo_rep}),
                    content_type='application/json',
                )
                self.assertEqual(r_gen.status_code, 200)
                rep_id = r_gen.json()['reporte']['id']
                r_dl = self.client.get(f'/reportes/{rep_id}/descargar/')
                self.assertEqual(r_dl.status_code, 200)
                b''.join(r_dl.streaming_content)
                r_dl.close()

            # Escenario B: BD completamente vacía de mediciones, climas y alertas
            reiniciar_datos_simulacion(self.inv.id)
            for url in (
                '/api/monitor/',
                '/historial/',
                '/api/historial/?rango=hour',
                '/api/historial/?rango=day',
                '/api/historial/?rango=minute',
                '/alertas/',
                '/api/alertas/',
            ):
                resp = self.client.get(url)
                self.assertEqual(resp.status_code, 200, f'Error en {url} con BD sin mediciones')

            for tipo_rep in ('HISTORICO_CONSOLIDADO', 'DETALLE_EVENTOS'):
                r_gen = self.client.post(
                    '/api/reportes/generar/',
                    data=json.dumps({'fecha_desde': hoy_iso, 'fecha_hasta': hoy_iso, 'tipo': tipo_rep}),
                    content_type='application/json',
                )
                self.assertEqual(r_gen.status_code, 200)
                rep_id = r_gen.json()['reporte']['id']
                r_dl = self.client.get(f'/reportes/{rep_id}/descargar/')
                self.assertEqual(r_dl.status_code, 200)
                b''.join(r_dl.streaming_content)
                r_dl.close()

    def test_todas_las_vistas_y_apis_protegidas_requieren_login(self):
        for ruta in ('/', '/historial/', '/alertas/', '/reportes/', '/configuracion/', '/acerca-de/'):
            r = self.client.get(ruta)
            self.assertEqual(r.status_code, 302, f'{ruta} no redirigió sin login')
            self.assertIn('/login/', r['Location'])

        for api_get in ('/api/monitor/', '/api/historial/', '/api/alertas/', '/api/configuracion/', '/api/reportes/'):
            r = self.client.get(api_get)
            self.assertEqual(r.status_code, 401, f'GET {api_get} no devolvió 401 sin login')

        for api_post in (
            '/api/modo/',
            '/api/mecanismo/',
            '/api/alertas/leer/',
            '/api/cultivos/',
            '/api/reportes/generar/',
            '/api/reportes/1/eliminar/',
        ):
            r = self.client.post(api_post, data='{}', content_type='application/json')
            self.assertEqual(r.status_code, 401, f'POST {api_post} no devolvió 401 sin login')

        self._login_admin()
        self.assertEqual(self.client.get('/').status_code, 200)
        self.client.get('/logout/')
        self.assertEqual(self.client.get('/').status_code, 302)
        self.assertEqual(self.client.get('/api/monitor/').status_code, 401)

    def test_api_alertas_leer_no_resuelve_alertas_activas_del_banner(self):
        self._login_admin()
        establecer_parametros_cultivo(
            id_cultivo=self.inv.cultivo_id,
            temp_min=16.0,
            temp_max=28.0,
            rad_min=300.0,
            rad_max=950.0,
            viento_max=40.0,
            persistencia_min=5,
            fecha=self.t0,
        )
        sim = reset_simulator()
        sim.pausar()

        obtener_evaluador().evaluar(
            self._crear_medicion(sim.instante + timedelta(minutes=1), temp_int=31.0),
            sim=sim,
            invernadero_id=self.inv.id,
        )
        alerta = Alerta.objects.get(invernadero=self.inv, variable='TEMPERATURA', categoria='ALERTA')
        self.assertFalse(alerta.resuelta)

        r_leer = self.client.post('/api/alertas/leer/')
        self.assertEqual(r_leer.status_code, 200)

        alerta.refresh_from_db()
        self.assertFalse(alerta.resuelta)

        mon = self.client.get('/api/monitor/').json()
        self.assertNotEqual(mon['banner']['badge'], 'NORMAL')
        notif = next(n for n in mon['notificaciones'] if n['id'] == alerta.id)
        self.assertFalse(notif['unread'])

    def test_banner_prioriza_alerta_critica_sobre_advertencia_mas_reciente(self):
        self._login_admin()
        establecer_parametros_cultivo(
            id_cultivo=self.inv.cultivo_id,
            temp_min=16.0,
            temp_max=28.0,
            rad_min=300.0,
            rad_max=950.0,
            viento_max=40.0,
            persistencia_min=5,
            fecha=self.t0,
        )
        sim = reset_simulator()
        sim.pausar()
        evaluador = obtener_evaluador()

        t1 = sim.instante + timedelta(minutes=1)
        evaluador.evaluar(
            self._crear_medicion(t1, temp_int=22.0, rad_int=500.0, viento=55.0),
            sim=sim,
            invernadero_id=self.inv.id,
        )

        t2 = sim.instante + timedelta(minutes=2)
        evaluador.evaluar(
            self._crear_medicion(t2, temp_int=22.0, rad_int=200.0, viento=55.0),
            sim=sim,
            invernadero_id=self.inv.id,
        )

        banner_crit = self.client.get('/api/monitor/').json()['banner']
        self.assertEqual(banner_crit['nivel'], 'CRITICO')
        self.assertEqual(banner_crit['badge'], 'CRÍTICO (+1)')
        self.assertEqual(banner_crit['activas_total'], 2)
        self.assertIn('Viento', banner_crit['titulo'])
        self.assertEqual(len(banner_crit['otras_activas']), 1)
        otra = banner_crit['otras_activas'][0]
        self.assertIsInstance(otra['id'], int)
        self.assertEqual(otra['nivel'], 'ADVERTENCIA')
        self.assertEqual(otra['variable'], 'RADIACION')
        self.assertIn('Radiación', otra['titulo'])
        self.assertEqual(otra['hora'], t2.strftime('%H:%M:%S'))

        t3 = sim.instante + timedelta(minutes=3)
        evaluador.evaluar(
            self._crear_medicion(t3, temp_int=22.0, rad_int=200.0, viento=15.0),
            sim=sim,
            invernadero_id=self.inv.id,
        )

        banner_adv = self.client.get('/api/monitor/').json()['banner']
        self.assertEqual(banner_adv['nivel'], 'ADVERTENCIA')
        self.assertEqual(banner_adv['badge'], 'ALERTA')
        self.assertEqual(banner_adv['activas_total'], 1)
        self.assertIn('Radiación', banner_adv['titulo'])
        self.assertEqual(banner_adv['otras_activas'], [])

        t4 = sim.instante + timedelta(minutes=4)
        evaluador.evaluar(
            self._crear_medicion(t4, temp_int=22.0, rad_int=500.0, viento=15.0),
            sim=sim,
            invernadero_id=self.inv.id,
        )

        banner_ok = self.client.get('/api/monitor/').json()['banner']
        self.assertEqual(banner_ok['nivel'], 'INFO')
        self.assertEqual(banner_ok['badge'], 'NORMAL')
        self.assertEqual(banner_ok['activas_total'], 0)
        self.assertEqual(banner_ok['otras_activas'], [])
