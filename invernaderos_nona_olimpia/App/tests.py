from django.test import TestCase, Client
from django.urls import reverse

class NavegacionVistasTest(TestCase):
    def setUp(self):
        self.client = Client()

    def test_monitor_view_is_index(self):
        """El index (/) debe renderizar la vista de Monitor con status 200."""
        response = self.client.get(reverse('monitor'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'layouts/base.html')
        self.assertTemplateUsed(response, 'partials/sidebar.html')
        self.assertTemplateUsed(response, 'partials/navbar.html')
        self.assertTemplateUsed(response, 'pages/monitor.html')
        self.assertContains(response, 'id="sidebar"')
        self.assertContains(response, 'id="mobileMenuBtn"')
        self.assertContains(response, 'id="sidebarOverlay"')
        self.assertContains(response, 'nav-item active')

    def test_historial_view(self):
        """La vista historial (/historial/) debe renderizar correctamente."""
        response = self.client.get(reverse('historial'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'pages/historial.html')
        self.assertContains(response, 'graficoTemperatura')
        self.assertContains(response, 'graficoRadiacion')

    def test_alertas_view(self):
        """La vista alertas (/alertas/) debe renderizar notificaciones."""
        response = self.client.get(reverse('alertas'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'pages/alertas.html')
        self.assertContains(response, 'Historial de notificaciones')

    def test_reportes_view(self):
        """La vista reportes (/reportes/) debe renderizar correctamente."""
        response = self.client.get(reverse('reportes'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'pages/reportes.html')

    def test_configuracion_view(self):
        """La vista configuración (/configuracion/) debe renderizar correctamente."""
        response = self.client.get(reverse('configuracion'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'pages/configuracion.html')

    def test_acerca_de_view(self):
        """La vista acerca de (/acerca-de/) debe renderizar correctamente."""
        response = self.client.get(reverse('acerca_de'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'pages/acerca_de.html')
