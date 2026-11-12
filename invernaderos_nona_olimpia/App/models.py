from django.db import models
from django.utils import timezone


class Cultivo(models.Model):
    nombre = models.CharField(max_length=100, unique=True)
    recomendaciones = models.TextField(blank=True, null=True)

    class Meta:
        db_table = 'CULTIVOS'

    def __str__(self):
        return self.nombre


class Parametro(models.Model):
    cultivo = models.OneToOneField(
        Cultivo,
        on_delete=models.CASCADE,
        related_name='parametro',
        db_column='id_cultivo'
    )
    temp_min = models.FloatField(help_text="Temperatura mínima óptima (°C)")
    temp_max = models.FloatField(help_text="Temperatura máxima óptima (°C)")
    rad_min = models.FloatField(help_text="Radiación mínima óptima (W/m²)")
    rad_max = models.FloatField(help_text="Radiación máxima óptima (W/m²)")
    tiempo_persistencia_min = models.IntegerField(default=10)
    fecha_actualizacion = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = 'PARAMETROS'

    def __str__(self):
        return f"Parámetros de {self.cultivo.nombre}"


class HistorialParametro(models.Model):
    parametro = models.ForeignKey(
        Parametro,
        on_delete=models.CASCADE,
        related_name='historial',
        db_column='id_parametro'
    )
    temp_min = models.FloatField()
    temp_max = models.FloatField()
    rad_min = models.FloatField()
    rad_max = models.FloatField()
    tiempo_persistencia_min = models.IntegerField()
    fecha = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = 'HISTORIAL_PARAMETROS'
        ordering = ['-fecha']


class Invernadero(models.Model):
    nombre = models.CharField(max_length=100, default="Invernadero 1 - Sector A")
    cultivo = models.ForeignKey(
        Cultivo,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='invernaderos',
        db_column='id_cultivo'
    )

    class Meta:
        db_table = 'INVERNADEROS'

    def __str__(self):
        return f"{self.nombre} ({self.cultivo.nombre if self.cultivo else 'Sin cultivo'})"


class HistorialTemperatura(models.Model):
    grados = models.FloatField()
    fecha = models.DateTimeField(default=timezone.now, db_index=True)
    invernadero = models.ForeignKey(
        Invernadero,
        on_delete=models.CASCADE,
        related_name='temperaturas',
        db_column='id_invernadero'
    )

    class Meta:
        db_table = 'HISTORIAL_TEMPERATURA'
        ordering = ['-fecha']


class HistorialRadiacion(models.Model):
    valor = models.FloatField(help_text="Radiación solar en W/m²")
    fecha = models.DateTimeField(default=timezone.now, db_index=True)
    invernadero = models.ForeignKey(
        Invernadero,
        on_delete=models.CASCADE,
        related_name='radiaciones',
        db_column='id_invernadero'
    )

    class Meta:
        db_table = 'HISTORIAL_RADIACION'
        ordering = ['-fecha']


class HistorialClima(models.Model):
    ESTADOS_CLIMA = [
        ('DESPEJADO', 'Despejado / Soleado'),
        ('PARCIALMENTE_NUBLADO', 'Parcialmente nublado (Nube pasajera)'),
        ('NUBLADO', 'Nublado'),
        ('LLUVIA', 'Lluvia / Tormenta'),
        ('OLA_DE_CALOR', 'Ola de calor'),
    ]
    invernadero = models.ForeignKey(
        Invernadero,
        on_delete=models.CASCADE,
        related_name='climas',
        db_column='id_invernadero'
    )
    estado = models.CharField(max_length=50, choices=ESTADOS_CLIMA)
    temp_externa = models.FloatField(null=True, blank=True)
    probabilidad_lluvia = models.IntegerField(default=0)
    es_pronostico = models.BooleanField(default=False)
    fecha = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        db_table = 'HISTORIAL_CLIMA'
        ordering = ['-fecha']


class Mecanismo(models.Model):
    TIPOS_MECANISMO = [
        ('MEDIA_SOMBRA', 'Media Sombra'),
        ('VENTILACION', 'Ventilación'),
        ('RIEGO', 'Sistema de Riego'),
    ]
    invernadero = models.ForeignKey(
        Invernadero,
        on_delete=models.CASCADE,
        related_name='mecanismos',
        db_column='id_invernadero'
    )
    tipo = models.CharField(max_length=50, choices=TIPOS_MECANISMO)
    estado = models.CharField(max_length=50, default='ABIERTO')

    class Meta:
        db_table = 'MECANISMOS'

    def __str__(self):
        return f"{self.get_tipo_display()} - {self.invernadero.nombre} ({self.estado})"


class HistorialMecanismo(models.Model):
    mecanismo = models.ForeignKey(
        Mecanismo,
        on_delete=models.CASCADE,
        related_name='historial',
        db_column='id_mecanismo'
    )
    fecha = models.DateTimeField(default=timezone.now, db_index=True)
    a_que_estado_paso = models.CharField(max_length=50)
    origen = models.CharField(max_length=20, default='AUTOMATICO')

    class Meta:
        db_table = 'HISTORIAL_MECANISMOS'
        ordering = ['-fecha']


class Alerta(models.Model):
    invernadero = models.ForeignKey(
        Invernadero,
        on_delete=models.CASCADE,
        related_name='alertas',
        db_column='id_invernadero'
    )
    variable = models.CharField(max_length=30)
    valor_detectado = models.FloatField()
    descripcion = models.TextField()
    fecha = models.DateTimeField(default=timezone.now, db_index=True)
    resuelta = models.BooleanField(default=False)

    class Meta:
        db_table = 'ALERTAS'
        ordering = ['-fecha']
