"""odbc_validate.py — Validación mínima de escritura ODBC (pocos popups trial).
Escribe con ODBC, lee/verifica con pydbisam (sin popup), y restaura. Con flush."""
import sys
import pyodbc
import pydbisam

CODIGO = "00-002-024"
TEST_VAL = 13.50
DATA_DIR = r"H:\HybridLite\HybridEmpresa\HybridDataBase"
DAT = DATA_DIR + r"\TCostoPrecioInv.Dat"
CONN = f"DRIVER={{DBISAM 4 ODBC Driver}};ConnectionType=Local;CatalogName={DATA_DIR};"


def p(*a):
    print(*a, flush=True)


def leer_usd():
    """Lee TIPO=1 PVPCONIMPUESTO1 via pydbisam (sin nag) + valida integridad."""
    db = pydbisam.PyDBISAM(DAT)
    idx = {n: i for i, n in enumerate(db.fields())}
    val, total = None, 0
    for row in db.rows():
        total += 1
        if str(row[idx["TPC_CODIGOPRODUCTO"]]).strip() == CODIGO and row[idx["TPC_TIPO"]] == 1:
            val = float(row[idx["TPC_PVPCONIMPUESTO1"]])
    return val, total


p("[*] Conectando ODBC (saldrá popup trial -> pulsa OK)...")
cn = pyodbc.connect(CONN, autocommit=True, timeout=20)
cur = cn.cursor()
p("[*] Conectado.")

orig, total = leer_usd()
p(f"[1] ANTES (pydbisam): {orig}  (filas íntegras: {total})")

p("[*] Escribiendo (puede salir otro popup -> OK)...")
cur.execute(f"UPDATE TCostoPrecioInv SET TPC_PVPCONIMPUESTO1 = {TEST_VAL:.4f} "
            f"WHERE TPC_CODIGOPRODUCTO = '{CODIGO}' AND TPC_TIPO = 1")
nuevo, total2 = leer_usd()
p(f"[2] DESPUÉS de UPDATE: {nuevo}  (filas íntegras: {total2})")
p(f"[3] ¿Escritura OK? {'SÍ ✅' if nuevo is not None and abs(nuevo-TEST_VAL)<0.01 else 'NO ❌'}")

p("[*] Restaurando original...")
cur.execute(f"UPDATE TCostoPrecioInv SET TPC_PVPCONIMPUESTO1 = {orig:.4f} "
            f"WHERE TPC_CODIGOPRODUCTO = '{CODIGO}' AND TPC_TIPO = 1")
fin, total3 = leer_usd()
p(f"[4] RESTAURADO: {fin}")
cur.close(); cn.close()
p("[*] Listo. Producto de prueba en su valor original.")
