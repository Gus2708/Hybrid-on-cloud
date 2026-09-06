# Delta Spec: continuous-delivery

## ADDED Requirements

### Requirement: continuous-delivery/release-trigger — GitHub Actions Release Triggering
The system MUST trigger the Continuous Delivery workflow upon pushing a semantic version tag or when manually triggered by a maintainer.

#### Scenario: Version tag pushed
- GIVEN a git tag matching the pattern `v*.*.*` or `v*` pushed to the repository
- WHEN GitHub Actions processes the tag event
- THEN the release workflow MUST trigger automatically on `windows-latest`.

#### Scenario: Manual release trigger with version input
- GIVEN a maintainer initiating a release dispatch via GitHub Actions
- WHEN the user executes the workflow dispatch
- THEN the release workflow MUST execute without requiring an immediate git tag event.

### Requirement: continuous-delivery/installer-packaging — Nuitka Compilation and Inno Setup Packaging
The system MUST compile the backend launcher into a standalone binary using Nuitka and compile an Inno Setup installer executable attached to a GitHub Release.

#### Scenario: Clean automated build and GitHub Release publication
- GIVEN the release workflow executing on `windows-latest` with Inno Setup installed
- WHEN Nuitka compiles `widget.exe` and Inno Setup compiles `Instalador_HybridOnCloud.exe`
- THEN the workflow MUST create a GitHub Release and attach the installer binary as a downloadable release asset with automatic release notes.

#### Scenario: Build failure prevents invalid release publication
- GIVEN an error occurring during Nuitka compilation or Inno Setup script execution
- WHEN the compiler process exits with an error code
- THEN the workflow MUST terminate immediately with failure and MUST NOT publish a corrupted or incomplete GitHub Release.
