"""In-memory hash index (code -> product) over the Corporación Norte catalog.

It starts from the local snapshot (instant) and refreshes from the site in the
background when older than INDEX_TTL. Stock is never read from here: the API asks
the site for the product's category on every availability query.
"""
import threading
import time

import corpnorte_client as client

INDEX_TTL = 3600
_lock = threading.Lock()
_state = {"built_at": 0.0, "by_code": {}, "products": [], "refreshing": False}


def norm(code):
    return (code or "").strip().upper()


def _install(products, built_at):
    by_code = {}
    for p in products:
        if norm(p.get("codigo")):
            by_code.setdefault(norm(p["codigo"]), p)
    _state.update(products=products, by_code=by_code, built_at=built_at)


def _refresh():
    try:
        products = client.fetch_all()
        if products:
            if not client.OFFLINE:
                client.save_snapshot(products)
            with _lock:
                _install(products, time.time())
    except Exception as e:  # keep serving the previous index
        print(f"index refresh failed: {e!r}")
    finally:
        _state["refreshing"] = False


def ensure_fresh():
    """Load the snapshot on first use; trigger a background refresh when stale."""
    with _lock:
        if not _state["products"]:
            snap = client.load_snapshot()
            if snap:
                _install(snap, 0.0)  # built_at 0 -> stale, so a refresh follows
        have = bool(_state["products"])
        stale = time.time() - _state["built_at"] > INDEX_TTL
        start = have and stale and not _state["refreshing"] and not client.OFFLINE
        if start:
            _state["refreshing"] = True
    if start:
        threading.Thread(target=_refresh, daemon=True).start()
    if not have:  # no snapshot yet: the first build must finish before answering
        if client.OFFLINE:
            raise RuntimeError("offline mode but no catalogo.json snapshot")
        _refresh_blocking()


def _refresh_blocking():
    with _lock:
        if _state["products"]:
            return
    products = client.fetch_all()
    client.save_snapshot(products)
    with _lock:
        _install(products, time.time())


def lookup(codes):
    """First product whose code is in the hash index, with the code that matched."""
    ensure_fresh()
    by_code = _state["by_code"]
    for c in codes:
        p = by_code.get(norm(c))
        if p:
            return p, c
    return None, None


def products():
    ensure_fresh()
    return _state["products"]
