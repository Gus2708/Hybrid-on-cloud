"""odbc_test.py — Prueba de conexión ODBC a DBISAM (SOLO LECTURA).
1) Confirma lectura LOCAL read-only. 2) Busca el CatalogName válido para REMOTO."""
import sys
import pyodbc

CODIGO = sys.argv[1] if len(sys.argv) > 1 else "00-002-024"
DATA_DIR = r"H:\HybridLite\HybridEmpresa\HybridDataBase"

# SQL con literal (el driver DBISAM rechazó el parámetro '?')
SQL = ("SELECT TPC_CODIGOPRODUCTO, TPC_TIPO, TPC_COSTOACTUAL, TPC_PVPSINIMPUESTO1, "
       f"TPC_PVPCONIMPUESTO1 FROM TCostoPrecioInv WHERE TPC_CODIGOPRODUCTO = '{CODIGO}'")

RO = "DBISAM 4 ODBC Driver (Read-Only)"

def probar(nombre, conn_str, do_query=True):
    print(f"\n=== {nombre} ===")
    try:
        cn = pyodbc.connect(conn_str, autocommit=True, timeout=10)
        print("    [CONECTADO]")
        if do_query:
            cur = cn.cursor()
            cur.execute(SQL)
            rows = cur.fetchall()
            for r in rows:
                print(f"    fila: {tuple(r)}")
            if not rows:
                print(f"    (sin filas para {CODIGO})")
            cur.close()
        cn.close()
        return True
    except Exception as e:
        print(f"    [FALLO] {str(e)[:200]}")
        return False

# 1) LOCAL read-only (confirma lectura)
probar("LOCAL read-only", f"DRIVER={{{RO}}};ConnectionType=Local;CatalogName={DATA_DIR};")

# 2) REMOTO read-only: probar nombres de catálogo
print("\n----- Buscando CatalogName válido para REMOTO (read-only) -----")
for cat in ["HybridEmpresa", "HybridDataBase", "Hybrid", "HybridLite", "Empresa",
            "HybridEmpresa\\HybridDataBase", "Default"]:
    cs = (f"DRIVER={{{RO}}};ConnectionType=Remote;RemoteHost=PRINCIPAL;RemotePort=12005;"
          f"RemoteUser=admin;RemotePassword=DBAdmin;CatalogName={cat};")
    if probar(f"REMOTE cat='{cat}'", cs):
        print(f"    >>> CATALOGO VÁLIDO: {cat}")
        break
