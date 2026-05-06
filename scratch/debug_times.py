import os, json

paths = [
    r'H:\HybridLite\HybridEmpresa\HybridDataBase\TInventario.dat',
    r'H:\HybridLite\HybridEmpresa\HybridDataBase\TCostoPrecioInv.Dat',
    r'H:\HybridLite\HybridEmpresa\HybridDataBase\TExistenciaInv.Dat',
    r'H:\HybridLite\HybridEmpresa\HybridDataBase\TTransaccionvta.dat',
    r'H:\HybridLite\HybridEmpresa\HybridDataBase\TDetalleVta.dat',
    r'H:\HybridLite\HybridEmpresa\HybridDataBase\TClientes.dat',
]

print("=== Archivos .dat ===")
for p in paths:
    if os.path.exists(p):
        mtime = os.path.getmtime(p)
        print(f"  {os.path.basename(p):30s} mtime = {mtime:.0f}")

print("\n=== Timestamps de sync ===")
for f in ['last_sync.json', 'ventas_last_sync.json']:
    try:
        with open(f) as fh:
            data = json.load(fh)
            ts = data.get("timestamp", 0)
            print(f"  {f:30s} ts    = {ts:.0f}")
    except Exception as e:
        print(f"  {f}: {e}")

print("\n=== Comparaciones ===")
try:
    with open('last_sync.json') as fh:
        sync_ts = json.load(fh).get("timestamp", 0)
    with open('ventas_last_sync.json') as fh:
        ventas_ts = json.load(fh).get("timestamp", 0)
except:
    sync_ts = 0
    ventas_ts = 0

for p in paths:
    if os.path.exists(p):
        mtime = os.path.getmtime(p)
        fname = os.path.basename(p).lower()
        ref_ts = ventas_ts if "vta" in fname or "cliente" in fname or "trans" in fname else sync_ts
        diff = mtime - ref_ts
        triggered = diff > 5
        print(f"  {os.path.basename(p):30s} diff={diff:+.0f}s  trigger={triggered}")
