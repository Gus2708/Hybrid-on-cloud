import pydbisam
import os

base = r"h:\HybridLite\HybridEmpresa\HybridDataBase"
files = ["TTransaccionvta.dat", "TDetalleVta.dat", "TClientes.dat"]

for fname in files:
    try:
        filepath = os.path.join(base, fname)
        db = pydbisam.PyDBISAM(filepath)
        print(f"\n==== {fname} ====")
        print("Columns:")
        for col in db._columns:
            # Safely print type
            tval = getattr(col.type, '_value_', col.type)
            print(f"  {col.name} - type: {tval}, size: {col.size}")
        
        print(f"Total Rows: {db._total_rows}")
        
        print("First 2 rows:")
        count = 0
        for row in db.rows():
            # row is a tuple, but pydbisam might return 'Fail' for unknown types
            print(row)
            count += 1
            if count >= 2:
                break
    except Exception as e:
        import traceback
        traceback.print_exc()
