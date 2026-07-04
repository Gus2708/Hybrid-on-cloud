"""read_db_precio.py — Lee (SOLO LECTURA) los precios/costos de un producto
directamente desde TCostoPrecioInv.Dat (DBISAM), para verificar el estado real
guardado, sin depender de la interfaz.

Uso:  python read_db_precio.py 00-002-024
"""
import sys
import pydbisam

RUTA = r"H:\HybridLite\HybridEmpresa\HybridDataBase\TCostoPrecioInv.Dat"

CAMPOS_INTERES = [
    "TPC_CODIGOPRODUCTO", "TPC_TIPO",
    "TPC_COSTOACTUAL", "TPC_COSTOREFERENCIAL",
    "TPC_PVPSINIMPUESTO1", "TPC_PVPCONIMPUESTO1",
    "TPC_MTOUTILIDAD1", "TPC_ULTFECHA", "TPC_ULTUSUARIO",
]


def main():
    if len(sys.argv) < 2:
        print("Uso: python read_db_precio.py <codigo>")
        return
    codigo = sys.argv[1].strip()

    db = pydbisam.PyDBISAM(RUTA)
    campos = db.fields()
    idx = {n: i for i, n in enumerate(campos)}
    cod_i = idx["TPC_CODIGOPRODUCTO"]

    encontrados = 0
    for row in db.rows():
        if str(row[cod_i]).strip() == codigo:
            encontrados += 1
            print(f"\n--- Registro #{encontrados} de {codigo} ---")
            for c in CAMPOS_INTERES:
                if c in idx:
                    print(f"  {c:<22} = {row[idx[c]]}")
    if not encontrados:
        print(f"No se encontró el producto {codigo} en TCostoPrecioInv.")
    else:
        print(f"\nTotal registros de precio para {codigo}: {encontrados}")


if __name__ == "__main__":
    main()
