from datetime import datetime
import json
import urllib.request


class LecturaClimatica:

  """Clase que encapsula los datos climáticos capturados para el invernadero."""

  def __init__(
      self,
      temperatura: float,
      radiacion_solar: float,
      codigo_clima: int,
      descripcion_clima: str,
      es_sintetico: bool = False,
  ):
    self._fecha_hora = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    self._temperatura = temperatura
    self._radiacion_solar = radiacion_solar
    self._codigo_clima = codigo_clima
    self._descripcion_clima = descripcion_clima
    self._es_sintetico = es_sintetico

  # Getters
  @property
  def fecha_hora(self) -> str:
    return self._fecha_hora

  @property
  def temperatura(self) -> float:
    return self._temperatura

  @property
  def radiacion_solar(self) -> float:
    return self._radiacion_solar

  @property
  def descripcion_clima(self) -> str:
    return self._descripcion_clima

  @property
  def es_sintetico(self) -> bool:
    return self._es_sintetico

  def __str__(self) -> str:
    origen = "🧪 SINTÉTICO (Prueba Nube)" if self._es_sintetico else "🌐 API REAL"
    return (
        f"[{self._fecha_hora}] [{origen}] "
        f"Rad: {self._radiacion_solar:.1f} W/m² | "
        f"Temp: {self._temperatura:.1f} °C | "
        f"Clima: {self._descripcion_clima}"
    )


class ServicioClimaOpenMeteo:

  """Clase encargada de consultar la API de Open-Meteo para la ubicación de Nona Olimpia."""

  # Tabla de traducción de códigos WMO meteorológicos a español
  DICCIONARIO_WMO = {
      0: "Cielo despejado / Sol",
      1: "Principalmente despejado",
      2: "Parcialmente nublado",
      3: "Nublado",
      45: "Niebla",
      48: "Niebla escarchada",
      51: "Llovizna ligera",
      61: "Lluvia ligera",
      63: "Lluvia moderada",
      80: "Chubascos",
  }

  def __init__(
      self, latitud: float = -24.3851, longitud: float = -65.1124
  ):
    """Inicializa el servicio con las coordenadas exactas de Nona Olimpia (Perico/Las Pampitas)."""
    self._latitud = latitud
    self._longitud = longitud
    
  # =========================================================================
  # REEMPLAZÁ AQUÍ: CONSTRUCCIÓN SEGURA DE LA URL
  # =========================================================================
    protocolo = "https://"
    dominio = "api" + "." + "open-meteo" + "." + "com"
    endpoint = "/v1/forecast"
    
    self._url_base = (
            f"{protocolo}{dominio}{endpoint}?"
            f"latitude={self._latitud}&longitude={self._longitud}&"
            f"current=temperature_2m,shortwave_radiation,weather_code&"
            f"timezone=America%2FArgentina%2FJujuy"
    )
  # =========================================================================

  def _traductor_wmo(self, codigo: int) -> str:
    """Convierte el código WMO numérico a una descripción comprensible."""
    return self.DICCIONARIO_WMO.get(codigo, f"Código WMO: {codigo}")

  def obtener_lectura_actual(
      self, simular_paso_nube: bool = False
  ) -> LecturaClimatica:
    """Consulta la API de Open-Meteo.

    Si simular_paso_nube=True, fuerza una caída de radiación para probar la
    lógica de histeresis y delays del sistema.
    """
    try:
      # Petición HTTP a la API de Open-Meteo
      req = urllib.request.Request(
          self._url_base, headers={"User-Agent": "Mozilla/5.0"}
      )
      with urllib.request.urlopen(req, timeout=5) as response:
        datos = json.loads(response.read().decode("utf-8"))

      # Extracción de datos reales del JSON retornado por Open-Meteo
      clima_actual = datos["current"]
      temp_real = float(clima_actual["temperature_2m"])
      rad_real = float(clima_actual["shortwave_radiation"])
      cod_wmo = int(clima_actual["weather_code"])
      desc_wmo = self._traductor_wmo(cod_wmo)

      # Evaluación del Modo Híbrido (Inyección de evento sintético para pruebas)
      if simular_paso_nube:
        return LecturaClimatica(
            temperatura=temp_real,
            radiacion_solar=180.0,  # Forzamos caída brusca por nube
            codigo_clima=3,
            descripcion_clima="Nublado transitorio (Simulado)",
            es_sintetico=True,
        )

      return LecturaClimatica(
          temperatura=temp_real,
          radiacion_solar=rad_real,
          codigo_clima=cod_wmo,
          descripcion_clima=desc_wmo,
          es_sintetico=False,
      )

    except Exception as e:
      print(f"⚠️ Error al conectar con Open-Meteo ({e}). Usando modo fallback.")
      # Fallback seguro por si falla internet en la presentación
      return LecturaClimatica(
          temperatura=24.5,
          radiacion_solar=200.0 if simular_paso_nube else 750.0,
          codigo_clima=0 if not simular_paso_nube else 3,
          descripcion_clima="Datos Fallback offline",
          es_sintetico=True,
      )


# --- PRUEBA DE EJECUCIÓN ---
if __name__ == "__main__":
  servicio_clima = ServicioClimaOpenMeteo()

  print("=" * 65)
  print("      MÓDULO DE ADQUISICIÓN CLIMÁTICA: FINCA NONA OLIMPIA")
  print("=" * 65)

  # 1. Obtenemos la lectura real de Open-Meteo
  print("\n1. Solicitando clima actual a Open-Meteo...")
  lectura_real = servicio_clima.obtener_lectura_actual(simular_paso_nube=False)
  print(lectura_real)

  # 2. Simulamos el evento que requiere probar Nona Olimpia (Paso de Nube)
  print("\n2. Inyectando prueba sintética: paso de nube pasajera...")
  lectura_nube = servicio_clima.obtener_lectura_actual(simular_paso_nube=True)
  print(lectura_nube)