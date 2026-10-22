"""Client for the Corporación Norte catalog API.

    productos.php?brand=cn&solo_cats=1            -> category list
    productos.php?brand=cn&categoria=<name>       -> every product of that category

The site only answers from a connection it accepts (the store PC); VPN exit IPs get a 403.
Set CORPNORTE_OFFLINE=1 to serve everything from the local catalogo.json snapshot,
which is how the code is tested away from the store.
"""
import json
import os
import time

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = "https://catalogocorporacionnorte.com/api/productos.php"
BRAND = "cn"
SNAPSHOT = os.path.join(HERE, "catalogo.json")
PAUSE = 0.4  # seconds between requests while downloading everything
OFFLINE = os.environ.get("CORPNORTE_OFFLINE") == "1"


def _get(params):
    r = requests.get(BASE, params=params, timeout=60,
                     headers={"User-Agent": "api-corporacionnorte/0.1"})
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code} for {params}: {r.text[:120]}")
    return r.json()


def load_snapshot():
    if not os.path.exists(SNAPSHOT):
        return []
    with open(SNAPSHOT, encoding="utf-8") as f:
        return json.load(f)


def save_snapshot(products):
    tmp = SNAPSHOT + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(products, f, ensure_ascii=False)
    os.replace(tmp, SNAPSHOT)  # never leave a half-written snapshot


def category_names(data):
    """Accepts the shapes solo_cats may come in: list of names or of objects."""
    if isinstance(data, dict):
        for key in ("categorias", "cats", "categories"):
            if key in data:
                data = data[key]
                break
    names = []
    for item in data if isinstance(data, list) else []:
        if isinstance(item, str):
            names.append(item)
        elif isinstance(item, dict):
            val = item.get("categoria") or item.get("nombre") or item.get("name")
            if val:
                names.append(val)
    return names


def fetch_category(name):
    """Fresh products of one category (this is the live-stock call)."""
    if OFFLINE:
        return [p for p in load_snapshot() if p.get("categoria") == name]
    data = _get({"brand": BRAND, "categoria": name})
    return data.get("productos", []) if isinstance(data, dict) else []


def fetch_all(progress=None):
    """Every product of every category, de-duplicated by id."""
    if OFFLINE:
        return load_snapshot()
    names = category_names(_get({"brand": BRAND, "solo_cats": 1}))
    if not names:
        raise RuntimeError("no categories returned")
    products = {}
    for i, name in enumerate(names, 1):
        items = fetch_category(name)
        for p in items:
            products[p["id"]] = p
        if progress:
            progress(i, len(names), name, len(items))
        time.sleep(PAUSE)
    return list(products.values())
