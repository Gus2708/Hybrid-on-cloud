# Exploration: writeback-guardrails

## Request Understanding
Writeback operations frequently fail or freeze because one or more instances of HybridLiteOS have open windows or modal dialogs (e.g. employee workflows, confirmation popups, unclosed search forms, or alert dialogs) that block application interaction. The objective is to introduce guardrails and verifiers in `hybrid_writeback` so that writeback:
1. Detects open blocking windows, modal dialogs, and disabled main windows across Hybrid processes before taking input control.
2. Avoids blindly adopting blocked Hybrid instances or taking over the hardware mouse/keyboard while blocking dialogs are present.
3. Distinguishes between employee activity (deferring execution without consuming retry budgets or corrupting state) and stale/orphan dialogs.
4. Provides clear pre-flight verification before entering safety-controlled automation loops.

## Current State
- `abrir_hybrid.py` has a heuristic in step 1.5 that adopts any visible `TF_MainHybridCashMG` window without verifying whether the window is enabled (`IsWindowEnabled`), whether modal popups exist (`GetLastActivePopup`), or whether submodules are open.
- `hybrid_health.py` only checks `IsHungAppWindow` and process age; a Delphi application running a modal event loop (`ShowModal`) continues pumping Windows messages, so `SendMessageTimeoutW` returns success even though the main form is completely disabled and blocked.
- `listener_writeback.py` immediately enters `control_seguro` (acquiring the inter-process mouse mutex, displaying the full-screen topmost red banner, and attempting `BlockInput`) before verifying whether HybridLiteOS is in an interactable state.
- When an open window or modal blocks the UI, pywinauto actions fail or time out, causing writeback items to fail and burn retry attempts (`backend_intentos`) until marked as `'error'`.

## Affected Areas
| Area | Evidence | Why It Matters |
|------|----------|----------------|
| `hybrid_writeback/hybrid_health.py` | [`hybrid_writeback/hybrid_health.py:L109-125`](file:///c:/Proyect/backend%20serrucho/hybrid_writeback/hybrid_health.py#L109-L125) | Add window inspection verifiers: modal popup detection (`GetLastActivePopup`), window enabled state (`IsWindowEnabled`), and enumeration of blocking dialogs (`TMessageForm`, `#32770`, search forms). |
| `hybrid_writeback/abrir_hybrid.py` | [`hybrid_writeback/abrir_hybrid.py:L324-332`](file:///c:/Proyect/backend%20serrucho/hybrid_writeback/abrir_hybrid.py#L324-L332) | Guard `asegurar_hybrid` against adopting blocked/modal instances; ensure clean readiness checks before reporting readiness. |
| `hybrid_writeback/listener_writeback.py` | [`hybrid_writeback/listener_writeback.py:L451-471`](file:///c:/Proyect/backend%20serrucho/hybrid_writeback/listener_writeback.py#L451-L471) | Implement pre-flight guardrails before acquiring `control_seguro`: defer or back off without incrementing retry failure counts when blocked by user/modal activity. |
| `tests/test_hybrid_health.py` | [`tests/test_hybrid_health.py:L36-75`](file:///c:/Proyect/backend%20serrucho/tests/test_hybrid_health.py#L36-L75) | Unit test coverage for modal detection, disabled window detection, and readiness classification. |
| `tests/test_listener_writeback.py` | [`tests/test_listener_writeback.py:L1-50`](file:///c:/Proyect/backend%20serrucho/tests/test_listener_writeback.py#L1-L50) | Verify that writeback defers safely without burning retries when Hybrid windows are blocked. |

## Existing Tests
| Test/File | Relevance | Missing Coverage |
|-----------|-----------|------------------|
| `tests/test_hybrid_health.py` (19 tests) | Validates hung process detection and kill decisions | Lacks tests for modal popups, enabled/disabled window checks, and blocking child dialog identification. |
| `tests/test_listener_writeback.py` | Validates writeback item lifecycle and retry policies | Lacks tests simulating pre-flight blockages and non-destructive back-off. |
| `tests/test_safety_control.py` | Validates mutex acquisition and banner display | Lacks integration checks for pre-flight guardrail gating before mutex acquisition. |

## Options
| Option | Pros | Cons | Risk | Effort |
|--------|------|------|------|--------|
| **Option A: Comprehensive Pre-flight Verifiers & Non-destructive Back-off** | 1. Detects modal dialogs (`GetLastActivePopup`, `IsWindowEnabled`, Delphi dialog classes).<br>2. Verifies readiness *before* acquiring mouse mutex or showing banner.<br>3. Defers writeback cycle without burning `backend_intentos` when blocked by active user.<br>4. Re-validates window health in `abrir_hybrid` so blocked instances are never adopted blindly. | Slightly more checks before each writeback pass (~50ms Win32 API calls). | Low; standard Win32 inspection APIs with fail-safe fallbacks. | Medium |
| **Option B: Aggressive Auto-dismiss / Taskkill of Blocking Dialogs** | Forces Hybrid into a clean state by pressing ESC or closing blocking dialogs automatically. | High risk of destroying an employee's unsaved transaction or closing critical error dialogs. | High; potential data corruption or employee friction. | Medium |
| **Option C: Only Check Process Count (Single Instance Enforcement)** | Refuses to run if more than 1 HybridLiteOS.exe process exists. | Fails even when an isolated background instance is completely healthy and separated from an employee instance; does not detect dialogs within a single instance. | High; causes unnecessary writeback stalls. | Low |

## Recommendation
Implement **Option A**:
1. **Pre-flight Window Verifiers (`hybrid_health.py`)**:
   - `hay_dialogos_bloqueantes(pid)`: Inspects top-level windows for the target process using `GetLastActivePopup`, `IsWindowEnabled`, and known blocking classes (`TMessageForm`, `#32770`, `TForm_BusquedaConfDb`, etc.).
   - `estado_ventanas_hybrid()`: Summarizes the global status (clean, blocked_by_modal, employee_active, no_instances).
2. **Guardrails in Instance Management (`abrir_hybrid.py`)**:
   - In step 1.5, never adopt `MAIN` if `hay_dialogos_bloqueantes(pid)` is true or if `IsWindowEnabled` is false.
   - When attempting isolation or launching, ensure leftover blocking modal popups are surfaced with structured diagnostic messages.
3. **Guardrails in Writeback Listener (`listener_writeback.py`)**:
   - Pre-flight check prior to `control_seguro`: if Hybrid is blocked by active modal windows, log a concise warning, skip the pass without incrementing `backend_intentos`, and let the next polling cycle re-check.

## Risks
- **False positives on temporary transitions**: When Hybrid transitions between forms during normal automation, `IsWindowEnabled` might briefly flicker. *Mitigation:* Apply a short grace period/retry (e.g. 1-2 seconds) before classifying as blocked.
- **Permission to inspect windows**: Standard Win32 `GetLastActivePopup` and `IsWindowEnabled` require normal user tokens (same desktop), which matches the existing writeback environment.

## Open Questions
- None. The Win32 inspection pattern aligns with the existing architecture in `hybrid_health.py` and `abrir_hybrid.py`.

## Ready For Planning
Yes. The problem, seams, test strategy, and solution boundaries are fully mapped.
