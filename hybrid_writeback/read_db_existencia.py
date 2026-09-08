"""read_db_existencia.py — Lee la existencia de un producto desde TExistenciaInv.Dat
con pydbisam (sin ODBC, sin popups). Uso: python read_db_existencia.py <codigo>"""
import sys
import pydbisam

RUTA = r"H:\HybridLite\HybridEmpresa\HybridDataBase\TExistenciaInv.Dat"


def existencia(codigo):
    """Devuelve (total, filas) donde filas = [(deposito, existencia, apartada), ...]"""
    db = pydbisam.PyDBISAM(RUTA)
    idx = {n: i for i, n in enumerate(db.fields())}
    filas, total = [], 0.0
    for row in db.rows():
        if str(row[idx["EIN_CODIGOPRODUCTO"]]).strip() == codigo:
            dep = row[idx["EIN_CODIGODEPOSITO"]]
            ex = float(row[idx["EIN_EXISTENCIA"]] or 0)
            ap = float(row[idx["EIN_EXISTENCIAAPARTADA"]] or 0)
            filas.append((dep, ex, ap))
            total += ex
    return total, filas


def existencia_batch(codigos):
    """Devuelve dict {codigo: (total, filas)} en una SOLA pasada por TExistenciaInv.Dat."""
    cod_set = {str(c).strip() for c in codigos}
    db = pydbisam.PyDBISAM(RUTA)
    idx = {n: i for i, n in enumerate(db.fields())}
    cod_i = idx.get("EIN_CODIGOPRODUCTO")
    dep_i = idx.get("EIN_CODIGODEPOSITO")
    ex_i = idx.get("EIN_EXISTENCIA")
    ap_i = idx.get("EIN_EXISTENCIAAPARTADA")
    res = {c: [0.0, []] for c in cod_set}
    if cod_i is None:
        return {c: (0.0, []) for c in cod_set}
    for row in db.rows():
        c = str(row[cod_i]).strip()
        if c in res:
            dep = row[dep_i] if dep_i is not None else ""
            ex = float(row[ex_i] or 0) if ex_i is not None else 0.0
            ap = float(row[ap_i] or 0) if ap_i is not None else 0.0
            res[c][0] += ex
            res[c][1].append((dep, ex, ap))
    return {c: (tot, filas) for c, (tot, filas) in res.items()}



if __name__ == "__main__":
    cod = sys.argv[1] if len(sys.argv) > 1 else "00-002-024"
    tot, filas = existencia(cod)
    print(f"Existencia de {cod}:")
    for dep, ex, ap in filas:
        print(f"  deposito={dep!r} existencia={ex} apartada={ap}")
    print(f"TOTAL = {tot}")
