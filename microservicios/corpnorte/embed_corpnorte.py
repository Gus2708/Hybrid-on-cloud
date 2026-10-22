"""Embed the Corporación Norte catalog and upload the vectors to corpnorte_embedding.

Incremental by md5 of the embedded text. Needs in .env:
    OPENROUTER_API_KEY, SERRUCHO_SUPABASE_URL, SERRUCHO_SERVICE_KEY
    (optional) EMBEDDING_MODEL, default openai/text-embedding-3-small

The model must match productos_embedding or the vectors are not comparable.

Usage:
    python embed_corpnorte.py --dry   # what it would embed and the estimated cost
    python embed_corpnorte.py         # embeds and uploads what is new or changed
Reads catalogo.json (run snapshot.py first, with no VPN).
"""
import hashlib
import sys
import time

import requests

import corpnorte_client as client
from corpnorte_env import ENV

MODEL, DIMS = ENV.get("EMBEDDING_MODEL", "openai/text-embedding-3-small"), 1536
EMBED_BATCH, WRITE_BATCH = 256, 40
PRICE_PER_M = 0.02

SB = ENV.get("SERRUCHO_SUPABASE_URL", "")
KEY = ENV.get("SERRUCHO_SERVICE_KEY", "")
SB_HEADERS = {"apikey": KEY, "Authorization": "Bearer " + KEY, "Content-Type": "application/json"}


def text_of(p):
    parts = [(p.get("nombre") or "").strip()]
    if p.get("colores"):
        parts.append(str(p["colores"]).strip())  # holds the piece count, e.g. "7 PIEZAS"
    if p.get("composicion"):
        parts.append(str(p["composicion"]).strip())  # holds the brand
    cat = p.get("subcategoria") or p.get("categoria")
    text = " | ".join(x for x in parts if x)
    return text + (f" | categoria: {cat}" if cat else "")


def md5(t):
    return hashlib.md5(t.encode()).hexdigest()


def embed(texts):
    r = requests.post("https://openrouter.ai/api/v1/embeddings",
                      headers={"Authorization": "Bearer " + ENV["OPENROUTER_API_KEY"]},
                      json={"model": MODEL, "input": texts, "dimensions": DIMS}, timeout=120)
    if not r.ok:
        raise RuntimeError(f"OpenRouter {r.status_code}: {r.text[:300]}")
    return [d["embedding"] for d in r.json()["data"]]


def existing_hashes():
    out, off = {}, 0
    while True:
        r = requests.get(f"{SB}/rest/v1/corpnorte_embedding?select=codigo,hash_desc&order=codigo.asc"
                         f"&offset={off}&limit=1000", headers=SB_HEADERS, timeout=60)
        r.raise_for_status()
        rows = r.json()
        out.update({x["codigo"]: x["hash_desc"] for x in rows})
        if len(rows) < 1000:
            return out
        off += 1000


def upload(rows):
    for attempt in range(1, 5):
        r = requests.post(f"{SB}/rest/v1/corpnorte_embedding?on_conflict=codigo",
                          headers={**SB_HEADERS, "Prefer": "resolution=merge-duplicates,return=minimal"},
                          json=rows, timeout=120)
        if r.ok:
            return
        time.sleep(0.5 * attempt)
    raise RuntimeError(f"upload failed: {r.status_code} {r.text[:200]}")


def main():
    dry = "--dry" in sys.argv
    items = {p["codigo"].strip(): p for p in client.load_snapshot() if p.get("codigo")}.values()
    prev = {} if dry and not SB else existing_hashes()
    todo = [p for p in items if prev.get(p["codigo"].strip()) != md5(text_of(p))]
    est = sum(len(text_of(p)) for p in todo) // 4
    print(f"{len(items)} products, {len(todo)} to embed, ~{est} tokens, ~${est / 1e6 * PRICE_PER_M:.4f}")
    if dry:
        return
    done = 0
    for i in range(0, len(todo), EMBED_BATCH):
        batch = todo[i:i + EMBED_BATCH]
        vectors = embed([text_of(p) for p in batch])
        rows = [{"codigo": p["codigo"].strip(), "nombre": (p.get("nombre") or "").strip(),
                 "marca": p.get("composicion"), "categoria": p.get("categoria"),
                 "subcategoria": p.get("subcategoria"), "hash_desc": md5(text_of(p)),
                 "embedding": "[" + ",".join(map(str, v)) + "]", "modelo": MODEL}
                for p, v in zip(batch, vectors)]
        for j in range(0, len(rows), WRITE_BATCH):
            upload(rows[j:j + WRITE_BATCH])
        done += len(batch)
        print(f"{done}/{len(todo)}")


if __name__ == "__main__":
    main()
