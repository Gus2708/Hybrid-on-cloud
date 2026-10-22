"""Build a Serrucho -> Maxcam equivalence table for manual review.

Matching order: exact code (internal code / barcode / reference vs Maxcam sku or
alt code) -> name similarity. Output: equivalencias.csv (sorted so the rows that
need review come first).

Usage: python build_equivalencias.py [path/to/MAESTRO_ACTUAL.csv]
"""
import csv
import json
import os
import re
import sys
import unicodedata
from collections import defaultdict
from difflib import SequenceMatcher

from maxcam_api import search

HERE = os.path.dirname(os.path.abspath(__file__))
MAESTRO = sys.argv[1] if len(sys.argv) > 1 else r"C:\Proyect\backend serrucho\MAESTRO_ACTUAL.csv"
CACHE = os.path.join(HERE, "maxcam_catalogo.json")
OUT = os.path.join(HERE, "equivalencias.csv")
SKU_RE = re.compile(r"(?<![\w.-])(\d{1,2}-\d{3,4})(?![\w-])")
STOP = {"DE", "PARA", "CON", "X", "Y", "EL", "LA", "UND", "UNID", "PCS"}


def load_maxcam():
    if os.path.exists(CACHE):
        with open(CACHE, encoding="utf-8") as f:
            return json.load(f)
    items, page = [], 1
    while True:
        d = search(page=page, per_page=100)
        items += d["items"]
        if len(items) >= d["total"] or not d["items"]:
            break
        page += 1
    with open(CACHE, "w", encoding="utf-8") as f:
        json.dump(items, f)
    return items


def norm(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().upper()
    return re.sub(r"[^A-Z0-9/.\" ]+", " ", s)


def tokens(s):
    return [t for t in norm(s).split() if t not in STOP]


def nums(toks):
    return {t for t in toks if any(c.isdigit() for c in t)}


def main():
    mx = load_maxcam()
    for it in mx:
        it["_tok"] = tokens(it["nombre"])
        it["_norm"] = " ".join(it["_tok"])
    by_code = {}
    by_sku = {it["sku"].strip().upper(): i for i, it in enumerate(mx)}
    inv = defaultdict(list)
    for i, it in enumerate(mx):
        for k in (it["sku"], it.get("codigo_alt")):
            if k and k.strip():
                by_code.setdefault(k.strip().upper(), i)
        for t in set(it["_tok"]):
            inv[t].append(i)

    with open(MAESTRO, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))

    out = []
    for r in rows:
        codes = [r["CODIGO_INTERNO"], r["CODIGO_BARRAS"], r["REFERENCIA"]]
        hit = next((by_code[c.strip().upper()] for c in codes
                    if c and c.strip().upper() in by_code and c.strip() != "SIN_CODIGO"), None)
        cands, metodo, conf = [], "", ""
        n_desc = " ".join(tokens(r["DESCRIPCION"]))
        # a SKU found in the description only counts if the names also look alike
        in_desc = [by_sku[m] for m in SKU_RE.findall(r["DESCRIPCION"].upper()) if m in by_sku
                   and SequenceMatcher(None, n_desc, mx[by_sku[m]]["_norm"]).ratio() >= 0.6]
        if hit is not None:
            cands, metodo, conf = [(hit, 1.0)], "codigo", "ALTA"
        elif in_desc:
            cands, metodo, conf = [(in_desc[-1], 1.0)], "sku_en_descripcion", "ALTA"
        else:
            toks = tokens(r["DESCRIPCION"])
            n_s = " ".join(toks)
            votes = defaultdict(int)
            for t in set(toks):
                if len(inv.get(t, ())) < 800:  # skip ultra-common tokens
                    for i in inv.get(t, ()):
                        votes[i] += 1
            short = sorted(votes, key=votes.get, reverse=True)[:15]
            scored = sorted(((i, SequenceMatcher(None, n_s, mx[i]["_norm"]).ratio()) for i in short),
                            key=lambda x: x[1], reverse=True)[:3]
            cands, metodo = scored, "nombre"
            if scored:
                same_nums = nums(toks) == nums(mx[scored[0][0]]["_tok"])
                conf = "MEDIA" if scored[0][1] >= 0.85 and same_nums else (
                    "BAJA" if scored[0][1] >= 0.6 else "SIN_MATCH")
            else:
                conf = "SIN_MATCH"
        row = {"serrucho_codigo": r["CODIGO_INTERNO"], "serrucho_descripcion": r["DESCRIPCION"],
               "serrucho_barras": r["CODIGO_BARRAS"], "serrucho_existencia": r["EXISTENCIA"],
               "metodo": metodo, "confianza": conf}
        for n in range(3):
            if n < len(cands) and conf != "SIN_MATCH":
                i, sc = cands[n]
                row.update({f"maxcam{n+1}_sku": mx[i]["sku"], f"maxcam{n+1}_nombre": mx[i]["nombre"],
                            f"maxcam{n+1}_score": round(sc, 2)})
            else:
                row.update({f"maxcam{n+1}_sku": "", f"maxcam{n+1}_nombre": "", f"maxcam{n+1}_score": ""})
        row["revisado_ok"] = ""
        out.append(row)

    order = {"MEDIA": 0, "BAJA": 1, "ALTA": 2, "SIN_MATCH": 3}
    out.sort(key=lambda x: order[x["confianza"]])
    with open(OUT, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]))
        w.writeheader()
        w.writerows(out)
    counts = defaultdict(int)
    for o in out:
        counts[o["confianza"]] += 1
    print(dict(counts), "->", OUT)


if __name__ == "__main__":
    main()
