import pydbisam
import sys

try:
    filepath = r"h:\HybridLite\HybridEmpresa\HybridDataBase\TClientes.dat"
    db = pydbisam.PyDBISAM(filepath)
    print("Methods:", dir(db))
except Exception as e:
    print(f"Error: {e}")
