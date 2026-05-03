"""
app.py — API REST para Ferretería El Serrucho.

Endpoints:
    GET /health                         -> Estado del servidor
    GET /api/v1/buscar?q=<texto>        -> Búsqueda de productos
    GET /api/v1/tasa                    -> Tasa USD/Bs actual
    GET /api/v1/producto/<codigo>       -> Detalle de un producto por código

Parámetros de /buscar:
    q        Texto a buscar (requerido)
    limit    Máximo de resultados (default: 50, max: 200)
    offset   Desplazamiento para paginación (default: 0)
    stock    Si stock=1, devuelve solo productos con existencia > 0
"""
from flask import Flask, request, jsonify
import os
import csv
import unicodedata
import re
import time
import subprocess
import json
from typing import List, Dict

from config import (
    TASA_BS_DEFAULT, 
    CSV_SOURCE_PATH,
    RUTA_INVENTARIO,
    RUTA_PRECIOS,
    RUTA_EXISTENCIA
)

app = Flask(__name__)

# ─── Protocolo V22: Normalización de búsqueda ────────────────────────────────
# Stop words en español para inventario de ferretería
STOP_WORDS = {
    "DE", "DEL", "LA", "EL", "PARA", "CON", "Y", "EN", "X",
    "UN", "UNA", "LAS", "LOS", "POR", "AL", "A", "O", "E",
    "SU", "SE", "SI", "NO", "NI", "QUE", "ES", "SON", "MAS",
}

# Prefijos de unidades de medida que se suelen escribir pegados (ej: 1/2", 3/4")
_RE_FRACTION = re.compile(r"(\d+)\s*/\s*(\d+)")

# Separadores (espacios, guiones, comas)
_RE_SPLIT = re.compile(r"[\s\-,]+")


def remove_accents(s: str) -> str:
    """Elimina tildes y diacríticos."""
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")


def normalize_query(text: str) -> str:
    """
    Normalización V22:
    1. Mayúsculas
    2. Eliminar acentos
    3. Eliminar stop words
    4. Normalizar fracciones: '1 / 2' -> '1/2'
    5. Singularizar (quitar 'S' final en palabras >3 chars)
    Devuelve string con tokens separados por espacio.
    """
    if not text:
        return ""
    s = text.upper()
    s = remove_accents(s)
    # Normalizar fracciones con espacios -> sin espacios
    s = _RE_FRACTION.sub(r"\1/\2", s)
    # Separar tokens
    tokens = [t for t in _RE_SPLIT.split(s) if t and t not in STOP_WORDS]
    # Singularizar: quitar S final en palabras de >3 chars (no números, no fracciones)
    result = []
    for w in tokens:
        if len(w) > 3 and w.endswith("S") and not w[-2:].isdigit():
            w = w[:-1]
        result.append(w)
    return " ".join(result)


# ─── Cache local del CSV ──────────────────────────────────────────────────────
_CSV_PATH = CSV_SOURCE_PATH
_LOCAL_CACHE: List[Dict] = []
_CACHE_MTIME: float = 0.0


def _load_inventory_if_needed():
    """Recarga el CSV si el archivo fue modificado desde la última carga."""
    global _LOCAL_CACHE, _CACHE_MTIME
    try:
        mtime = os.path.getmtime(_CSV_PATH)
    except OSError:
        return

    if mtime <= _CACHE_MTIME and _LOCAL_CACHE:
        return  # No cambió

    items = []
    try:
        with open(_CSV_PATH, "r", encoding="utf-8-sig", errors="ignore") as f:
            reader = csv.reader(f)
            next(reader, None)  # Skip header
            for row in reader:
                if not row or len(row) < 7:
                    continue
                code = (row[0] or "").strip()
                if not code or not code[0].isdigit():
                    continue
                desc = (row[1] or "").strip().strip('"').upper()
                unidad = (row[2] or "").strip()
                barcode = (row[3] or "").strip()
                try:
                    costo = float(row[4]) if row[4].strip() else 0.0
                except ValueError:
                    costo = 0.0
                try:
                    precio_usd = float(row[5]) if row[5].strip() else 0.0
                except ValueError:
                    precio_usd = 0.0
                try:
                    existencia = float(row[6]) if row[6].strip() else 0.0
                except ValueError:
                    existencia = 0.0

                items.append({
                    "codigo_interno": code,
                    "descripcion":    desc,
                    "unidad":         unidad,
                    "codigo_barras":  barcode,
                    "costo":          costo,
                    "precio_venta":   precio_usd,
                    "existencia":     existencia,
                })
    except Exception as e:
        print(f"[APP] Error cargando CSV: {e}")
        return

    _LOCAL_CACHE = items
    _CACHE_MTIME = mtime
    print(f"[APP] CSV cargado: {len(items)} productos (mtime actualizado).")


