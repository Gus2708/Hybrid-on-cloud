"""
flujo_ficha_real.py — Cambio de DESCRIPCIÓN y/o REFERENCIA en HybridLiteOS con
INPUT REAL de hardware (mismo patrón que flujo_precio_real.py).

Descripción y referencia viven en el HEADER de la Ficha de Inventario
(TTConfigForm) — los mismos 3 campos THybridEdit (código/referencia/
descripción) que flujo_compra_real.crear_producto() llena al dar de ALTA un
producto nuevo. Editar un producto EXISTENTE difiere solo en cómo se entra a
la Ficha: en vez de 'Incluir' (registro vacío), se usa 'Modificar + buscar +
cargar' (reutiliza flujo_precio_real.cargar_producto). En modo Modificar el
campo código queda BLOQUEADO (no editable) — es el comportamiento esperado,
por eso set_ficha() no toca código, solo descripción/referencia.

Secuencia (set_ficha):
  1. asegurar_hybrid (lanza/loguea Hybrid si hace falta).
  2. fpr._cerrar_residuales() + fpr.cargar_producto(codigo) — Modificar ->
     Busqueda -> teclear código -> ENTER -> cargar la fila (misma Ficha que
     usa flujo_precio_real, sesión reutilizable).
  3. Localizar los 3 campos del header con fcr._campos_ficha(hf) (por franja
     de posición relativa a la ventana, igual que crear_producto).
  4. Escribir SOLO el/los campo(s) pedido(s) con fcr._escribir_campo_ficha
     (clic + borrado duro + teclear), verificando el read-back en pantalla.
  5. preview (default): descartar con fcr._cancelar_ficha_alta (Cancelar +
     responde 'No' a guardar) — funciona igual para una Modificación que para
     una alta: la Ficha vuelve a su estado previo, nada se guarda.
     --commit: fpr._guardar_ficha() (Guardar + Confirm 'Sí').

SEGURIDAD / IDEMPOTENCIA (clave para el listener): a diferencia del STOCK
(que es un DELTA aplicado sobre un documento de ajuste permanente del kardex
— reintentar un commit ambiguo puede aplicar el cambio DOS VECES), descripción
y referencia son VALORES ABSOLUTOS: reescribir la misma descripción/referencia
(por un reintento tras un fallo, por ejemplo) es un no-op seguro. Por eso
set_ficha() NUNCA devuelve una etapa "ambigua" — TODAS las etapas de fallo que
emite ("abrir_hybrid", "escritura", "aceptar") están en
listener_writeback.ETAPAS_REINTENTABLES y se reintentan sin riesgo. Una
excepción inesperada en la escritura/guardado se propaga al listener, que la
atrapa en _fase_metadata_item y la mapea a "aceptar" (también reintentable).

VERIFICACIÓN: solo read-back EN PANTALLA (window_text() tras teclear). No
existe lector DBISAM de descripción/referencia en este backend (a diferencia
de precio/costo, que sí tienen hybrid_price_writer) — no se agrega ninguno acá.
  * descripción: el read-back DEBE coincidir (.strip()) con el valor pedido;
    si no, se descarta y falla (mismo criterio estricto que crear_producto).
  * referencia: si el read-back no coincide, se registra un WARNING pero NO
    bloquea (igual que crear_producto — la referencia es informativa/menos
    crítica que el código o la descripción).

USO:
    python flujo_ficha_real.py 00-002-024 --desc "Martillo de goma 16oz"
    python flujo_ficha_real.py 00-002-024 --ref "MG-16OZ" --commit
    python flujo_ficha_real.py 00-002-024 --desc "..." --ref "..." --commit
"""
import sys
import logging

# consola tolerante a UTF-8
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import flujo_precio as fp             # helpers de ventanas + constantes de clase
import flujo_precio_real as fpr       # cargar_producto, _cerrar_residuales, _guardar_ficha...
import flujo_compra_real as fcr       # _campos_ficha, _escribir_campo_ficha, _cancelar_ficha_alta
import realinput as ri                # noqa: F401  (mantenido por paridad con los otros flujos)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("ficha_real")


