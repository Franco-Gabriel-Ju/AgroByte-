class Cultivo:

  def __init__(self, id_cultivo: int, nombre: str, descripcion: str):
    self._id = id_cultivo
    self._nombre = nombre
    self._descripcion = descripcion

  # Getters
  @property
  def id(self) -> int:
    return self._id

  @property
  def nombre(self) -> str:
    return self._nombre

  @property
  def descripcion(self) -> str:
    return self._descripcion

  def __str__(self) -> str:
    return (
        f"Cultivo [ID: {self._id}] - Nombre: {self._nombre} | Desc:"
        f" {self._descripcion}"
    )


class GestorCultivos:

  def __init__(self):
    self.cultivos: list[Cultivo] = []
    self._ultimo_id = 0

  @staticmethod
  def _validar_cadena(texto: str, min_caracteres: int = 3) -> tuple[bool, str]:
    """Valida que el texto no esté vacío y cumpla con la longitud mínima."""
    texto_limpio = texto.strip()
    if not texto_limpio:
      return False, "El campo no puede estar vacío."
    if len(texto_limpio) < min_caracteres:
      return (
          False,
          f"Debe contener al menos {min_caracteres} caracteres de longitud.",
      )
    return True, texto_limpio

  def ingresar_cultivo(self) -> Cultivo | None:

    # 1. Ingreso y Validación del Nombre
    while True:
      nombre_input = input("\n> Ingrese el nombre del cultivo: ")
      valido, resultado = self._validar_cadena(nombre_input, min_caracteres=3)
      if valido:
        nombre = resultado
        break
      print(f"Error: {resultado}")

    while True:
      desc_input = input("> Ingrese la descripción o recomendaciones: ")
      valido, resultado = self._validar_cadena(desc_input, min_caracteres=5)
      if valido:
        descripcion = resultado
        break
      print(f"Error: {resultado}")

    nuevo_id = self._ultimo_id + 1

    print("\n" + "-" * 40)
    print("  VERIFICACIÓN DEL OBJETO CULTIVO A CREAR")
    print("-" * 40)
    print(f"  • ID (Autogenerado): {nuevo_id}")
    print(f"  • Nombre           : {nombre}")
    print(f"  • Descripción      : {descripcion}")
    print("-" * 40)

    while True:
      confirmacion = (
          input("\n¿Desea instanciar y guardar este cultivo? (S/N): ")
          .strip()
          .upper()
      )
      if confirmacion in ["S", "N"]:
        break
      print(
          "Opción no válida. Ingrese 'S' para confirmar o 'N' para cancelar."
      )

    if confirmacion == "S":
      nuevo_cultivo = Cultivo(
          id_cultivo=nuevo_id, nombre=nombre, descripcion=descripcion
      )

      self.cultivos.append(nuevo_cultivo)
      self._ultimo_id = nuevo_id

      print(f"\n Objeto instanciado con éxito: {nuevo_cultivo}")
      return nuevo_cultivo
    else:
      print("\n Operación cancelada. No se instanció ningún objeto.")
      return None

  def listar_cultivos(self):
    """Muestra en consola la lista de objetos Cultivo registrados."""
    print("\n--- LISTADO DE CULTIVOS REGISTRADOS ---")
    if not self.cultivos:
      print("No hay cultivos registrados en la memoria.")
    else:
      for c in self.cultivos:
        print(c)

if __name__ == "__main__":
  gestor = GestorCultivos()

  gestor.ingresar_cultivo()

  gestor.listar_cultivos()