def _enrich(item: Dict) -> Dict:
    """Agrega precio_bs calculado con la tasa actual."""
    tasa = TASA_BS_DEFAULT
    precio_bs = round(item["precio_venta"] * tasa, 2)
    return {**item, "precio_bs": precio_bs, "tasa_bs": tasa}


# ─── Endpoints ────────────────────────────────────────────────────────────────

@app.route("/health", methods=["GET"])
def health():
    _load_inventory_if_needed()
    
    # Obtener última sync
    last_sync_str = "Nunca"
    last_sync_ts = 0.0
    base_dir = os.path.dirname(os.path.abspath(__file__))
    sync_file = os.path.join(base_dir, "last_sync.json")
    
    if os.path.exists(sync_file):
        try:
            with open(sync_file, "r") as f:
                data = json.load(f)
                last_sync_str = data.get("last_sync", "Nunca")
                last_sync_ts = data.get("timestamp", 0.0)
        except: pass
            
    # Comprobar si HybridLite tiene archivos más nuevos que la última sync
    hybrid_paths = [RUTA_INVENTARIO, RUTA_PRECIOS, RUTA_EXISTENCIA, CSV_SOURCE_PATH]
    needs_sync = False
    newest_file_ts = 0.0
    
    for path in hybrid_paths:
        if os.path.exists(path):
            mtime = os.path.getmtime(path)
            if mtime > newest_file_ts:
                newest_file_ts = mtime
            if mtime > last_sync_ts + 2: # Margen de 2 seg
                needs_sync = True
    
    return jsonify({
        "status": "ok",
        "productos_en_cache": len(_LOCAL_CACHE),
        "last_sync": last_sync_str,
        "needs_sync": needs_sync,
        "csv_existe": os.path.exists(CSV_SOURCE_PATH),
        "tasa_bs": TASA_BS_DEFAULT,
    }), 200


@app.route("/api/v1/tasa", methods=["GET"])
def tasa():
    """Devuelve la tasa de cambio USD->Bs actualmente configurada."""
    return jsonify({
        "tasa_bs_por_usd": TASA_BS_DEFAULT,
        "fuente": "config/TASA_BS env var",
    })


@app.route("/api/v1/buscar", methods=["GET"])
def buscar():
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify({"query": q, "count": 0, "total_encontrados": 0, "results": []})

    # Paginación
    try:
        limit = min(int(request.args.get("limit", 50)), 200)
    except ValueError:
        limit = 50
    try:
        offset = max(int(request.args.get("offset", 0)), 0)
    except ValueError:
        offset = 0

    solo_con_stock = request.args.get("stock", "0") == "1"

    # Asegurar cache actualizado
    _load_inventory_if_needed()

    norm = normalize_query(q)
    tokens = norm.split() if norm else [q.upper()]

    # Filtrar
    encontrados = []
    for item in _LOCAL_CACHE:
        if solo_con_stock and item["existencia"] <= 0:
            continue
        haystack = item["descripcion"] + " " + item["codigo_interno"] + " " + item["codigo_barras"]
        if all(t in haystack for t in tokens):
            encontrados.append(item)

    # Ordenar: primero los que tienen stock, luego por descripción
    encontrados.sort(key=lambda x: (-x["existencia"], x["descripcion"]))

    total = len(encontrados)
    pagina = encontrados[offset : offset + limit]

    return jsonify({
        "query":            q,
        "query_norm":       norm,
        "total_encontrados": total,
        "count":            len(pagina),
        "offset":           offset,
        "limit":            limit,
        "results":          [_enrich(r) for r in pagina],
    })


@app.route("/api/v1/producto/<codigo>", methods=["GET"])
def detalle_producto(codigo: str):
    """Devuelve el detalle de un producto por código interno o código de barras."""
    _load_inventory_if_needed()
    codigo = codigo.strip().upper()
    for item in _LOCAL_CACHE:
        if item["codigo_interno"].upper() == codigo or item["codigo_barras"] == codigo:
            return jsonify(_enrich(item))
    return jsonify({"error": "Producto no encontrado", "codigo": codigo}), 404


@app.route("/api/v1/sync/run", methods=["POST", "GET"])
def trigger_sync():
    """Ejecuta el proceso de sincronización bajo demanda."""
    try:
        # Ejecuta sync.py en modo 'once'
        # Usamos sys.executable para asegurar que use el mismo interprete de python
        import sys
        result = subprocess.run(
            [sys.executable, "sync.py", "once"],
            capture_output=True,
            text=True,
            check=False
        )
        if result.returncode == 0:
            return jsonify({
                "status": "success",
                "message": "Sincronización completada exitosamente",
                "output": result.stdout[-500:] # Últimos 500 caracteres del log
            }), 200
        else:
            return jsonify({
                "status": "error",
                "message": "Error durante la sincronización",
                "error": result.stderr
            }), 500
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    app.run(host="0.0.0.0", port=port, debug=debug)
