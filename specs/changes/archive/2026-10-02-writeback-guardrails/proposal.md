# Proposal: writeback-guardrails

## Intent
Writeback automation (stock adjustments, price updates, and inventory sheet modifications) frequently fails, freezes, or corrupts workflows when an instance of HybridLiteOS has blocking windows or modal dialogs open (e.g. an employee active in a submodule, an unclosed confirmation dialog, an alert popup, or an unclosed search grid). Currently, the system either blindly adopts an existing disabled window or takes control of hardware mouse and keyboard via `control_seguro`, only to crash seconds later and burn through retry attempts (`backend_intentos`).

This proposal introduces guardrails and pre-flight verifiers into `hybrid_writeback` to:
1. Detect active modal dialogs, disabled main windows, and blocking popup forms before initiating UI automation.
2. Prevent `abrir_hybrid.py` from adopting any existing Hybrid instance that is in a blocked or disabled state.
3. Add a non-destructive pre-flight guardrail in `listener_writeback.py` that defers execution without burning retry attempts or locking the physical screen when Hybrid is occupied or blocked.

## Scope

### In Scope
- Implement Win32 window state inspection in `hybrid_writeback/hybrid_health.py`:
  - Verify if windows are enabled via `IsWindowEnabled`.
  - Detect active modal popups via `GetLastActivePopup`.
  - Identify known blocking Delphi modal classes (`TMessageForm`, `#32770`, `TForm_BusquedaConfDb`, and active transaction forms).
- Update `hybrid_writeback/abrir_hybrid.py` to guard step 1.5: do not adopt an existing instance if it contains blocking windows or disabled roots.
- Update `hybrid_writeback/listener_writeback.py` with a pre-flight guardrail: check window health before acquiring `control_seguro`; defer processing cleanly when blocked by user/modal activity without consuming `backend_intentos`.
- Add comprehensive unit tests in `tests/test_hybrid_health.py` and `tests/test_listener_writeback.py`.

### Out of Scope
- Forcefully killing or closing employee transactions with unsaved work.
- Modifying database schemas in DBISAM or remote Supabase tables.
- Rewriting pywinauto automation internals for unaffected submodules.

## Capabilities

### Modified Capabilities
- `writeback-assurance`: Add requirements for pre-flight modal and blocking window verification before acquiring physical input control or adopting existing instances.

## Approach
1. **Window Inspection Verifiers (`hybrid_health.py`)**:
   - Introduce `ventanas_bloqueantes(pids=None)`: enumerates top-level windows for Hybrid processes and flags any window where `IsWindowEnabled(hwnd) == False`, `GetLastActivePopup(hwnd) != hwnd`, or the class belongs to a known modal dialog (`TMessageForm`, `#32770`, `TForm_BusquedaConfDb`).
   - Introduce `verificar_hybrid_listo()`: returns a structured tuple `(listo: bool, motivo: str)` checking if Hybrid is ready for automated writeback or currently blocked.
2. **Safe Adoption Guard (`abrir_hybrid.py`)**:
   - In `asegurar_hybrid()`, before adopting an existing `MAIN` window (step 1.5), verify that the instance has no blocking windows and is enabled. If blocked, do not adopt; attempt clean isolated launch or report blocked state.
3. **Pre-flight Writeback Guardrail (`listener_writeback.py`)**:
   - In `procesar_pendientes()`, execute `verificar_hybrid_listo()` before calling `with control_seguro()`.
   - If blocked by modal dialogs or user activity, log an informative warning, skip the current execution cycle, and keep items in `pendiente` status without incrementing `backend_intentos`.
4. **Automated Verification**:
   - Extend `tests/test_hybrid_health.py` with mock scenarios for modal popups, disabled parent forms, and Delphi dialog classes.
   - Extend `tests/test_listener_writeback.py` to assert that pre-flight blockage defers execution non-destructively.

## Affected Areas
| Area | Impact | Description |
|------|--------|-------------|
| `hybrid_writeback/hybrid_health.py` | Modify | Add `ventanas_bloqueantes()` and `verificar_hybrid_listo()`. |
| `hybrid_writeback/abrir_hybrid.py` | Modify | Guard instance adoption against blocked/disabled states. |
| `hybrid_writeback/listener_writeback.py` | Modify | Add pre-flight readiness verification before taking screen control. |
| `tests/test_hybrid_health.py` | Modify | Unit tests for modal dialog detection and window readiness checks. |
| `tests/test_listener_writeback.py` | Modify | Unit tests verifying non-destructive back-off when blocked. |

## Risks
| Risk | Likelihood | Mitigation |
|------|------------|------------|
| False positive blockage during normal form opening | Low | Add brief stabilization retry (1-2s) before declaring an instance blocked. |
| Non-responsive process during inspection | Low | Use Win32 timeouts (`SendMessageTimeoutW`, `IsHungAppWindow`) to avoid hanging the verifier. |

## Rollback Plan
Discard git modifications in `hybrid_writeback/` and `tests/`. The existing code remains intact without database or filesystem migrations.

## Success Criteria
- [ ] `sdd check --change writeback-guardrails` passes.
- [ ] Window verifiers accurately detect modal popups (`GetLastActivePopup`), disabled windows (`IsWindowEnabled == False`), and Delphi dialog classes.
- [ ] `abrir_hybrid.py` rejects adopting blocked Hybrid instances.
- [ ] `listener_writeback.py` defers execution cleanly without incrementing `backend_intentos` when blocked.
- [ ] Full test suite passes without regressions.

## Open Questions
- None.
