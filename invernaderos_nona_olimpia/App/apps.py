from django.apps import AppConfig
from django.db.backends.signals import connection_created


def _configurar_sqlite(sender, connection, **kwargs):
    """Activa modo WAL y sincronización normal en SQLite para concurrencia segura."""
    if connection.vendor == 'sqlite':
        with connection.cursor() as cursor:
            cursor.execute('PRAGMA journal_mode=WAL;')
            cursor.execute('PRAGMA synchronous=NORMAL;')


class AppConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'App'

    def ready(self):
        connection_created.connect(_configurar_sqlite)
