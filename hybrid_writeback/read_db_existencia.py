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


if __name__ == "__main__":
    cod = sys.argv[1] if len(sys.argv) > 1 else "00-002-024"
    tot, filas = existencia(cod)
    print(f"Existencia de {cod}:")
    for dep, ex, ap in filas:
        print(f"  deposito={dep!r} existencia={ex} apartada={ap}")
    print(f"TOTAL = {tot}")
