"""alias_manager.py — Gestor de alias y equivalencias de códigos de proveedores.

Permite traducir códigos de productos que en listas de precios o facturas de
proveedores vienen con una nomenclatura distinta a la registrada en el
catálogo maestro de HybridLiteOS (ej. 'THINNER-01' -> 'THINNER-M').
"""
import os
import json
import logging

log = logging.getLogger("alias_manager")

DIR = os.path.dirname(os.path.abspath(__file__))
RUTA_ALIAS = os.path.join(DIR, "alias_proveedores.json")


def cargar_alias():
    """Carga el diccionario de alias desde el archivo JSON."""
    if not os.path.isfile(RUTA_ALIAS):
        return {}
    try:
        with open(RUTA_ALIAS, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        log.warning("No se pudo leer %s: %s", RUTA_ALIAS, e)
        return {}


def resolver_alias(codigo, proveedor=None):
    """Resuelve un código de proveedor al código registrado en HybridLiteOS.

    Args:
        codigo (str): Código a buscar (ej. 'THINNER-01').
        proveedor (str, optional): Nombre o código del proveedor para filtrar.

    Returns:
        str: El código correspondiente en HybridLiteOS (o el original si no tiene alias).
    """
    if not codigo:
        return codigo

    cod_clean = str(codigo).strip()
    tabla = cargar_alias()

    if cod_clean in tabla:
        info = tabla[cod_clean]
        if isinstance(info, dict):
            prov_match = True
            if proveedor and info.get("proveedor"):
                prov_match = proveedor.upper() in info["proveedor"].upper()
            if prov_match:
                destino = info.get("codigo_sistema", cod_clean)
                log.info("Alias resuelto: %s -> %s (proveedor=%s)", cod_clean, destino, info.get("proveedor"))
                return destino
        elif isinstance(info, str):
            return info

    return cod_clean


def registrar_alias(codigo_proveedor, codigo_sistema, proveedor="", descripcion="", notas=""):
    """Registra una nueva equivalencia de código de forma persistente."""
    cod_p = str(codigo_proveedor).strip()
    cod_s = str(codigo_sistema).strip()
    tabla = cargar_alias()

    tabla[cod_p] = {
        "codigo_sistema": cod_s,
        "proveedor": proveedor.strip().upper(),
        "descripcion": descripcion.strip(),
        "notas": notas.strip()
    }

    try:
        with open(RUTA_ALIAS, "w", encoding="utf-8") as f:
            json.dump(tabla, f, indent=2, ensure_ascii=False)
        log.info("Alias guardado: %s -> %s", cod_p, cod_s)
        return True
    except Exception as e:
        log.error("Error guardando alias %s -> %s: %s", cod_p, cod_s, e)
        return False
