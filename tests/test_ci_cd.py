"""
Pruebas automatizadas de validación estructural y sintáctica para canalizaciones CI/CD.
Asegura que los workflows de GitHub Actions cumplan con el contrato de calidad,
triggers, runner Windows y pasos de pruebas/empaquetado.
"""
import os
import yaml
import pytest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKFLOWS_DIR = os.path.join(REPO_ROOT, ".github", "workflows")


class TestContinuousIntegrationWorkflow:
    """Valida la configuración del pipeline de CI (.github/workflows/ci.yml)."""

    def test_ci_workflow_exists_and_is_valid_yaml(self):
        ci_path = os.path.join(WORKFLOWS_DIR, "ci.yml")
        assert os.path.exists(ci_path), "El archivo .github/workflows/ci.yml debe existir"
        with open(ci_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        assert isinstance(data, dict), "ci.yml debe ser un documento YAML válido"
        assert "name" in data, "ci.yml debe tener un campo name"
        assert "jobs" in data, "ci.yml debe definir al menos un job"

    def test_ci_workflow_triggers(self):
        ci_path = os.path.join(WORKFLOWS_DIR, "ci.yml")
        with open(ci_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        
        triggers = data.get("on") or data.get(True)
        assert triggers, "ci.yml debe definir disparadores (on)"
        
        # Verificar triggers de push y pull_request a main
        assert "push" in triggers, "Debe activarse en push"
        assert "pull_request" in triggers, "Debe activarse en pull_request"
        assert "workflow_dispatch" in triggers, "Debe admitir ejecución manual workflow_dispatch"
        
        push_branches = triggers["push"].get("branches", [])
        pr_branches = triggers["pull_request"].get("branches", [])
        assert "main" in push_branches, "Push debe vigilar la rama main"
        assert "main" in pr_branches, "Pull Request debe vigilar la rama main"

    def test_ci_workflow_job_configuration(self):
        ci_path = os.path.join(WORKFLOWS_DIR, "ci.yml")
        with open(ci_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        
        jobs = data.get("jobs", {})
        assert len(jobs) >= 1, "Debe tener al menos un job de prueba"
        
        # Obtener el job principal (test o ci)
        job_key = "test" if "test" in jobs else list(jobs.keys())[0]
        job = jobs[job_key]
        
        assert job.get("runs-on") == "windows-latest", "El job de CI debe correr en windows-latest"
        
        steps = job.get("steps", [])
        step_names = [s.get("name", "") for s in steps]
        step_runs = [s.get("run", "") for s in steps if "run" in s]
        all_run_text = "\n".join(step_runs)
        
        # Validar setup-python 3.14 con cache
        uses_setup = [s for s in steps if "setup-python" in s.get("uses", "")]
        assert uses_setup, "Debe usar actions/setup-python"
        with_cfg = uses_setup[0].get("with", {})
        assert "3.14" in str(with_cfg.get("python-version", "")), "Python version debe ser 3.14"
        assert with_cfg.get("cache") == "pip", "Debe habilitar caché de pip"
        
        # Validar ejecución de ruff
        assert any("ruff check" in r for r in step_runs), "Debe ejecutar python -m ruff check ."
        
        # Validar ejecución de pytest con cobertura
        assert any("pytest" in r for r in step_runs), "Debe ejecutar python -m pytest"
        assert any("coverage.xml" in r or "--cov" in r for r in step_runs), "Debe medir cobertura"
        
        # Validar artefacto de cobertura
        uses_upload = [s for s in steps if "upload-artifact" in s.get("uses", "")]
        assert uses_upload, "Debe subir el reporte de cobertura con actions/upload-artifact"


class TestContinuousDeliveryWorkflow:
    """Valida la configuración del pipeline de Release (.github/workflows/release.yml)."""

    def test_release_workflow_exists_and_is_valid_yaml(self):
        rel_path = os.path.join(WORKFLOWS_DIR, "release.yml")
        assert os.path.exists(rel_path), "El archivo .github/workflows/release.yml debe existir"
        with open(rel_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        assert isinstance(data, dict), "release.yml debe ser un documento YAML válido"
        assert "name" in data, "release.yml debe tener un campo name"
        assert "jobs" in data, "release.yml debe definir al menos un job"

    def test_release_workflow_triggers_and_permissions(self):
        rel_path = os.path.join(WORKFLOWS_DIR, "release.yml")
        with open(rel_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        
        triggers = data.get("on") or data.get(True)
        assert triggers, "release.yml debe definir disparadores (on)"
        assert "workflow_dispatch" in triggers, "Debe admitir ejecución manual workflow_dispatch"
        assert "push" in triggers, "Debe activarse en push"
        
        push_tags = triggers["push"].get("tags", [])
        assert any("v*" in tag for tag in push_tags), "Debe dispararse con tags v*"
        
        # Validar permisos de release
        perms = data.get("permissions", {})
        if not perms:
            # Podría estar a nivel de job
            jobs = data.get("jobs", {})
            first_job = list(jobs.values())[0]
            perms = first_job.get("permissions", {})
        assert perms.get("contents") == "write", "Debe tener permisos contents: write para crear releases"

    def test_release_workflow_build_and_packaging_steps(self):
        rel_path = os.path.join(WORKFLOWS_DIR, "release.yml")
        with open(rel_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        
        jobs = data.get("jobs", {})
        job_key = list(jobs.keys())[0]
        job = jobs[job_key]
        
        assert job.get("runs-on") == "windows-latest", "El job de release debe correr en windows-latest"
        
        steps = job.get("steps", [])
        step_runs = [s.get("run", "") for s in steps if "run" in s]
        all_run_text = "\n".join(step_runs)
        
        # Inno Setup instalación
        assert "innosetup" in all_run_text.lower(), "Debe instalar o configurar Inno Setup"
        
        # Compilación Nuitka
        assert "build_nuitka" in all_run_text or "nuitka" in all_run_text.lower(), "Debe ejecutar compilación Nuitka"
        
        # Compilación de installer
        assert "iscc" in all_run_text.lower() or "installer.iss" in all_run_text, "Debe compilar installer.iss con ISCC"
        
        # Publicación con softprops/action-gh-release
        uses_release = [s for s in steps if "action-gh-release" in s.get("uses", "")]
        assert uses_release, "Debe publicar release con softprops/action-gh-release"
        with_cfg = uses_release[0].get("with", {})
        files = with_cfg.get("files", "")
        assert "Instalador_HybridOnCloud" in str(files) or "installer/" in str(files), "Debe adjuntar el instalador"


class TestBuildNuitkaSanity:
    """Valida que el script de build_nuitka no dependa de prompts interactivos."""

    def test_build_script_has_unattended_flags(self):
        script_path = os.path.join(REPO_ROOT, "scripts", "build_nuitka.py")
        with open(script_path, "r", encoding="utf-8") as f:
            content = f.read()
        assert "--assume-yes-for-downloads" in content, "Debe incluir --assume-yes-for-downloads para modo desatendido"
        assert "os.path.dirname" in content, "Debe calcular rutas dinámicamente"
