"""colisiones.py — Clave de búsqueda SEGURA para la celda "Código" de las
grillas de HybridLite (Compras, Pedidos, Ajustes).

EL PROBLEMA (confirmado en vivo dos veces: compra #30 el 2026-08-11 y compra
#43 el 2026-08-22): al teclear un código en la celda "Código" de una grilla,
HybridLite resuelve **primero por PRD_REFERENCIA** (el "código de barras") y
solo si no encuentra nada resuelve por PRD_CODIGO (el código interno). Como en
el catálogo hay 98 productos cuyo código interno es la REFERENCIA de OTRO
producto, teclear el código interno de A carga en la grilla el producto B.

Nada en el flujo lo detectaba: cargar_item() tecleaba y seguía de largo, y el
descuadre recién aparecía en la verificación contra la DBISAM, cuando el
documento ya estaba totalizado y era permanente (no reencolable sin duplicar
la compra).

Peor: la colisión puede ENCADENARSE. En la compra #43 el ítem 7453038479639
cargó `02812`, que YA era otro ítem legítimo de la misma compra — su fila
quedó sobreescrita y esa compra se perdió entera sin dejar rastro en ninguna
fila.

LA SOLUCIÓN de este módulo: decidir ANTES de teclear qué string produce el
producto correcto, usando el mismo criterio que usa HybridLite.

    clave_de_busqueda("7453038493758")
      -> ("CV-GL-1", "codigo interceptado por 02251; se usa su referencia")

Regla (derivada de "referencia gana sobre código"):
  1. Si el código NO es referencia de ningún otro producto -> teclear el
     código interno tal cual (caso normal, ~98.7% del catálogo).
  2. Si está interceptado pero el producto tiene referencia propia ÚNICA ->
     teclear esa referencia: al ganar la referencia, resuelve al producto
     correcto.
  3. Si está interceptado y no hay referencia propia única -> NO HAY CLAVE
     SEGURA: se lanza SinClaveSegura y el llamador debe ABORTAR ANTES de
     teclear. Un aborto limpio (nada escrito, reintentable) es infinitamente
     preferible a un documento permanente con el producto equivocado.

Al 2026-08-22 el catálogo (7.639 productos) tiene 98 códigos interceptados:
48 se resuelven por su referencia y 50 no tienen salida (referencia vacía) —
esos 50 solo se pueden arreglar en el catálogo de HybridLite, asignándoles
una referencia propia o eliminando el duplicado.

Lectura SOLO LECTURA de TInventario.dat, cacheada por mtime (el archivo pesa
varios MB y una compra consulta decenas de códigos).
"""
import os
import logging
from collections import defaultdict

import pydbisam

log = logging.getLogger("colisiones")

RUTA_INVENTARIO = r"H:\HybridLite\HybridEmpresa\HybridDataBase\TInventario.dat"

# {"mtime": float, "por_ref": dict, "ref_de": dict, "desc_de": dict}
_CACHE = {"mtime": None, "datos": None}


class SinClaveSegura(Exception):
    """El código está interceptado por la referencia de otro producto y no hay
    forma segura de teclearlo. El llamador DEBE abortar sin escribir nada."""


class CatalogoIlegible(Exception):
    """No se pudo leer TInventario.dat (unidad H: caída, archivo bloqueado).
    Sin catálogo no se puede descartar una colisión, así que el llamador debe
    tratarlo como fail-closed: abortar sin teclear."""


def _catalogo():
    """{"por_ref": {referencia: [codigos]}, "ref_de": {codigo: referencia},
    "desc_de": {codigo: descripcion}} desde TInventario.dat, cacheado por mtime.

    Lanza CatalogoIlegible si no se puede leer: es FAIL-CLOSED a propósito —
    devolver "no hay colisión" cuando en realidad no pudimos mirar es
    exactamente el error que produjo la compra #43."""
    try:
        mtime = os.path.getmtime(RUTA_INVENTARIO)
    except OSError as e:
        raise CatalogoIlegible(f"No pude acceder a TInventario.dat: {e}") from e

    if _CACHE["mtime"] == mtime and _CACHE["datos"] is not None:
        return _CACHE["datos"]

    try:
        db = pydbisam.PyDBISAM(RUTA_INVENTARIO)
        idx = {n: i for i, n in enumerate(db.fields())}
        i_cod = idx["PRD_CODIGO"]
        i_ref = idx["PRD_REFERENCIA"]
        i_desc = idx["PRD_DESCRIPCION"]

        por_ref = defaultdict(list)
        ref_de, desc_de = {}, {}
        for row in db.rows():
            codigo = str(row[i_cod]).strip()
            if not codigo or codigo == "Fail":
                continue
            crudo = row[i_ref]
            referencia = str(crudo).strip() if crudo and str(crudo).strip() != "Fail" else ""
            ref_de[codigo] = referencia
            desc_de[codigo] = str(row[i_desc]).strip()
            if referencia:
                por_ref[referencia].append(codigo)
    except Exception as e:
        raise CatalogoIlegible(f"No pude leer TInventario.dat: {e!r}") from e

    if not ref_de:
        raise CatalogoIlegible("TInventario.dat se leyó vacío (0 productos).")

    datos = {"por_ref": dict(por_ref), "ref_de": ref_de, "desc_de": desc_de}
    _CACHE.update(mtime=mtime, datos=datos)
    log.info("Catálogo leído para colisiones: %d productos, %d referencias.",
             len(ref_de), len(por_ref))
    return datos


