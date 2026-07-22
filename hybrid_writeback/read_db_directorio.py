"""read_db_directorio.py — Verificación (SOLO LECTURA) del alta de clientes/proveedores
directamente contra la DBISAM (TClientes.dat / TProveedores.Dat), sin depender de la UI.

Se usa desde flujo_cliente_real.py / flujo_proveedor_real.py tras Guardar: confirma que
la ficha recién dada de alta EXISTE en la base y devuelve el código que HybridLite
autoasignó (CLT_CODIGO / PRV_CODIGO), que la app guarda en `codigo_*_hybrid`.

Estrategia de verificación (robusta al modo de asignación de código, que puede ser
autosecuencial en clientes o derivado del RIF en proveedores): se buscan los registros
cuya DESCRIPCION coincide con el nombre enviado (normalizado, MAYÚSCULAS como lo teclea el
flujo) y, si se pasó RIF, que además el RIF coincida; entre los que matchean se devuelve el
de mayor BASE_AUTOINCREMENT (el creado más recientemente). Mismo criterio de "último
registro" que _ultimo_pedido_db en flujo_pedido_real.

Uso:
    python read_db_directorio.py cliente "JUAN PEREZ"
    python read_db_directorio.py proveedor "TORNILLOS CA" --rif J-12345678-9
"""
import sys
import pydbisam

RUTA_CLIENTES = r"H:\HybridLite\HybridEmpresa\HybridDataBase\TClientes.dat"
RUTA_PROVEEDORES = r"H:\HybridLite\HybridEmpresa\HybridDataBase\TProveedores.Dat"

# Mapa de campos por tipo (nombres reales de la DBISAM, confirmados con pydbisam).
CONFIG = {
    "cliente": {
        "ruta":      RUTA_CLIENTES,
        "codigo":    "CLT_CODIGO",
        "nombre":    "CLT_DESCRIPCION",
        "rif":       "CLT_RIF",
        "telefono":  "CLT_TELEFONO",
        "direccion": "CLT_DIRECCION1",
        "email":     "CLT_EMAIL",
        "auto":      "BASE_AUTOINCREMENT",
    },
    "proveedor": {
        "ruta":      RUTA_PROVEEDORES,
        "codigo":    "PRV_CODIGO",
        "nombre":    "PRV_DESCRIPCION",
        "rif":       "PRV_RIF",
        "telefono":  "PRV_TELEFONO",
        "contacto":  "PRV_CONTACTO",
        "email":     "PRV_EMAIL",
        "direccion": "PRV_DIRECCION1",
        "auto":      "BASE_AUTOINCREMENT",
    },
}


def _clean(val):
    """Normaliza texto DBISAM: 'Fail'/'' -> None (patrón conocido del proyecto)."""
    if val is None:
        return None
    text = str(val).strip()
    if text == "" or text == "Fail":
        return None
    return text


def _norm(val):
    """Normaliza para comparar nombres: mayúsculas + espacios colapsados."""
    return " ".join(str(val or "").upper().split())


def _norm_rif(val):
    """Normaliza un RIF/cédula para comparar: mayúsculas, sin espacios ni guiones/puntos."""
    return "".join(ch for ch in str(val or "").upper() if ch.isalnum())


def _rows(tipo):
    """Itera los registros de la tabla del tipo dado como dicts {campo_logico: valor}."""
    cfg = CONFIG[tipo]
    db = pydbisam.PyDBISAM(cfg["ruta"])
    campos = db.fields()
    idx = {n: i for i, n in enumerate(campos)}
    for row in db.rows():
        reg = {}
        for logico, real in cfg.items():
            if logico == "ruta":
                continue
            reg[logico] = row[idx[real]] if real in idx else None
        yield reg


def codigo_desde_rif(rif):
    """Deriva el CÓDIGO de la ficha a partir del RIF/cédula: alfanumérico en
    MAYÚSCULAS, sin guiones/espacios/puntos. Es la convención de la tienda
    (RIF 'J-31440341-9' -> código 'J314403419'). Devuelve '' si el rif es vacío."""
    return _norm_rif(rif)


def buscar_por_codigo(tipo, codigo):
    """Devuelve el registro cuyo código coincide (normalizado) con `codigo`, o None."""
    if tipo not in CONFIG:
        return None
    objetivo = _norm_rif(codigo)
    if not objetivo:
        return None
    for reg in _rows(tipo):
        if _norm_rif(reg.get("codigo")) == objetivo:
            return reg
    return None


def existe_codigo(tipo, codigo):
    """True si ya hay una ficha con ese código (para hacer el alta idempotente:
    si el código ya existe, el flujo NO intenta crearlo de nuevo)."""
    return buscar_por_codigo(tipo, codigo) is not None


def verificar(tipo, nombre, rif=None):
    """Confirma que existe una ficha con ese nombre (y RIF si se pasa) y devuelve su código.

    Return: (ok: bool, codigo: str|None, detalle: str).
    Si hay varias coincidencias devuelve la de mayor BASE_AUTOINCREMENT (la más nueva)."""
    if tipo not in CONFIG:
        return False, None, f"tipo desconocido: {tipo!r}"

    objetivo_nombre = _norm(nombre)
    objetivo_rif = _norm_rif(rif) if rif else None

    mejor = None
    for reg in _rows(tipo):
        if _norm(reg.get("nombre")) != objetivo_nombre:
            continue
        if objetivo_rif and _norm_rif(reg.get("rif")) != objetivo_rif:
            continue
        auto = reg.get("auto") or 0
        if mejor is None or auto > (mejor.get("auto") or 0):
            mejor = reg

    if mejor is None:
        cond = f"nombre={nombre!r}" + (f", rif={rif!r}" if rif else "")
        return False, None, f"no encontré ninguna ficha de {tipo} con {cond} en la DBISAM tras Guardar."

    codigo = _clean(mejor.get("codigo"))
    if not codigo:
        return False, None, (f"la ficha de {tipo} {nombre!r} existe pero su código quedó vacío "
                             f"en la DBISAM (¿alta a medias?).")
    return True, codigo, (f"ficha de {tipo} {nombre!r} VERIFICADA en DB "
                          f"(codigo={codigo}, rif={_clean(mejor.get('rif'))}).")


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    rif = None
    if "--rif" in sys.argv:
        i = sys.argv.index("--rif")
        if i + 1 < len(sys.argv):
            rif = sys.argv[i + 1]
    if len(args) < 2:
        print('Uso: python read_db_directorio.py <cliente|proveedor> "NOMBRE" [--rif RIF]')
        return
    tipo, nombre = args[0], args[1]
    ok, codigo, detalle = verificar(tipo, nombre, rif)
    print(("OK: " if ok else "NO: ") + detalle)
    if ok:
        print(f"codigo_hybrid = {codigo}")


if __name__ == "__main__":
    main()
