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
