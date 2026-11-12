from django.db import transaction
from django.utils import timezone
from .models import (
    Cultivo, Parametro, HistorialParametro, Invernadero,
    HistorialTemperatura, HistorialRadiacion, HistorialClima,
    Mecanismo, HistorialMecanismo, Alerta
)


def registrar_cultivo(nombre: str, recomendaciones: str = "") -> Cultivo:
    cultivo, _ = Cultivo.objects.update_or_create(
        nombre=nombre,
        defaults={'recomendaciones': recomendaciones}
    )
    return cultivo


def registrar_lectura_sensores(id_invernadero: int, grados: float, radiacion: float, fecha=None):
    fecha_reg = fecha or timezone.now()
    with transaction.atomic():
        reg_temp = HistorialTemperatura.objects.create(
            invernadero_id=id_invernadero,
            grados=grados,
            fecha=fecha_reg
        )
        reg_rad = HistorialRadiacion.objects.create(
            invernadero_id=id_invernadero,
            valor=radiacion,
            fecha=fecha_reg
        )
    return reg_temp, reg_rad


def registrar_clima(id_invernadero: int, estado: str, temp_externa: float = None,
                    prob_lluvia: int = 0, es_pronostico: bool = False, fecha=None) -> HistorialClima:
    return HistorialClima.objects.create(
        invernadero_id=id_invernadero,
        estado=estado,
        temp_externa=temp_externa,
        probabilidad_lluvia=prob_lluvia,
        es_pronostico=es_pronostico,
        fecha=fecha or timezone.now()
    )


def registrar_alerta(id_invernadero: int, variable: str, valor: float, descripcion: str) -> Alerta:
    return Alerta.objects.create(
        invernadero_id=id_invernadero,
        variable=variable,
        valor_detectado=valor,
        descripcion=descripcion
    )


def establecer_parametros_cultivo(id_cultivo: int, temp_min: float, temp_max: float,
                                  rad_min: float, rad_max: float, persistencia_min: int = 10) -> Parametro:
    with transaction.atomic():
        param, _ = Parametro.objects.update_or_create(
            cultivo_id=id_cultivo,
            defaults={
                'temp_min': temp_min,
                'temp_max': temp_max,
                'rad_min': rad_min,
                'rad_max': rad_max,
                'tiempo_persistencia_min': persistencia_min,
                'fecha_actualizacion': timezone.now()
            }
        )
        HistorialParametro.objects.create(
            parametro=param,
            temp_min=temp_min,
            temp_max=temp_max,
            rad_min=rad_min,
            rad_max=rad_max,
            tiempo_persistencia_min=persistencia_min
        )
    return param


def cambiar_estado_mecanismo(id_mecanismo: int, nuevo_estado: str, origen: str = 'AUTOMATICO') -> Mecanismo:
    with transaction.atomic():
        mec = Mecanismo.objects.select_for_update().get(id=id_mecanismo)
        mec.estado = nuevo_estado
        mec.save(update_fields=['estado'])

        HistorialMecanismo.objects.create(
            mecanismo=mec,
            a_que_estado_paso=nuevo_estado,
            origen=origen,
            fecha=timezone.now()
        )
    return mec