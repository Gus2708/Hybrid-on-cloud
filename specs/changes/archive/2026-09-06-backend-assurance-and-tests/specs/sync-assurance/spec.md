# Delta Spec: sync-assurance

## ADDED Requirements

### Requirement: sync-assurance/ventas-sync — Conciliación de ventas sin duplicaciones
The system MUST reconcile local CSV sales transactions against cached state and generate idempotent Supabase upsert payloads.

#### Scenario: Unchanged sales batches skipped
- GIVEN a sales cache matching current CSV records hash
- WHEN `sync_ventas` executes an incremental pass
- THEN no network write requests are dispatched and sync finishes cleanly.

#### Scenario: Changed or new sales transactions dispatched
- GIVEN new sales records present in CSV
- WHEN `sync_ventas` runs
- THEN valid batches are constructed and sent to Supabase with proper conflict resolution.

### Requirement: sync-assurance/ajustes-sync — Decodificación de transacciones de inventario
The system MUST correctly decode DBISAM timestamp values and identify local mirror transactions.

#### Scenario: Timestamp decoding from midnight milliseconds
- GIVEN a DBISAM millisecond integer (e.g. `3661000`)
- WHEN decoded via `decode_dbisam_time`
- THEN the formatted string `"01:01:01"` is returned.

#### Scenario: Cache identification of previously synced adjustments
- GIVEN an adjustment header tagged with local mirror signatures
- WHEN evaluated by the sync filtering logic
- THEN it is recognized as already mirrored to avoid cyclic re-application.

### Requirement: sync-assurance/watchdog — Supervisión de procesos y cooldown de reinicios
The system MUST track target process health and prevent rapid reinvocation loops.

#### Scenario: Dead process detection
- GIVEN a monitored PID that has terminated
- WHEN `is_alive(pid)` is evaluated
- THEN it returns `False`.

#### Scenario: Restart cooldown enforcement
- GIVEN a process that failed repeatedly within a short window
- WHEN checked for restart eligibility
- THEN backoff delay prevents aggressive immediate re-spawning.