def interceptores(codigo, cat=None):
    """Códigos de los OTROS productos que tienen `codigo` como su referencia.
    Si la lista no está vacía, teclear `codigo` carga el primero de ellos, no
    el producto que se quería."""
    cat = cat or _catalogo()
    codigo = str(codigo).strip()
    return [c for c in cat["por_ref"].get(codigo, []) if c != codigo]


def clave_de_busqueda(codigo):
    """Devuelve (clave, motivo): el string que hay que TECLEAR para que la
    grilla cargue `codigo`, y una explicación corta para el log.

    `clave == codigo` en el caso normal. Lanza SinClaveSegura si el código está
    interceptado y no hay alternativa, y CatalogoIlegible si no se pudo leer el
    catálogo (ambos = abortar sin teclear)."""
    cat = _catalogo()
    codigo = str(codigo).strip()

    ladrones = interceptores(codigo, cat)
    if not ladrones:
        return codigo, "sin colisión"

    referencia = cat["ref_de"].get(codigo, "")
    duenos_ref = cat["por_ref"].get(referencia, []) if referencia else []
    if referencia and duenos_ref == [codigo]:
        motivo = (f"código interceptado por {', '.join(ladrones)} "
                  f"(lo tienen como referencia); se teclea su referencia propia "
                  f"{referencia!r}, que es única")
        log.warning("Colisión en %s: %s", codigo, motivo)
        return referencia, motivo

    detalle_ref = (f"su referencia {referencia!r} la comparten {duenos_ref}"
                   if referencia else "no tiene referencia propia")
    raise SinClaveSegura(
        f"El código {codigo!r} ({cat['desc_de'].get(codigo, '?')}) es la referencia de "
        f"{', '.join(ladrones)}, así que teclearlo cargaría ese otro producto, y "
        f"{detalle_ref}: no hay forma segura de cargarlo desde la grilla. "
        f"Arreglar el catálogo en HybridLite (darle una referencia propia única "
        f"o eliminar el duplicado) y reintentar.")


def revisar_lote(codigos):
    """Pre-vuelo de una lista de códigos: devuelve (claves, problemas) donde
    `claves` es {codigo: clave_a_teclear} para los resolubles y `problemas` es
    {codigo: motivo} para los que no tienen clave segura.

    Pensado para llamarse ANTES de tocar la UI: si `problemas` no está vacío,
    el documento entero se aborta sin escribir nada (política todo-o-nada),
    y el usuario recibe la lista completa de lo que hay que arreglar en el
    catálogo en vez de descubrirlo de a un producto por corrida."""
    claves, problemas = {}, {}
    for codigo in codigos:
        try:
            claves[str(codigo).strip()], _ = clave_de_busqueda(codigo)
        except SinClaveSegura as e:
            problemas[str(codigo).strip()] = str(e)
    return claves, problemas


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        for cod in sys.argv[1:]:
            try:
                clave, motivo = clave_de_busqueda(cod)
                marca = "=" if clave == cod else "->"
            except SinClaveSegura as e:
                print(f"  {cod}: SIN CLAVE SEGURA\n     {e}")
                continue
            print(f"  {cod} {marca} teclear {clave!r}   ({motivo})")
        sys.exit(0)

    # sin argumentos: auditoría completa del catálogo
    cat = _catalogo()
    interceptados = [c for c in cat["ref_de"] if interceptores(c, cat)]
    resolubles, sin_salida = [], []
    for cod in interceptados:
        try:
            clave_de_busqueda(cod)
            resolubles.append(cod)
        except SinClaveSegura:
            sin_salida.append(cod)

    print(f"productos          : {len(cat['ref_de'])}")
    print(f"códigos interceptados: {len(interceptados)}")
    print(f"  resolubles por su referencia: {len(resolubles)}")
    print(f"  SIN clave segura            : {len(sin_salida)}")
    if sin_salida:
        print("\nHay que arreglarlos en el catálogo de HybridLite "
              "(referencia propia única, o eliminar el duplicado):")
        for cod in sorted(sin_salida):
            ladrones = interceptores(cod, cat)
            print(f"  {cod:<16} {cat['desc_de'].get(cod, '')[:52]:<54} "
                  f"lo intercepta: {', '.join(ladrones)}")
