import pydbisam
import os

base = r"h:\HybridLite\HybridEmpresa\HybridDataBase"
files = ["TTransaccionvta.dat", "TDetalleVta.dat"]

for fname in files:
    try:
        filepath = os.path.join(base, fname)
        db = pydbisam.PyDBISAM(filepath)
        print(f"\n==== {fname} Columns ====")
        for col in db._columns:
            print(col.name)
    except Exception as e:
        print(f"Error: {e}")
