"""
odbc_write_test.py — PRUEBA de escritura vía ODBC (modo LOCAL file-server, SEGURO).

Escribe el precio USD con impuesto del producto de prueba, lo verifica con dos
lectores independientes (ODBC y pydbisam), confirma que la tabla sigue íntegra,
y RESTAURA el valor original. El producto de prueba termina sin cambios.

Uso:  python odbc_write_test.py 00-002-024 13.50
"""
import sys
import pyodbc
import pydbisam

CODIGO = sys.argv[1] if len(sys.argv) > 1 else "00-002-024"
TEST_VAL = float(sys.argv[2]) if len(sys.argv) > 2 else 13.50

DATA_DIR = r"H:\HybridLite\HybridEmpresa\HybridDataBase"
DAT = DATA_DIR + r"\TCostoPrecioInv.Dat"
# Driver READ-WRITE (sin '(Read-Only)') en modo local
CONN = f"DRIVER={{DBISAM 4 ODBC Driver}};ConnectionType=Local;CatalogName={DATA_DIR};"


def leer_odbc(cur, codigo):
    cur.execute("SELECT TPC_TIPO, TPC_PVPCONIMPUESTO1 FROM TCostoPrecioInv "
                f"WHERE TPC_CODIGOPRODUCTO = '{codigo}' ORDER BY TPC_TIPO")
    return {row[0]: float(row[1]) for row in cur.fetchall()}


def leer_pydbisam(codigo):
    """Lector independiente para verificación cruzada + chequeo de integridad."""
    db = pydbisam.PyDBISAM(DAT)
    idx = {n: i for i, n in enumerate(db.fields())}
    out, total = {}, 0
    for row in db.rows():           # recorrer TODO valida que la tabla está íntegra
        total += 1
        if str(row[idx["TPC_CODIGOPRODUCTO"]]).strip() == codigo:
            out[row[idx["TPC_TIPO"]]] = float(row[idx["TPC_PVPCONIMPUESTO1"]])
    return out, total


def main():
    print(f"=== Prueba de escritura ODBC para {CODIGO} ===\n")

    # Conexión read-write
    cn = pyodbc.connect(CONN, autocommit=True, timeout=15)
    cur = cn.cursor()
    print("[1] Conexión LOCAL read-write: OK")

    # Estado original
    antes = leer_odbc(cur, CODIGO)
    print(f"[2] ANTES (ODBC): {antes}")
    if 1 not in antes:
        print("    ! No existe registro TIPO=1 (USD). Abortando."); return
    original = antes[1]

    # saneo simple del código (alfanumérico y guiones)
    cod_safe = "".join(c for c in CODIGO if c.isalnum() or c in "-_.")

    try:
        # Escribir valor de prueba en el registro USD (TIPO=1) — SQL con literales
        n = cur.execute(
            f"UPDATE TCostoPrecioInv SET TPC_PVPCONIMPUESTO1 = {TEST_VAL:.4f} "
            f"WHERE TPC_CODIGOPRODUCTO = '{cod_safe}' AND TPC_TIPO = 1").rowcount
        print(f"[3] UPDATE a {TEST_VAL}: {n} fila(s) afectada(s)")

        # Verificar con ODBC
        despues = leer_odbc(cur, CODIGO)
        print(f"[4] DESPUÉS (ODBC):     {despues}")

        # Verificar con lector independiente + integridad de la tabla
        py, total = leer_pydbisam(CODIGO)
        print(f"[5] DESPUÉS (pydbisam): {py}  | filas totales leídas OK: {total}")

        ok = abs(despues.get(1, -1) - TEST_VAL) < 0.01 and abs(py.get(1, -1) - TEST_VAL) < 0.01
        print(f"[6] ¿Escritura verificada por ambos lectores?  {'SÍ ✅' if ok else 'NO ❌'}")
    finally:
        # RESTAURAR siempre
        cur.execute(f"UPDATE TCostoPrecioInv SET TPC_PVPCONIMPUESTO1 = {original:.4f} "
                    f"WHERE TPC_CODIGOPRODUCTO = '{cod_safe}' AND TPC_TIPO = 1")
        rest = leer_odbc(cur, CODIGO)
        print(f"[7] RESTAURADO a original {original}: ahora {rest}")

    cur.close(); cn.close()
    print("\n=== Fin. El producto de prueba quedó en su valor original. ===")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\n[ERROR] {e}")
