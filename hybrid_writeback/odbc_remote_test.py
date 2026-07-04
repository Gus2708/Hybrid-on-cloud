"""odbc_remote_test.py — Encuentra la cadena de conexión REMOTA correcta (read-only).
Prueba keywords de host (RemoteAddress/RemoteHost) y nombres de base (DatabaseName)."""
import pyodbc

RO = "DBISAM 4 ODBC Driver (Read-Only)"
IP = "192.168.1.118"
BASE_AUTH = f"RemotePort=12005;RemoteUser=admin;RemotePassword=DBAdmin;"

SQL = ("SELECT TPC_CODIGOPRODUCTO, TPC_TIPO, TPC_PVPCONIMPUESTO1 "
       "FROM TCostoPrecioInv WHERE TPC_CODIGOPRODUCTO = '00-002-024'")

def intentar(desc, cs, do_query=False):
    print(f"\n=== {desc} ===")
    try:
        cn = pyodbc.connect(cs, autocommit=True, timeout=8)
        print("    [CONECTADO AL SERVIDOR/BASE]")
        if do_query:
            cur = cn.cursor()
            try:
                cur.execute(SQL)
                for r in cur.fetchall():
                    print(f"    fila: {tuple(r)}")
            except Exception as qe:
                print(f"    [query falló] {str(qe)[:160]}")
            cur.close()
        cn.close()
        return True
    except Exception as e:
        print(f"    [FALLO] {str(e)[:190]}")
        return False

# Paso 1: ¿qué keyword de host conecta al servidor? (sin base, para ver si pasa de 127.0.0.1)
print("########## PASO 1: keyword de host ##########")
for kw in ["RemoteAddress", "RemoteHost"]:
    intentar(f"host via {kw}={IP} (sin base)",
             f"DRIVER={{{RO}}};ConnectionType=Remote;{kw}={IP};{BASE_AUTH}")

# Paso 2: con base de datos (DatabaseName / CatalogName) y varios nombres
print("\n########## PASO 2: nombre de base ##########")
for hostkw in ["RemoteAddress", "RemoteHost"]:
    for dbkw in ["DatabaseName", "CatalogName"]:
        for db in ["HybridEmpresa", "HybridDataBase", "Hybrid", "HybridLite"]:
            cs = (f"DRIVER={{{RO}}};ConnectionType=Remote;{hostkw}={IP};{BASE_AUTH}{dbkw}={db};")
            if intentar(f"{hostkw}={IP} {dbkw}={db}", cs, do_query=True):
                print(f"\n    >>> CONEXIÓN VÁLIDA: host={hostkw}, base={dbkw}={db}")
                raise SystemExit(0)
print("\n(No conectó a ninguna base con esos nombres — ver errores arriba.)")
