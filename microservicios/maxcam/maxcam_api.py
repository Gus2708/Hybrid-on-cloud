"""Maxcam catalog API (Flask) on top of the authenticated Supabase RPCs.

Run: python maxcam_api.py  ->  http://localhost:5001
Endpoints:
    GET /productos?q=&marca=&rubro=&rubro_hijo=&precio_min=&precio_max=
                  &disponibles=1&agotados=0&orden=&pagina=1&por_pagina=40
    GET /productos/<sku>
    GET /marcas
    GET /categorias
"""
import requests
from flask import Flask, jsonify, request

import maxcam_auth as auth
import maxcam_index

app = Flask(__name__)
MAX_PER_PAGE = 100
SUCURSAL = "BQ"  # Barquisimeto: the only branch that serves our zone


def rpc(name, body):
    headers = dict(auth.HEADERS, Authorization="Bearer " + auth.get_access_token())
    r = requests.post(f"{auth.BASE}/rest/v1/rpc/{name}", headers=headers, json=body, timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"{name} failed: {r.status_code} {r.text[:200]}")
    return r.json()


def search(page=1, per_page=40, q="", **f):
    return rpc("catalogo_contexto", {
        "p_pagina": page,
        "p_por_pagina": per_page,
        "p_orden": f.get("orden", ""),
        "p_busqueda": q,
        "p_rubro": f.get("rubro", ""),
        "p_rubro_hijo": f.get("rubro_hijo", ""),
        "p_marca": f.get("marca", ""),
        "p_origen": "",
        "p_disponibles": f.get("disponibles", True),
        "p_agotados": f.get("agotados", True),
        "p_precio_min": f.get("precio_min"),
        "p_precio_max": f.get("precio_max"),
    })


def _num(name):
    v = request.args.get(name)
    return float(v) if v not in (None, "") else None


def _flag(name, default):
    v = request.args.get(name)
    return default if v is None else v.lower() in ("1", "true", "yes")


@app.errorhandler(Exception)
def on_error(e):
    return jsonify(error=str(e)), 502


@app.get("/productos")
def productos():
    per_page = min(int(request.args.get("por_pagina", 40)), MAX_PER_PAGE)
    data = search(
        page=int(request.args.get("pagina", 1)),
        per_page=per_page,
        q=request.args.get("q", ""),
        marca=request.args.get("marca", ""),
        rubro=request.args.get("rubro", ""),
        rubro_hijo=request.args.get("rubro_hijo", ""),
        orden=request.args.get("orden", ""),
        precio_min=_num("precio_min"),
        precio_max=_num("precio_max"),
        disponibles=_flag("disponibles", True),
        agotados=_flag("agotados", True),
    )
    return jsonify(total=data["total"], items=data["items"])


@app.get("/productos/<sku>")
def producto(sku):
    items = search(per_page=20, q=sku)["items"]
    hit = next((i for i in items if i["sku"].lower() == sku.lower()), None)
    return (jsonify(hit), 200) if hit else (jsonify(error="not found"), 404)


@app.get("/disponibilidad")
def disponibilidad():
    """Is a (sold-out) Serrucho product available at Maxcam?

    Codes (codigo, referencia, barras) go through the hash index; `descripcion`
    is only a text-search fallback when no code matches.
    """
    codes = [c for k in ("codigo", "referencia", "barras")
             for c in request.args.getlist(k) if c and c != "SIN_CODIGO"]
    sku, matched = maxcam_index.lookup(search, codes)
    metodo = "hash"
    if sku is None and request.args.get("descripcion"):
        hits = search(per_page=5, q=request.args["descripcion"])["items"]
        sku = hits[0]["sku"] if hits else None
        metodo = "texto"
    if sku is None:
        return jsonify(encontrado=False, disponible=False)
    live = next((i for i in search(per_page=20, q=sku)["items"] if i["sku"] == sku), None)
    if live is None:
        return jsonify(encontrado=False, disponible=False)
    # Only Barquisimeto (BQ) counts: other branches don't serve this zone.
    stock_bq = next((s["disponible"] for s in live["stock_por_sucursal"]
                     if s["sucursal"] == SUCURSAL), 0)
    return jsonify(encontrado=True, disponible=stock_bq > 0, stock_bq=stock_bq,
                   metodo=metodo, coincidio_con=matched,
                   sku=live["sku"], nombre=live["nombre"], precio=live["precio"],
                   cant_caja=live["cant_caja"], stock_por_sucursal=live["stock_por_sucursal"])


@app.get("/marcas")
def marcas():
    return jsonify(rpc("get_marcas", {}))


@app.get("/categorias")
def categorias():
    return jsonify(search(per_page=1)["categorias"])


if __name__ == "__main__":
    import threading
    threading.Thread(target=lambda: maxcam_index.lookup(search, []), daemon=True).start()
    app.run(port=5001)
