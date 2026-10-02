# Delta Spec: writeback-assurance

## ADDED Requirements

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