def set_ficha(codigo, nueva_descripcion=None, nueva_referencia=None, commit=False):
    """Cambia descripción y/o referencia de un producto EXISTENTE en una sola
    sesión de Ficha (Modificar, no Incluir).

    Return: {"ok": bool, "etapa": str, "detalle": str}
      etapa éxito: "preview" (verificado en pantalla, NO guardado) | "commit"
                   (guardado, verificado en pantalla)
      etapa fallo: "abrir_hybrid" | "escritura" | "aceptar" (las TRES son
                   reintentables — ver nota de IDEMPOTENCIA en el docstring
                   del módulo; nunca se devuelve otra etapa desde acá)."""
    nueva_descripcion = (nueva_descripcion or "").strip() or None
    nueva_referencia = (nueva_referencia or "").strip() or None
    if nueva_descripcion is None and nueva_referencia is None:
        return {"ok": False, "etapa": "escritura", "detalle": "Nada que cambiar."}

    import abrir_hybrid
    ok, msg = abrir_hybrid.asegurar_hybrid()
    if not ok:
        return {"ok": False, "etapa": "abrir_hybrid", "detalle": msg}

    try:
        fpr._cerrar_residuales()
        fpr.cargar_producto(codigo)
    except (fpr.PrecioError, fp.FlujoError) as e:
        return {"ok": False, "etapa": "escritura",
                "detalle": f"No pude cargar {codigo} en la Ficha: {e}"}

    hf = fp._find_hwnd(fp.FICHA_CLASS)
    campos = fcr._campos_ficha(hf)

    if nueva_descripcion is not None and campos["descripcion"] is None:
        fcr._cancelar_ficha_alta(hf)
        return {"ok": False, "etapa": "escritura",
                "detalle": f"No pude localizar el campo descripción de la Ficha para {codigo}. "
                           f"Nada se tocó."}
    if nueva_referencia is not None and campos["referencia"] is None:
        fcr._cancelar_ficha_alta(hf)
        return {"ok": False, "etapa": "escritura",
                "detalle": f"No pude localizar el campo referencia de la Ficha para {codigo}. "
                           f"Nada se tocó."}

    descripcion_ui = None
    referencia_ui = None

    if nueva_descripcion is not None:
        descripcion_ui = fcr._escribir_campo_ficha(campos["descripcion"], nueva_descripcion, lento=False)
        if descripcion_ui != nueva_descripcion:
            fcr._cancelar_ficha_alta(hf)
            return {"ok": False, "etapa": "escritura",
                    "detalle": f"La descripción de {codigo} quedó en pantalla como "
                               f"{descripcion_ui!r}, no {nueva_descripcion!r}. Nada se tocó."}

    if nueva_referencia is not None:
        referencia_ui = fcr._escribir_campo_ficha(campos["referencia"], nueva_referencia, lento=False)
        if referencia_ui != nueva_referencia:
            log.warning("La referencia de %s quedó en pantalla como %r, no %r (no bloqueante).",
                        codigo, referencia_ui, nueva_referencia)

    resumen = f"descripcion={descripcion_ui!r} referencia={referencia_ui!r}"

    if not commit:
        fcr._cancelar_ficha_alta(hf)   # descarta sin guardar (Cancelar + 'No')
        return {"ok": True, "etapa": "preview",
                "detalle": f"Datos verificados en pantalla y DESCARTADOS (sin --commit): {resumen}"}

    fpr._guardar_ficha()               # Guardar + Confirm 'Sí'
    return {"ok": True, "etapa": "commit",
            "detalle": f"Descripción/Referencia guardada (verificada en pantalla): {resumen}"}


if __name__ == "__main__":
    _raw = sys.argv[1:]
    _flags_con_valor = ("--desc", "--ref")
    args = []           # solo posicionales: <codigo>
    i = 0
    while i < len(_raw):
        tok = _raw[i]
        if tok in _flags_con_valor:
            i += 2      # saltar la bandera Y su valor
            continue
        if not tok.startswith("--"):
            args.append(tok)
        i += 1

    if len(args) < 1:
        print("Uso: python flujo_ficha_real.py <codigo> [--desc \"texto\"] "
              "[--ref \"texto\"] [--commit]")
        sys.exit(1)
    codigo = args[0]
    desc = _raw[_raw.index("--desc") + 1] if "--desc" in _raw else None
    ref = _raw[_raw.index("--ref") + 1] if "--ref" in _raw else None
    if desc is None and ref is None:
        print("Debe indicar --desc y/o --ref.")
        sys.exit(1)

    res = set_ficha(codigo, nueva_descripcion=desc, nueva_referencia=ref, commit="--commit" in _raw)
    print("\n=== RESULTADO ===")
    for k, v in res.items():
        print(f"  {k}: {v}")
