# Design: writeback-guardrails

## Technical Approach
Implement Win32 inspection verifiers and operational guardrails to prevent writeback automation from executing against blocked, modal-disabled, or operator-occupied HybridLiteOS instances:

1. **Win32 Window Inspection (`hybrid_writeback/hybrid_health.py`)**:
   - Query visible top-level windows belonging to `HybridLiteOS.exe` processes.
   - Inspect window modal status using native Win32 APIs:
     - `_user32.IsWindowEnabled(hwnd)`: Returns `False` when a window has been disabled by a modal dialog (`ShowModal` in Delphi/VCL).
     - `_user32.GetLastActivePopup(hwnd)`: Returns the HWND of the active pop-up window owned by `hwnd`. If `popup != hwnd` and `IsWindowVisible(popup)`, an unhandled modal or message dialog is active.
   - Detect known Delphi modal and blocking classes:
     - `TMessageForm`: Modal alert/confirmation dialog.
     - `#32770`: Native Windows modal dialog / file prompt.
     - `TForm_BusquedaConfDb`: Search popups left open.
     - Active transaction modules (`TF_FacturacionMain`, `TF_ComprasMain`, `TF_PedidosMain`, `TF_AjustesMain`) when open by an employee.
   - Expose:
     - `ventanas_bloqueantes(pids=None) -> list[dict]`: Returns a structured list of blocking windows with HWND, PID, class name, window text, and reason.
     - `verificar_hybrid_listo(target_pid=None) -> tuple[bool, str, list[dict]]`: Returns `(listo, motivo, bloqueos)`.

2. **Safe Adoption Guard (`hybrid_writeback/abrir_hybrid.py`)**:
   - In `asegurar_hybrid()` step 1.5, before adopting an existing `MAIN` window (`TF_MainHybridCashMG`), verify that the instance is fully enabled and has no blocking windows (`verificar_hybrid_listo(pid=pid)`).
   - If blocked or disabled, do not adopt the instance; attempt a clean isolated launch or surface the blockage clearly.

3. **Pre-flight Writeback Guardrail (`hybrid_writeback/listener_writeback.py`)**:
   - In `procesar_pendientes()`, perform a pre-flight readiness check before entering `with control_seguro()`.
   - If Hybrid has active blocking windows or is being used with modal dialogs:
     - Log an informative warning with the exact blocking window details.
     - Do NOT acquire the mouse mutex or display the red locking banner.
     - Do NOT mark items as `error` and do NOT increment `backend_intentos`.
     - Defer the entire batch cleanly to the next polling cycle.

## Architecture Decisions
| Decision | Choice | Alternatives | Rationale |
|----------|--------|--------------|-----------|
| Win32 Modal Detection | `GetLastActivePopup` + `IsWindowEnabled` | Pywinauto tree traversal | Win32 API calls execute in microseconds and do not hang if a window is in a modal message loop; pywinauto tree queries can block. |
| Deferral Policy | Non-destructive back-off (no retry burn) | Mark as retryable failure with `backend_intentos += 1` | User activity or modal popups are normal operational states, not item defects; burning retry attempts would cause items to permanently fail into `error` after 3 cycles. |
| Mutual Exclusion | Pre-flight check *before* `control_seguro` | Check inside `control_seguro` | Prevents seizing mouse/keyboard and flashing the full-screen red banner over an employee's screen when writeback cannot proceed anyway. |
| Delphi Form Identification | Class matching | Title substring matching | Delphi class names (`TMessageForm`, `TForm_BusquedaConfDb`) are stable across localizations and builds, whereas window titles change with language or record content. |

## Architecture Design

### Project Placement
```text
hybrid_writeback/
├── hybrid_health.py
│   └── ventanas_bloqueantes()
        [new] Enumerate windows and identify modal, disabled, or blocking states.
├── abrir_hybrid.py
│   └── asegurar_hybrid()
        [modify] Enforce readiness verifier before adopting existing MAIN windows.
└── listener_writeback.py
    └── procesar_pendientes()
        [modify] Pre-flight check prior to control_seguro; defers non-destructively when blocked.
tests/
├── test_hybrid_health.py
│   └── test_ventanas_bloqueantes()
        [new] Unit tests for modal popups, disabled forms, and readiness evaluation.
└── test_listener_writeback.py
    └── test_preflight_bloqueado_pospone()
        [new] Unit test verifying pre-flight back-off without state mutation.
```

### Data Flow
```text
[listener_writeback.procesar_pendientes(items)]
       │
       ▼
[hybrid_health.verificar_hybrid_listo()]
       │
       ├─► [Blocked: modal open / disabled / employee active]
       │         │
       │         ▼
       │   [Log warning & return] (No mouse lock, no banner, items remain 'pendiente', 0 retries burned)
       │
       └─► [Ready / Clean]
                 │
                 ▼
           [with control_seguro()]
                 │
                 ▼
           [Execute writeback (flujo_stock / flujo_precio / flujo_ficha)]
```

### Behavior Flow
1. **Verificación Previa**: Al llegar items pendientes en `listener_writeback`, el proceso consulta `verificar_hybrid_listo()` antes de solicitar el mutex de mouse o mostrar el banner.
2. **Postergación Segura**: Si se detecta un diálogo modal (`TMessageForm`, ventana deshabilitada o popup activo), se registra la advertencia y se finaliza la pasada sin tocar el estado ni los reintentos de los items.
3. **Ejecución Protegida**: Si la instancia está libre y lista, se entra a `control_seguro` y se asegura la ventana sin riesgo de colisión modal.

### Interfaces / Contracts
- `hybrid_health.ventanas_bloqueantes(pids=None) -> list[dict]`
- `hybrid_health.verificar_hybrid_listo(target_pid=None) -> tuple[bool, str, list[dict]]`
- Retorno booleano y lista de diccionarios con claves `hwnd`, `pid`, `class_name`, `title`, `motivo`.

## Testing Strategy
| Layer | What | Approach |
|-------|------|----------|
| Win32 Unit Tests | `hybrid_health.ventanas_bloqueantes` | Mock `win32gui`, `_user32.IsWindowEnabled`, and `_user32.GetLastActivePopup` to verify detection of disabled parents and popup dialogs. |
| Adoption Guard Tests | `abrir_hybrid.asegurar_hybrid` | Mock existing `MAIN` window with blocked state to verify rejection of blocked instances. |
| Listener Guardrail Tests | `listener_writeback.procesar_pendientes` | Mock blocked pre-flight check and assert that `control_seguro` is never entered and items remain untouched. |
| Regression Test Suite | Full suite (199 tests) | Run `pytest` to guarantee zero regressions across sync, RPA, and schema tests. |

## Migration / Rollout
Direct drop-in enhancement to `hybrid_writeback`. Backward-compatible with existing CLI invocations and watchdog processes.

## Technical Risks
| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Ventana modal transitoria durante apertura | Baja | La verificación pre-vuelo ocurre antes de arrancar la automatización; las transiciones internas son gestionadas por los flujos existentes. |
| Procesos sin permisos para inspección de ventanas | Baja | El listener corre en la misma sesión interactiva de escritorio Windows que HybridLiteOS. |

## Open Questions
- [ ] Ninguna; el diseño cubre completamente la detección de ventanas bloqueantes en Win32 y su integración no destructiva en el flujo de writeback.
