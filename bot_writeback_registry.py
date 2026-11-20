"""
bot_writeback_registry.py — Shared registry between listener_writeback and sync_ajustes
to prevent creating duplicate [Local Inv ID: ...] mirror orders in Supabase for
stock adjustments already originated from the app.

Flow:
1. Before committing a stock adjustment in HybridLite, listener_writeback records an
   in-flight intent (machine, max THT_AUTOINCREMENT before commit, expected items).
2. After commit, listener_writeback reads DBISAM to promote the newly created
   THT_AUTOINCREMENT ID(s) into `bot_inv_ids` and removes the fulfilled intent.
3. If sync_ajustes runs concurrently or DBISAM is briefly unreadable after commit,
   sync_ajustes checks `es_ajuste_del_bot(...)` using both `bot_inv_ids` and active
   in-flight intents (same machine + strictly newer ID + 1-to-1 item subset match).
4. Pure pre-commit failures cancel the in-flight intent so subsequent manual adjustments
   are never falsely suppressed.
"""
from contextlib import contextmanager
import json
import os
import socket
import time
import uuid

REGISTRY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bot_writeback_ajustes.json")
LOCK_FILE = REGISTRY_FILE + ".lock"
INFLIGHT_TTL_SECONDS = 900
_LOCK_STALE_SECONDS = 10.0
_LOCK_TIMEOUT_SECONDS = 2.5


def _column_names(db) -> list[str]:
    if hasattr(db, "fields") and callable(db.fields):
        return list(db.fields())
    return [c.name for c in db._columns]


def _resolve_db_dir(base_db_dir: str | None = None) -> str | None:
    if base_db_dir:
        return base_db_dir
    try:
        from config import RUTA_INVENTARIO
        if RUTA_INVENTARIO:
            return os.path.dirname(RUTA_INVENTARIO)
    except Exception:
        return None
    return None


