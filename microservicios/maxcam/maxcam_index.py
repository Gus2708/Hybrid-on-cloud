"""Hash index over the Maxcam catalog: O(1) lookup by code at query time.

The index (code -> product id/sku) is rebuilt lazily when older than INDEX_TTL;
stock is never served from it, callers fetch live stock for the matched SKU.
"""
import threading
import time

INDEX_TTL = 3600
_lock = threading.Lock()
_state = {"built_at": 0.0, "by_code": {}, "total": 0}


def norm(code):
    return (code or "").strip().upper()


def _build(search):
    by_code, items, page = {}, 0, 1
    while True:
        d = search(page=page, per_page=100)
        for it in d["items"]:
            items += 1
            for key in (it["sku"], it.get("codigo_alt")):
                if norm(key):
                    by_code.setdefault(norm(key), it["sku"])
        if items >= d["total"] or not d["items"]:
            break
        page += 1
    _state.update(built_at=time.time(), by_code=by_code, total=items)


def lookup(search, codes):
    """Return the Maxcam SKU for the first code found in the hash index, else None."""
    with _lock:
        if time.time() - _state["built_at"] > INDEX_TTL:
            _build(search)
        by_code = _state["by_code"]
    for c in codes:
        sku = by_code.get(norm(c))
        if sku:
            return sku, c
    return None, None
