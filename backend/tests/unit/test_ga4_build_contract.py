"""Las imagenes nuevas de frontend compilan con GA4 apagado."""

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "build-images.yml"
COMPOSE = REPO_ROOT / "docker-compose.yml"
DOCKERFILE = REPO_ROOT / "frontend" / "Dockerfile"
GA4 = "VITE_GA4_MEASUREMENT_ID"
PRESERVED_BUILD_ARGS = (
    "VITE_SENTRY_DSN",
    "VITE_SUPPORT_WHATSAPP",
    "VITE_CONTACT_EMAIL",
    "VITE_LEGAL_RESPONSABLES",
)


def test_ci_y_compose_no_pasan_ga4_como_build_arg() -> None:
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    job = workflow["jobs"]["build"]
    frontend = next(
        item
        for item in job["strategy"]["matrix"]["include"]
        if item["service"] == "frontend"
    )
    assert frontend["context"] == "./frontend"

    steps = job["steps"]
    build = next(
        step
        for step in steps
        if str(step.get("uses", "")).startswith("docker/build-push-action@")
    )
    assert build["with"]["context"] == "${{ matrix.context }}"
    build_args = [arg.strip() for arg in build["with"]["build-args"].splitlines()]
    assert not any(arg.startswith(f"{GA4}=") for arg in build_args)
    for name in PRESERVED_BUILD_ARGS:
        assert any(arg.startswith(f"{name}=") for arg in build_args)

    compose = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
    frontend_build = compose["services"]["frontend"]["build"]
    assert frontend_build["context"] == "./frontend"
    assert frontend_build["dockerfile"] == "Dockerfile"
    frontend_args = frontend_build["args"]
    assert GA4 not in frontend_args
    for name in PRESERVED_BUILD_ARGS:
        assert name in frontend_args


def test_dockerfile_fuerza_ga4_vacio_y_publica_la_csp_generada_en_la_imagen() -> None:
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")
    disabled_environment = f"ENV {GA4}=\n"
    assert disabled_environment in dockerfile.splitlines(keepends=True)
    environment = dockerfile.index(disabled_environment)
    assert f"ARG {GA4}=" not in dockerfile
    for name in PRESERVED_BUILD_ARGS:
        assert f"ARG {name}=" in dockerfile
        assert f"ENV {name}=${{{name}}}" in dockerfile
    build = dockerfile.index("RUN npm run build")
    generate_csp = dockerfile.index(
        "RUN node configure-analytics-csp.mjs security-headers.conf "
        "/app/security-headers.generated.conf"
    )
    csp_destination = "/etc/nginx/security-headers.conf"
    copy_line = (
        f"COPY --from=build /app/security-headers.generated.conf {csp_destination}"
    )
    copy_csp = dockerfile.index(copy_line)
    lines = dockerfile.splitlines()
    copy_line_index = lines.index(copy_line)
    final_stage = max(
        index for index, line in enumerate(lines) if line.startswith("FROM ")
    )
    writes_to_csp = [
        line.strip()
        for line in lines
        if line.startswith(("COPY ", "ADD ")) and line.split()[-1] == csp_destination
    ]

    assert environment < build < generate_csp < copy_csp
    assert dockerfile.count(csp_destination) == 1
    assert writes_to_csp == [copy_line]
    assert copy_line_index > final_stage
