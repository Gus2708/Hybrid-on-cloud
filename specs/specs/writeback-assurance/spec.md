# Spec: writeback-assurance

## Domain Overview
Domain behavior synchronized from change artifacts.

## Requirements

### Requirement: writeback-assurance/mock-harness — Aislamiento headless para automatización
The system MUST provide an automated testing fixture that mocks Win32 hardware inputs, window handles, and database files so that writeback logic runs deterministically in headless environments.

#### Scenario: Intercepting hardware input calls
- GIVEN a test running under the `mock_hybrid` harness
- WHEN writeback code triggers cursor movement or keyboard entry via `realinput`
- THEN the hardware calls are intercepted without moving the physical mouse or keyboard, recording call arguments for assertion.

### Requirement: writeback-assurance/state-machine — Determinismo en la máquina de estados de writeback
The system MUST handle retryable versus fatal non-retryable errors conservatively in `listener_writeback` to prevent duplicate inventory adjustments.

#### Scenario: Pre-commit failure triggers retry
- GIVEN an item being processed that fails during a pre-commit stage (e.g., `abrir_hybrid` or `escritura`)
- WHEN the failure occurs and attempts are below `MAX_INTENTOS`
- THEN the record remains in a retryable state and `backend_intentos` is incremented.

#### Scenario: Ambiguous or post-commit failure marks immediate error
- GIVEN an item undergoing adjustment that encounters an unhandled exception or post-commit timeout
- WHEN the state is evaluated
- THEN the record is transitioned immediately to `error` status without retrying, preventing duplicate stock application.

### Requirement: writeback-assurance/safety-control — Exclusión mutua y aborto
The system MUST enforce process-level mutual exclusion and emergency abort handling during physical bot control.

#### Scenario: Mutex acquisition between competing bots
- GIVEN one bot process holding the Win32 named mutex
- WHEN a second bot attempts to enter `control_seguro`
- THEN the second bot waits or gracefully backs off without concurrent cursor conflict.

#### Scenario: Emergency abort flag
- GIVEN an active automation block inside `control_seguro`
- WHEN the abort flag is signaled (simulating F12)
- THEN `fue_abortado()` returns `True` and subsequent automation actions abort safely.

### Requirement: writeback-assurance/window-guardrails — Pre-flight modal and blocking window verification
The system MUST inspect HybridLiteOS top-level windows for modal dialogs, disabled windows, and active popups before any UI automation begins.

#### Scenario: Detecting modal popups and disabled parent windows
- GIVEN a running HybridLiteOS process that has an active modal popup (such as `TMessageForm`, `#32770`, or `TForm_BusquedaConfDb`)
- WHEN `ventanas_bloqueantes()` or `verificar_hybrid_listo()` is called
- THEN the system MUST identify the window as blocked, returning the blocking HWND and class name, and flag `listo=False`.

#### Scenario: Clean state with no blocking windows
- GIVEN a running HybridLiteOS instance with only its main window enabled and no active popups
- WHEN `verificar_hybrid_listo()` is called
- THEN the system MUST return `listo=True` with no blocking windows reported.

### Requirement: writeback-assurance/safe-adoption — Guard against adopting blocked or disabled Hybrid instances
The system MUST NOT adopt an existing HybridLiteOS instance if that instance has open blocking dialogs or a disabled main window.

#### Scenario: Existing instance is blocked by a modal dialog
- GIVEN an existing `TF_MainHybridCashMG` window whose parent is disabled or has an active popup
- WHEN `asegurar_hybrid()` runs
- THEN the system MUST reject adopting that instance, preventing automation from executing on a blocked form.

### Requirement: writeback-assurance/non-destructive-deferral — Non-destructive deferral when Hybrid is occupied
The system MUST defer writeback processing without incrementing failure retry counters (`backend_intentos`) or displaying the intrusive locking banner when HybridLiteOS is blocked by user activity or modal windows.

#### Scenario: Writeback cycle runs while operator is working
- GIVEN pending items in `ordenes_cambio_items` and HybridLiteOS is detected to have active modal dialogs or disabled main windows
- WHEN `listener_writeback.procesar_pendientes()` executes its pre-flight check
- THEN the system MUST NOT acquire `control_seguro` or mouse mutex, MUST NOT mark items as `error`, MUST NOT increment `backend_intentos`, and MUST defer processing to the next poll cycle.
