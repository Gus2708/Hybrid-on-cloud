"""Embed the Maxcam catalog and upload the vectors to maxcam_embedding (Serrucho Supabase).

Incremental by md5 hash of the embedded text. Needs in .env:
    OPENROUTER_API_KEY, SERRUCHO_SUPABASE_URL, SERRUCHO_SERVICE_KEY
    (optional) EMBEDDING_MODEL, default openai/text-embedding-3-small

Usage:
    python embed_maxcam.py --dry   # shows what it would embed and the estimated cost
    python embed_maxcam.py         # embeds and uploads what is new or changed
"""
import hashlib
import sys
import time

import requests

import build_equivalencias as be
from maxcam_auth import ENV

# Must be the same model as productos_embedding or the vectors are not comparable;
# changing it means re-embedding both tables.
MODEL, DIMS = ENV.get("EMBEDDING_MODEL", "openai/text-embedding-3-small"), 1536
EMBED_BATCH, WRITE_BATCH = 256, 40
PRICE_PER_M = 0.02

SB = ENV["SERRUCHO_SUPABASE_URL"] if "SERRUCHO_SUPABASE_URL" in ENV else ""
SB_HEADERS = {"apikey": ENV.get("SERRUCHO_SERVICE_KEY", ""),
              "Authorization": "Bearer " + ENV.get("SERRUCHO_SERVICE_KEY", ""),
              "Content-Type": "application/json"}


def text_of(p):
    # Same spirit as the Serrucho text: description plus category, no prices.
    cat = (p.get("rubro_hijo") or p.get("rubro") or "").strip()
    return p["nombre"].strip() + (f" | categoria: {cat}" if cat else "")


def md5(t):
    return hashlib.md5(t.encode()).hexdigest()


def embed(texts):
    r = requests.post("https://openrouter.ai/api/v1/embeddings",
                      headers={"Authorization": "Bearer " + ENV["OPENROUTER_API_KEY"]},
                      json={"model": MODEL, "input": texts, "dimensions": DIMS}, timeout=120)
    if not r.ok:
        raise RuntimeError(f"OpenRouter {r.status_code}: {r.text[:300]}")
    j = r.json()
    return [d["embedding"] for d in j["data"]], (j.get("usage") or {}).get("total_tokens", 0)


def existing_hashes():
    out, off = {}, 0
    while True:
        r = requests.get(f"{SB}/rest/v1/maxcam_embedding?select=sku,hash_desc&order=sku.asc"
                         f"&offset={off}&limit=1000", headers=SB_HEADERS, timeout=60)
        r.raise_for_status()
        rows = r.json()
        out.update({x["sku"]: x["hash_desc"] for x in rows})
        if len(rows) < 1000:
            return out
        off += 1000


def upload(rows):
    for attempt in range(1, 5):
        r = requests.post(f"{SB}/rest/v1/maxcam_embedding?on_conflict=sku",
                          headers={**SB_HEADERS, "Prefer": "resolution=merge-duplicates,return=minimal"},
                          json=rows, timeout=120)
        if r.ok:
            return
        time.sleep(0.5 * attempt)
    raise RuntimeError(f"upload failed: {r.status_code} {r.text[:200]}")


def main():
    dry = "--dry" in sys.argv
    items = {p["sku"]: p for p in be.load_maxcam()}.values()  # sku is the primary key
    prev = {} if dry and not SB else existing_hashes()
    todo = [p for p in items if prev.get(p["sku"]) != md5(text_of(p))]
    est_tokens = sum(len(text_of(p)) for p in todo) // 4
    print(f"{len(items)} products, {len(todo)} to embed, ~{est_tokens} tokens, "
          f"~${est_tokens / 1e6 * PRICE_PER_M:.4f}")
    if dry:
        return
    done = 0
    for i in range(0, len(todo), EMBED_BATCH):
        batch = todo[i:i + EMBED_BATCH]
        vectors, _ = embed([text_of(p) for p in batch])
        rows = [{"sku": p["sku"], "nombre": p["nombre"], "marca": p.get("marca"),
                 "rubro": p.get("rubro"), "rubro_hijo": p.get("rubro_hijo"),
                 "codigo_alt": p.get("codigo_alt") or None, "hash_desc": md5(text_of(p)),
                 "embedding": "[" + ",".join(map(str, v)) + "]", "modelo": MODEL}
                for p, v in zip(batch, vectors)]
        for j in range(0, len(rows), WRITE_BATCH):
            upload(rows[j:j + WRITE_BATCH])
        done += len(batch)
        print(f"{done}/{len(todo)}")


if __name__ == "__main__":
    main()
