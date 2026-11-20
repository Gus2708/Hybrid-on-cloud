"""invoice_product_identity.py — strict code/reference/description identity rules for
products created from a supplier invoice.

Pure logic, standard library only: no UI, DBISAM, network or Hybrid session. The
write-back flow (flujo_compra_real) injects the effects (catalog read, sleep).

Policy (set by the app, never inverted here): the scanned physical barcode is the
product code (PRD_CODIGO / Hybrid "Código") and the effective printed invoice
supplier code is the reference (PRD_REFERENCIA / Hybrid "Referencia"). Values are
literal: no trimming, case folding, zero stripping or truncation. A value that
cannot be stored and read back unchanged is rejected, never coerced.

Messages never include the values themselves (invoice data), only field names.
"""
import time
import unicodedata
from collections import namedtuple

MAX_CODIGO = 80         # same bound as the app's new-code preparation
MAX_REFERENCIA = 100    # same bound as the existing reference export/sync limit
CAMPOS = ("codigo", "referencia", "descripcion")

# colisiones._catalogo drops products whose code is "Fail" and reads a reference of
# "Fail" as empty, so such values could never be read back faithfully.
_CENTINELA_CATALOGO = "Fail"

IdentidadEsperada = namedtuple("IdentidadEsperada", CAMPOS)
Verificacion = namedtuple("Verificacion", "estado campos lecturas")


class IdentidadInvalida(ValueError):
    """A value is not supported by the strict path (nothing was touched)."""


def _literal(nombre, valor, maximo=None, obligatorio=True):
    if not isinstance(valor, str):
        raise IdentidadInvalida(f"{nombre}: debe ser texto (no se convierte otro tipo).")
    if not valor:
        if obligatorio:
            raise IdentidadInvalida(f"{nombre}: es obligatorio.")
        return valor
    if valor != valor.strip():
        raise IdentidadInvalida(f"{nombre}: tiene espacios al inicio o al final "
                                f"(no se recortan; se rechaza).")
    if any(unicodedata.category(c) == "Cc" for c in valor):
        raise IdentidadInvalida(f"{nombre}: contiene caracteres de control.")
    if maximo is not None and len(valor) > maximo:
        raise IdentidadInvalida(f"{nombre}: supera el máximo de {maximo} caracteres "
                                f"(no se trunca; se rechaza).")
    if valor == _CENTINELA_CATALOGO and nombre != "descripcion":
        raise IdentidadInvalida(f"{nombre}: el valor reservado del catálogo no se puede "
                                f"verificar al releer.")
    return valor


def validar_identidad(codigo, referencia, descripcion):
    """Return the expected identity or raise IdentidadInvalida. A missing reference
    (None or "") is accepted and expected to read back empty."""
    return IdentidadEsperada(
        _literal("codigo", codigo, MAX_CODIGO),
        _literal("referencia", "" if referencia is None else referencia, MAX_REFERENCIA,
                 obligatorio=False),
        _literal("descripcion", descripcion),
    )


def comparar(esperada, leida):
    """Names of the fields whose exact text differs; a missing key counts as different."""
    return tuple(c for c in CAMPOS if leida.get(c) != getattr(esperada, c))


def clasificar_existencia(esperada, catalogo):
    """Classify an expected identity against a catalog shaped like colisiones._catalogo
    ({"ref_de": {codigo: ref}, "desc_de": {codigo: descripcion}}).

    ("ausente", ())            no such code
    ("coincide", ())           code present with the exact expected reference/description
    ("discrepa", (campos...))  present but different, or present only under another
                               capitalization (treated as the same product, fail closed)."""
    ref_de, desc_de = catalogo["ref_de"], catalogo["desc_de"]
    if esperada.codigo not in ref_de:
        parecido = esperada.codigo.casefold()
        if any(c.casefold() == parecido for c in ref_de):
            return "discrepa", ("codigo",)
        return "ausente", ()
    campos = comparar(esperada, {"codigo": esperada.codigo,
                                 "referencia": ref_de[esperada.codigo],
                                 "descripcion": desc_de.get(esperada.codigo)})
    return ("discrepa", campos) if campos else ("coincide", ())


def verificar_con_reintentos(esperada, leer, intentos, espera, dormir=time.sleep,
                             errores_lectura=(OSError,)):
    """Bounded fresh read-back of a just-saved product, tolerant of read-after-save lag.

    `leer(codigo)` returns {"codigo","referencia","descripcion"} or None when absent and
    raises one of `errores_lectura` when the catalog cannot be read. It is called at most
    `intentos` times, sleeping `espera` seconds between attempts only. Read-only: this
    never saves, creates or retries a write. The final state is that of the last attempt:
    "ok" | "ausente" | "discrepa" (with the differing field names) | "ilegible"."""
    estado, campos = "ilegible", ()
    for n in range(1, intentos + 1):
        try:
            leida = leer(esperada.codigo)
        except errores_lectura:
            estado, campos = "ilegible", ()
        else:
            if leida is None:
                estado, campos = "ausente", ()
            else:
                campos = comparar(esperada, leida)
                estado = "discrepa" if campos else "ok"
        if estado == "ok":
            return Verificacion("ok", (), n)
        if n < intentos:
            dormir(espera)
    return Verificacion(estado, campos, intentos)