@contextmanager
def _registry_lock():
    lock_path = REGISTRY_FILE + ".lock"
    parent = os.path.dirname(lock_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    deadline = time.monotonic() + _LOCK_TIMEOUT_SECONDS
    acquired = False
    while time.monotonic() < deadline:
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            try:
                os.write(fd, f"{os.getpid()}\n".encode("ascii"))
            finally:
                os.close(fd)
            acquired = True
            break
        except FileExistsError:
            try:
                if time.time() - os.path.getmtime(lock_path) > _LOCK_STALE_SECONDS:
                    os.remove(lock_path)
                    continue
            except OSError:
                pass
            time.sleep(0.05)
    if not acquired:
        raise TimeoutError(f"Could not acquire lock for {REGISTRY_FILE}")
    try:
        yield
    finally:
        try:
            os.remove(lock_path)
        except OSError:
            pass


def _empty_registry() -> dict:
    return {"bot_inv_ids": [], "inflight": []}


def _load_unlocked() -> dict:
    if not os.path.exists(REGISTRY_FILE):
        return _empty_registry()
    try:
        with open(REGISTRY_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
        if not isinstance(raw, dict):
            return _empty_registry()
        raw_ids = raw.get("bot_inv_ids") or []
        bot_ids = sorted({int(x) for x in raw_ids})
        inflight = [e for e in (raw.get("inflight") or []) if isinstance(e, dict)]
        return {"bot_inv_ids": bot_ids, "inflight": inflight}
    except Exception:
        return _empty_registry()


def _save_unlocked(data: dict) -> None:
    payload = {
        "bot_inv_ids": sorted({int(x) for x in (data.get("bot_inv_ids") or [])}),
        "inflight": list(data.get("inflight") or []),
    }
    parent = os.path.dirname(REGISTRY_FILE)
    if parent:
        os.makedirs(parent, exist_ok=True)
    tmp_path = f"{REGISTRY_FILE}.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        for attempt in range(5):
            try:
                os.replace(tmp_path, REGISTRY_FILE)
                return
            except PermissionError:
                if attempt == 4:
                    raise
                time.sleep(0.02)
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass


def _prune_inflight(data: dict, current_time: float) -> bool:
    kept = []
    changed = False
    for entry in data.get("inflight") or []:
        try:
            created = float(entry.get("created_at"))
        except (TypeError, ValueError):
            changed = True
            continue
        if current_time - created <= INFLIGHT_TTL_SECONDS:
            kept.append(entry)
        else:
            changed = True
    data["inflight"] = kept
    return changed


def obtener_machine_actual() -> str:
    return (os.environ.get("COMPUTERNAME") or socket.gethostname() or "").strip()


def obtener_max_inv_id(base_db_dir: str | None = None) -> int | None:
    db_dir = _resolve_db_dir(base_db_dir)
    if not db_dir:
        return None
    path_header = os.path.join(db_dir, "TTransaccioninv.dat")
    try:
        import pydbisam
        db_hdr = pydbisam.PyDBISAM(path_header)
        cols = _column_names(db_hdr)
        idx_id = cols.index("THT_AUTOINCREMENT")
        max_id = 0
        for row in db_hdr.rows():
            if row is None:
                continue
            lid = int(row[idx_id])
            if lid > max_id:
                max_id = lid
        return max_id
    except Exception:
        return None


def _item_key(codigo: str, delta: float) -> tuple[str, int]:
    return (str(codigo).strip().upper(), round(float(delta) * 100))


def _extract_qty(item: dict) -> float | None:
    if "cantidad" in item and item.get("cantidad") is not None:
        return float(item["cantidad"])
    if "delta" in item and item.get("delta") is not None:
        return float(item["delta"])
    return None


def _subset_consume(remaining_items: list[dict], doc_details: list[dict]) -> list[dict] | None:
    doc_keys = []
    for item in doc_details:
        qty = _extract_qty(item)
        if qty is None or round(qty * 100) == 0:
            continue
        doc_keys.append(_item_key(item.get("codigo", ""), qty))
    if not doc_keys:
        return None

    pool = list(remaining_items)
    for key in doc_keys:
        match_idx = None
        for idx, rem in enumerate(pool):
            if _item_key(rem.get("codigo", ""), rem.get("delta", 0.0)) == key:
                match_idx = idx
                break
        if match_idx is None:
            return None
        pool.pop(match_idx)
    return pool


def registrar_inflight(
    orden_id,
    items: list[dict],
    max_inv_id_before: int | None = None,
    machine: str | None = None,
    now: float | None = None,
) -> str:
    current_time = time.time() if now is None else float(now)
    machine_name = (machine if machine is not None else obtener_machine_actual()).strip()
    normalized = []
    for item in items:
        qty = _extract_qty(item)
        if qty is None or round(qty * 100) == 0:
            continue
        normalized.append({"codigo": str(item.get("codigo", "")).strip(), "delta": float(qty)})

    token = uuid.uuid4().hex
    entry = {
        "token": token,
        "orden_id": orden_id,
        "machine": machine_name,
        "created_at": current_time,
        "max_inv_id_before": int(max_inv_id_before) if max_inv_id_before is not None else None,
        "remaining_items": normalized,
    }
    with _registry_lock():
        data = _load_unlocked()
        _prune_inflight(data, current_time)
        data["inflight"].append(entry)
        _save_unlocked(data)
    return token


def cancelar_inflight(token: str) -> None:
    if not token:
        return
    with _registry_lock():
        data = _load_unlocked()
        before = len(data["inflight"])
        data["inflight"] = [e for e in data["inflight"] if e.get("token") != token]
        if len(data["inflight"]) != before:
            _save_unlocked(data)


def es_ajuste_del_bot(
    local_id: int,
    machine: str,
    details: list[dict],
    now: float | None = None,
) -> bool:
    lid = int(local_id)
    machine_norm = (machine or "").strip().upper()
    current_time = time.time() if now is None else float(now)

    with _registry_lock():
        data = _load_unlocked()
        pruned = _prune_inflight(data, current_time)

        if lid in data["bot_inv_ids"]:
            if pruned:
                _save_unlocked(data)
            return True

        if not machine_norm:
            if pruned:
                _save_unlocked(data)
            return False

        matched = False
        for idx, entry in enumerate(data["inflight"]):
            entry_machine = str(entry.get("machine") or "").strip().upper()
            if not entry_machine or entry_machine != machine_norm:
                continue
            max_before = entry.get("max_inv_id_before")
            if max_before is not None and lid <= int(max_before):
                continue
            leftover = _subset_consume(entry.get("remaining_items") or [], details)
            if leftover is not None:
                data["bot_inv_ids"].append(lid)
                if not leftover:
                    data["inflight"].pop(idx)
                else:
                    entry["remaining_items"] = leftover
                matched = True
                break

        if matched or pruned:
            _save_unlocked(data)
        return matched


def confirmar_desde_dbisam(
    token: str,
    base_db_dir: str | None = None,
    now: float | None = None,
) -> list[int]:
    if not token:
        return []
    current_time = time.time() if now is None else float(now)

    with _registry_lock():
        data = _load_unlocked()
        pruned = _prune_inflight(data, current_time)
        entry = next((e for e in data["inflight"] if e.get("token") == token), None)
        if entry is None:
            if pruned:
                _save_unlocked(data)
            return []
        entry_machine = str(entry.get("machine") or "").strip().upper()
        max_before = entry.get("max_inv_id_before")
        remaining = list(entry.get("remaining_items") or [])
        known_ids = set(data["bot_inv_ids"])
        if pruned:
            _save_unlocked(data)

    if not entry_machine or not remaining:
        return []

    db_dir = _resolve_db_dir(base_db_dir)
    if not db_dir:
        return []

    path_hdr = os.path.join(db_dir, "TTransaccioninv.dat")
    path_det = os.path.join(db_dir, "TDetalleInv.Dat")

    try:
        import pydbisam
        db_hdr = pydbisam.PyDBISAM(path_hdr)
        cols_h = _column_names(db_hdr)
        idx_h_id = cols_h.index("THT_AUTOINCREMENT")
        idx_h_status = cols_h.index("THT_STATUS")
        idx_h_machine = cols_h.index("THT_MACHINENAME")

        candidates = []
        for row in db_hdr.rows():
            if row is None:
                continue
            if str(row[idx_h_status]).strip() == "4":
                continue
            lid = int(row[idx_h_id])
            if lid in known_ids:
                continue
            if max_before is not None and lid <= int(max_before):
                continue
            row_machine = str(row[idx_h_machine] or "").strip().upper()
            if row_machine != entry_machine:
                continue
            candidates.append(lid)

        if not candidates:
            return []
        candidates.sort()
        candidate_set = set(candidates)

        db_det = pydbisam.PyDBISAM(path_det)
        cols_d = _column_names(db_det)
        idx_d_parent = cols_d.index("TBT_OPERACION_AUTOINCREMENT")
        idx_d_code = cols_d.index("TBT_CODIGO")
        idx_d_qty = cols_d.index("TBT_CANTIDAD")

        details_by_parent: dict[int, list[dict]] = {}
        for row in db_det.rows():
            if row is None:
                continue
            parent_id = int(row[idx_d_parent])
            if parent_id not in candidate_set:
                continue
            qty = float(row[idx_d_qty])
            if round(qty * 100) == 0:
                continue
            details_by_parent.setdefault(parent_id, []).append({
                "codigo": str(row[idx_d_code]).strip(),
                "cantidad": qty,
            })
    except Exception:
        return []

    matched_docs: list[tuple[int, list[dict]]] = []
    working_remaining = list(remaining)
    for lid in candidates:
        doc_details = details_by_parent.get(lid)
        if not doc_details:
            continue
        leftover = _subset_consume(working_remaining, doc_details)
        if leftover is not None:
            matched_docs.append((lid, doc_details))
            working_remaining = leftover
            if not working_remaining:
                break

    if not matched_docs:
        return []

    matched_ids = [lid for lid, _ in matched_docs]
    with _registry_lock():
        data = _load_unlocked()
        _prune_inflight(data, current_time)
        before_merge_ids = set(data["bot_inv_ids"])
        for lid in matched_ids:
            if lid not in before_merge_ids and lid not in data["bot_inv_ids"]:
                data["bot_inv_ids"].append(lid)

        cur_idx = next((i for i, e in enumerate(data["inflight"]) if e.get("token") == token), None)
        if cur_idx is not None:
            cur_entry = data["inflight"][cur_idx]
            cur_remaining = list(cur_entry.get("remaining_items") or [])
            for lid, doc_details in matched_docs:
                # Only consume docs that were not already consumed concurrently by sync_ajustes
                if lid not in before_merge_ids:
                    leftover = _subset_consume(cur_remaining, doc_details)
                    if leftover is not None:
                        cur_remaining = leftover
            if not cur_remaining:
                data["inflight"].pop(cur_idx)
            else:
                cur_entry["remaining_items"] = cur_remaining

        _save_unlocked(data)
    return matched_ids
