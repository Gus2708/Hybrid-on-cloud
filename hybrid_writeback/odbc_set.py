"""odbc_set.py — Fija TPC_PVPCONIMPUESTO1 (TIPO=1, USD) de un producto via ODBC.
Solo ASCII. Uso: python odbc_set.py <codigo> <valor>"""
import sys
import pyodbc
import pydbisam

CODIGO = sys.argv[1]
VAL = float(sys.argv[2])
DATA_DIR = r"H:\HybridLite\HybridEmpresa\HybridDataBase"
DAT = DATA_DIR + r"\TCostoPrecioInv.Dat"
CONN = f"DRIVER={{DBISAM 4 ODBC Driver}};ConnectionType=Local;CatalogName={DATA_DIR};"


def leer():
    db = pydbisam.PyDBISAM(DAT)
    idx = {n: i for i, n in enumerate(db.fields())}
    for row in db.rows():
        if str(row[idx["TPC_CODIGOPRODUCTO"]]).strip() == CODIGO and row[idx["TPC_TIPO"]] == 1:
            return float(row[idx["TPC_PVPCONIMPUESTO1"]])
    return None


cod = "".join(c for c in CODIGO if c.isalnum() or c in "-_.")
print(f"[*] Antes: {leer()}", flush=True)
print("[*] Conectando ODBC (pulsa OK en el popup trial)...", flush=True)
cn = pyodbc.connect(CONN, autocommit=True, timeout=20)
cur = cn.cursor()
cur.execute(f"UPDATE TCostoPrecioInv SET TPC_PVPCONIMPUESTO1 = {VAL:.4f} "
            f"WHERE TPC_CODIGOPRODUCTO = '{cod}' AND TPC_TIPO = 1")
cur.close(); cn.close()
print(f"[*] Despues: {leer()}", flush=True)
print("[OK] Listo.", flush=True)
