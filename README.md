# Hybrid-on-Cloud — Bidirectional Bridge Between a Legacy POS and the Cloud

Production backend that keeps a closed, 20-year-old Delphi/DBISAM point-of-sale
system (**HybridLite**) in sync with a **Supabase/PostgreSQL** database — in both
directions. It has been running unattended, 24/7, in a working hardware store
since May 2026.

> **Read path:** DBISAM `.DAT` files → Python extractors → incremental diff →
> Supabase.
> **Write path:** cloud request queue → supervised UI automation → HybridLite.

---

## The interesting problem

The POS stores its data in **DBISAM 4** tables and exposes no API. Its ODBC
driver is a paid add-on that was not licensed, and the `.DAT` files are the live
database of a business that is open for trade — patching them directly risks
corrupting B-tree indexes, BLOB chains and checksums, and would silently destroy
the accounting ledger.

So the two directions needed different solutions:

**Reading** was tractable: the DBISAM format could be parsed read-only from
Python, streaming record by record so a 200 MB table never lands in RAM.

**Writing** was not. With no supported write path, the only remaining interface
was the application's own UI — but the usual automation route failed in a way
that took a while to characterize: driving it with `pywinauto`'s synthetic input
*appears* to work, yet the data-loading triggers quietly misbehave. The search
dialog answers `"Database name is missing"` and the grid comes back empty. The
approach that does work is emitting **real hardware-level input events through
the Win32 `SendInput` API**, which the application cannot distinguish from a
person typing — against an isolated second instance of the POS, behind a mutex
so automation never fights the cashier for the mouse.

Some of it is genuinely fiddly: price fields only accept the decimal separator
from the **numeric keypad** (`VK_DECIMAL`), ignoring the same character sent as
Unicode text.

That constraint — *the database is untouchable, so the UI is the API* — shapes
most of the design decisions below.

---

## Architecture

```mermaid
flowchart LR
    subgraph Store["Store PC (Windows, 24/7)"]
        DAT[("DBISAM .DAT<br/>live POS data")]
        MON["monitor.py<br/>file watcher"]
        EXT["extractors<br/>streaming reader"]
        SYNC["sync engines<br/>MD5 diff"]
        WD["backend_watchdog.py<br/>process supervisor"]
        LIS["5 listeners<br/>write-back queue"]
        UI["SendInput engine<br/>isolated POS instance"]
    end
    SUPA[("Supabase<br/>PostgreSQL")]
    APP["Mobile app<br/>El Serrucho Go"]

    DAT --> MON --> EXT --> SYNC --> SUPA
    SUPA --> LIS --> UI --> DAT
    APP <--> SUPA
    WD -.supervises.-> MON & LIS
```

### Read path — incremental mirror

Extractors pull inventory, prices, stock, invoices, customers and suppliers out
of the `.DAT` files. Each row is hashed (MD5); only rows whose hash changed are
pushed, in batches of 1,000. A file watcher triggers extraction on change, with
per-table debounce and cooldown so a burst of POS writes collapses into one sync.

Sales are converted to USD using **the exchange rate stored on each individual
invoice**, not today's rate — in a country with daily currency devaluation,
re-converting historical sales at the current rate silently rewrites the past.

### Write path — the UI *is* the API

The mobile app writes a request row to Supabase. A listener claims it, drives the
POS through the corresponding flow, then **verifies the result by reading the
database back** before reporting success.

| Listener | Responsibility |
| :--- | :--- |
| `listener_writeback.py` | Stock adjustments (as kardex documents), USD prices, costs |
| `listener_compras.py` | Goods receipts, plus creating products that don't exist yet |
| `listener_pedidos.py` | Delivery notes, pre-loaded so the register can charge in seconds |
| `listener_directorio.py` | Customer and supplier records with derived codes |
| `zelle_listener.py` | Bank payment notifications via Microsoft Graph, with anti-spoofing |

---

## Safety invariants

Automating a UI to mutate live accounting data is the risky part of this system,
so the constraints are explicit and deliberately conservative:

1. **Never write `.DAT` directly.** Every mutation goes through the POS engine so
   indexes, BLOBs and checksums stay consistent.
