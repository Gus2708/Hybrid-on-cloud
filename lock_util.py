import os
import time
from contextlib import contextmanager

LOCK_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sync.lock")

@contextmanager
def acquire_lock(timeout=60):
    """
    Intenta adquirir un bloqueo global mediante un archivo.
    Si el archivo existe, espera hasta 'timeout' segundos.
    """
    start_time = time.time()
    acquired = False
    
    while time.time() - start_time < timeout:
        try:
            # os.O_CREAT | os.O_EXCL asegura que la creación falle si el archivo ya existe (atómico)
            fd = os.open(LOCK_FILE, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            with os.fdopen(fd, 'w') as f:
                f.write(str(os.getpid()))
            acquired = True
            break
        except FileExistsError:
            # Verificar si el proceso que creó el lock sigue vivo (protección contra crashes)
            # En Windows esto es más complejo, por ahora simplemente esperamos.
            time.sleep(1)
            continue
            
    if not acquired:
        raise TimeoutError(f"No se pudo adquirir el bloqueo de sincronización después de {timeout}s.")
        
    try:
        yield
    finally:
        if acquired:
            try:
                os.remove(LOCK_FILE)
            except:
                pass

def is_locked():
    return os.path.exists(LOCK_FILE)
