"""Corporación Norte catalog API (Flask).

Run: python corpnorte_api.py  ->  http://localhost:5002
Endpoints:
    GET /disponibilidad?codigo=&referencia=&barras=   in stock at Corporación Norte?
    GET /productos?q=&marca=&categoria=&pagina=1&por_pagina=40
    GET /categorias
    GET /marcas
"""
import unicodedata
from urllib.parse import quote

from flask import Flask, jsonify, request

import corpnorte_client as client
import corpnorte_index as index

app = Flask(__name__)
MAX_PER_PAGE = 100


def _fold(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return s.lower()


IMAGE_BASE = "https://catalogocorporacionnorte.com/uploads/productos/"


def _imagen(codigo):
    """The site names the file after the code with "/" replaced by "-". The extension
    varies per product (the site itself falls back jpg -> png -> jpeg -> webp), so this
    returns the jpg URL and the app handles the fallback."""
    return IMAGE_BASE + quote(codigo.strip().replace("/", "-"), safe="-_.") + ".jpg"


def _public(p, en_vivo=None):
    out = {
        "imagen": _imagen(p["codigo"]),
        "codigo": p["codigo"], "nombre": (p.get("nombre") or "").strip(),
        "marca": p.get("composicion"), "categoria": p.get("categoria"),
        "subcategoria": p.get("subcategoria"), "precio": p.get("precio"),
        "stock": p.get("stock"), "bulto": p.get("bulto"), "piezas": p.get("colores"),
        "oferta": bool(p.get("oferta")), "nuevo": bool(p.get("nuevo")),
    }
    if en_vivo is not None:
        out["en_vivo"] = en_vivo
    return out


@app.errorhandler(Exception)
def on_error(e):
    return jsonify(error=str(e)), 502


@app.get("/health")
def health():
    return jsonify(status="ok", service="corpnorte")


@app.get("/disponibilidad")
def disponibilidad():
    """`disponible` is stock > 0: the site's own `disponible` flag is always 1."""
    codes = [c for k in ("codigo", "referencia", "barras")
             for c in request.args.getlist(k) if c and c != "SIN_CODIGO"]
    found, matched = index.lookup(codes)
    if found is None:
        return jsonify(encontrado=False, disponible=False)
    live, en_vivo = found, False
    try:  # live stock: refetch the product's category
        fresh = next((p for p in client.fetch_category(found["categoria"])
                      if p["id"] == found["id"]), None)
        if fresh:
            live, en_vivo = fresh, True
    except Exception as e:
        print(f"live stock failed, serving indexed data: {e!r}")
    stock = live.get("stock") or 0
    return jsonify(encontrado=True, disponible=stock > 0, metodo="hash",
                   coincidio_con=matched, **_public(live, en_vivo))


@app.get("/productos")
def productos():
    toks = _fold(request.args.get("q", "")).split()
    marca = _fold(request.args.get("marca", ""))
    cat = _fold(request.args.get("categoria", ""))
    hits = []
    for p in index.products():
        hay = _fold(f"{p.get('codigo')} {p.get('nombre')} {p.get('composicion')}")
        if (all(t in hay for t in toks) and (not marca or marca == _fold(p.get("composicion")))
                and (not cat or cat == _fold(p.get("categoria")))):
            hits.append(p)
    per = min(int(request.args.get("por_pagina", 40)), MAX_PER_PAGE)
    page = max(int(request.args.get("pagina", 1)), 1)
    return jsonify(total=len(hits), items=[_public(p) for p in hits[(page - 1) * per:page * per]])


@app.get("/categorias")
def categorias():
    counts = {}
    for p in index.products():
        key = (p.get("categoria"), p.get("subcategoria"))
        counts[key] = counts.get(key, 0) + 1
    return jsonify([{"categoria": c, "subcategoria": s, "total": n} for (c, s), n in sorted(
        counts.items(), key=lambda kv: (str(kv[0][0]), str(kv[0][1])))])


@app.get("/marcas")
def marcas():
    counts = {}
    for p in index.products():
        m = (p.get("composicion") or "").strip()
        counts[m] = counts.get(m, 0) + 1
    return jsonify([{"marca": m, "total": n} for m, n in sorted(counts.items())])


if __name__ == "__main__":
    import threading
    threading.Thread(target=index.ensure_fresh, daemon=True).start()
    app.run(port=5002)