2. **Stock changes are documents, not updates.** Stock is adjusted by posting a
   count-adjustment document, which keeps the kardex auditable. There is no path
   that overwrites a balance.
3. **Ambiguous failures are never retried.** If a flow fails *after* the commit
   keystroke, the system cannot know whether the document was posted. Retrying
   could double a purchase or a stock delta, so the request is marked `error` for
   a human instead. Failures in clearly pre-commit stages *are* retried.
   The distinction is enforced in code, not by convention.
4. **One hand on the mouse.** A named Win32 mutex (`Local\SerruchoBotMouseLock`)
   serializes all automation. A top-most banner announces live execution and
   **F12** aborts immediately.
5. **Isolated instance.** Automation drives its own POS window, never the
   cashier's session.
6. **Time-boxed.** Writes are restricted to a configurable off-hours window.

A dry-run mode (`HYBRID_WRITE_ENABLED=0`) navigates and fills every field but
never commits, which is how flows are developed and regression-checked.

---

## Resilience

The store's network drive and internet connection are both unreliable, so the
system assumes failure rather than treating it as exceptional:

- A supervisor process restarts any listener that dies or hangs, detected via
  heartbeat files rather than liveness of the PID alone.
- The sync cache is only updated **after** the server confirms the write, so a
  connection dropped mid-batch re-sends instead of silently skipping rows.
- Health checks against the network drive run with a timeout, because a
  disconnected SMB share blocks indefinitely instead of failing.
- A hung POS instance is detected and recovered before each flow.

---

## Layout

```text
├── app.py                     # Flask API (product search, sync endpoints)
├── backend_watchdog.py        # Supervisor: keeps every process alive
├── monitor.py                 # .DAT file watcher with per-table debounce
├── config.py                  # Central config, environment-driven
│
├── actualizar_inventario.py   # Inventory + price + stock extractor
├── extraer_ventas.py          # Invoice extractor (filters voided documents)
├── sync.py                    # Incremental inventory sync (MD5 diff)
├── sync_ventas.py             # Sales sync, USD-converted per invoice
├── sync_ajustes.py            # Adjustment sync
├── rates_service.py           # BCV and Binance P2P exchange-rate scraper
│
├── hybrid_writeback/          # Write-back engine
│   ├── realinput.py           # Win32 SendInput driver (real hardware events)
│   ├── abrir_hybrid.py        # Isolated POS instance + automated login
│   ├── safety_control.py      # Mutex, abort hotkey, live banner
│   ├── flujo_*_real.py        # One choreography per operation
│   ├── listener_*.py          # One queue consumer per operation
│   └── diagnostico/           # Throwaway UI-inspection scripts
│
├── widget.pyw                 # Desktop status widget (system tray)
├── plans/                     # Design notes written before each change
└── tests/                     # pytest suite
```

---

## Running it

Requires Python 3.10+ on Windows, and a licensed HybridLite installation for the
write-back path. The read path only needs access to the `.DAT` files.

```powershell
pip install -r requirements.txt
copy .env.example .env          # then fill in your Supabase credentials

python sync.py once             # one-shot inventory sync
python sync.py force            # full resync, ignoring the hash cache
pytest                          # test suite

python backend_watchdog.py      # start the full 24/7 stack
```

Configuration is entirely environment-driven — see [.env.example](.env.example)
for every supported variable. No credentials are committed to this repository.

---

## Documentation

| Document | Contents |
| :--- | :--- |
| [ARCHITECTURE.md](docs/ARCHITECTURE.md) | Sync engine internals and data flow |
| [hybrid_writeback/README.md](hybrid_writeback/README.md) | Write-back engine, flow by flow |
| [SECURITY-RLS.md](docs/SECURITY-RLS.md) | Row-level security policies and hardening |
| [API-SYNC-GUIDE.md](docs/API-SYNC-GUIDE.md) | Local API endpoints |
| [ZELLE-LISTENER.md](docs/ZELLE-LISTENER.md) | Payment-notification listener and anti-spoofing |
| [plans/](plans/) | Design notes written before each significant change |

Code comments and internal documents are in Spanish, the working language of the
business this was built for.

---

## License

MIT — see [LICENSE](LICENSE).
