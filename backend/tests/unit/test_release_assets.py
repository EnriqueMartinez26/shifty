"""Filesystem contract for immutable, host-backed frontend asset retention."""

from __future__ import annotations

import hashlib
import os
import subprocess
import time
from pathlib import Path

import pytest

from tests.unit.host_falso import BASH, REPO_ROOT


HELPER = REPO_ROOT / "scripts" / "release-assets.sh"
AGE_14_DAYS = 14 * 24 * 60 * 60


def _image_id(release: str) -> str:
    return "sha256:" + hashlib.sha256(release.encode()).hexdigest()


def _tree(root: Path, release: str, *, shared: str = "stable") -> Path:
    assets = root / release
    assets.mkdir(parents=True)
    (assets / f"chunk-{release}.js").write_text(
        f"window.release = '{release}';\n", encoding="utf-8"
    )
    (assets / "shared.js").write_text(shared + "\n", encoding="utf-8")
    (assets / "fonts").mkdir()
    (assets / "fonts" / f"font-{release}.woff2").write_bytes(release.encode())
    return assets


def _helper(
    tmp_path: Path, *args: str, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    if BASH is None:
        pytest.skip("Git Bash or bash is required")
    checkout = tmp_path / "checkout"
    checkout.mkdir(exist_ok=True)
    return subprocess.run(
        [BASH, str(HELPER), *args],
        cwd=checkout,
        env={**os.environ, "SHIFTY_DIR": checkout.as_posix(), **(env or {})},
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def _import(tmp_path: Path, store: Path, source: Path, release: str) -> None:
    result = _helper(
        tmp_path,
        "import",
        store.as_posix(),
        release,
        _image_id(release),
        source.as_posix(),
    )
    assert result.returncode == 0, result.stderr


def _set_import_time(manifest: Path, timestamp: int) -> None:
    manifest.chmod(0o644)
    lines = manifest.read_text(encoding="utf-8").splitlines()
    lines[3] = f"imported_at={timestamp}"
    manifest.write_bytes(("\n".join(lines) + "\n").encode())
    manifest.chmod(0o444)


def test_A_B_C_assets_and_manifests_coexist_and_are_idempotent(tmp_path: Path) -> None:
    fixtures = tmp_path / "fixtures"
    store = tmp_path / "host-assets"
    trees = [_tree(fixtures, release) for release in ("A", "B", "C")]

    for release, source in zip(("A", "B", "C"), trees, strict=True):
        _import(tmp_path, store, source, release)
        verified = _helper(
            tmp_path, "verify", store.as_posix(), release, _image_id(release)
        )
        assert verified.returncode == 0, verified.stderr

    files = store / "assets"
    if os.name != "nt":
        assert files.stat().st_mode & 0o777 == 0o755
        assert (store / ".manifests").stat().st_mode & 0o777 == 0o700
    assert (files / "chunk-A.js").is_file()
    assert (files / "chunk-B.js").is_file()
    assert (files / "chunk-C.js").is_file()
    assert (files / "shared.js").read_text(encoding="utf-8") == "stable\n"
    manifest_before = (store / ".manifests" / "B.manifest").read_bytes()
    _import(tmp_path, store, trees[1], "B")
    assert (store / ".manifests" / "B.manifest").read_bytes() == manifest_before


def test_prepare_keeps_private_store_root_and_limits_public_directory_permissions(
    tmp_path: Path,
) -> None:
    if os.name == "nt":
        pytest.skip("Windows NTFS does not expose POSIX directory modes")
    store = tmp_path / "private-store"
    store.mkdir(mode=0o700)
    store.chmod(0o700)

    result = _helper(tmp_path, "prepare", store.as_posix())

    assert result.returncode == 0, result.stderr
    assert store.stat().st_mode & 0o777 == 0o700
    assert (store / "assets").stat().st_mode & 0o777 == 0o755
    assert (store / ".manifests").stat().st_mode & 0o777 == 0o700
    assert (store / ".staging").stat().st_mode & 0o777 == 0o700


def test_conflicting_filename_fails_without_clobbering_file_or_manifest(
    tmp_path: Path,
) -> None:
    fixtures = tmp_path / "fixtures"
    store = tmp_path / "host-assets"
    source_a = _tree(fixtures, "A", shared="shared from A")
    source_b = _tree(fixtures, "B", shared="different bytes from B")
    _import(tmp_path, store, source_a, "A")
    original = (store / "assets" / "shared.js").read_bytes()
    manifest = (store / ".manifests" / "A.manifest").read_bytes()

    result = _helper(
        tmp_path,
        "import",
        store.as_posix(),
        "B",
        _image_id("B"),
        source_b.as_posix(),
    )

    assert result.returncode != 0
    assert "colision" in result.stderr
    assert (store / "assets" / "shared.js").read_bytes() == original
    assert (store / ".manifests" / "A.manifest").read_bytes() == manifest
    assert not (store / ".manifests" / "B.manifest").exists()


def test_failed_import_removes_only_files_linked_by_that_attempt(
    tmp_path: Path,
) -> None:
    fixtures = tmp_path / "fixtures"
    store = tmp_path / "host-assets"
    source_a = _tree(fixtures, "A", shared="shared bytes")
    source_b = _tree(fixtures, "B", shared="shared bytes")
    _import(tmp_path, store, source_a, "A")
    manifest_a = (store / ".manifests" / "A.manifest").read_bytes()
    hook = tmp_path / "fail-second-link.sh"
    hook.write_text(
        """__asset_link_calls=0
ln() {
  __asset_link_calls=$((__asset_link_calls + 1))
  if [ "$__asset_link_calls" -eq 2 ]; then
    printf 'injected link failure\\n' >&2
    return 73
  fi
  command ln "$@"
}
""",
        encoding="utf-8",
    )

    result = _helper(
        tmp_path,
        "import",
        store.as_posix(),
        "B",
        _image_id("B"),
        source_b.as_posix(),
        env={"BASH_ENV": hook.as_posix()},
    )

    assert result.returncode != 0
    assert "no pude publicar asset" in result.stderr
    assert (store / ".manifests" / "A.manifest").read_bytes() == manifest_a
    assert not (store / ".manifests" / "B.manifest").exists()
    assert (store / "assets" / "shared.js").read_text(
        encoding="utf-8"
    ) == "shared bytes\n"
    assert (store / "assets" / "chunk-A.js").is_file()
    assert not (store / "assets" / "chunk-B.js").exists()
    assert not (store / "assets" / "fonts" / "font-B.woff2").exists()
    assert not list((store / ".staging").iterdir())


def test_tampered_asset_fails_manifest_verification(tmp_path: Path) -> None:
    store = tmp_path / "host-assets"
    source = _tree(tmp_path / "fixtures", "A")
    _import(tmp_path, store, source, "A")
    target = store / "assets" / "chunk-A.js"
    target.chmod(0o644)
    target.write_text("modified\n", encoding="utf-8")
    target.chmod(0o444)

    result = _helper(tmp_path, "verify", store.as_posix(), "A", _image_id("A"))

    assert result.returncode != 0
    assert "hash distinto" in result.stderr


def test_writable_manifest_is_rejected(tmp_path: Path) -> None:
    store = tmp_path / "host-assets"
    source = _tree(tmp_path / "fixtures", "A")
    _import(tmp_path, store, source, "A")
    manifest = store / ".manifests" / "A.manifest"
    manifest.chmod(0o644)

    result = _helper(tmp_path, "verify", store.as_posix(), "A", _image_id("A"))

    assert result.returncode != 0
    assert "manifest modificable" in result.stderr


def test_rejects_symlink_before_publishing_anything(tmp_path: Path) -> None:
    if os.name == "nt":
        pytest.skip("Windows symlink creation requires extra privileges")
    store = tmp_path / "host-assets"
    source = _tree(tmp_path / "fixtures", "A")
    outside = tmp_path / "outside.js"
    outside.write_text("outside\n", encoding="utf-8")
    (source / "escape.js").symlink_to(outside)

    result = _helper(
        tmp_path,
        "import",
        store.as_posix(),
        "A",
        _image_id("A"),
        source.as_posix(),
    )

    assert result.returncode != 0
    assert "symlink" in result.stderr
    assert not (store / ".manifests" / "A.manifest").exists()
    assert not (store / "assets" / "chunk-A.js").exists()


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFO files require POSIX")
def test_rejects_special_files_before_publishing(tmp_path: Path) -> None:
    store = tmp_path / "host-assets"
    source = _tree(tmp_path / "fixtures", "A")
    mkfifo = getattr(os, "mkfifo", None)
    assert callable(mkfifo)
    mkfifo(source / "pipe")

    result = _helper(
        tmp_path,
        "import",
        store.as_posix(),
        "A",
        _image_id("A"),
        source.as_posix(),
    )

    assert result.returncode != 0
    assert "no regular" in result.stderr
    assert not (store / ".manifests" / "A.manifest").exists()


def test_rejects_release_traversal_and_store_inside_checkout(tmp_path: Path) -> None:
    source = _tree(tmp_path / "fixtures", "A")
    store = tmp_path / "host-assets"
    bad_release = _helper(
        tmp_path,
        "import",
        store.as_posix(),
        "../checkout",
        _image_id("A"),
        source.as_posix(),
    )
    assert bad_release.returncode != 0
    assert "release invalido" in bad_release.stderr

    checkout = tmp_path / "checkout"
    inside = checkout / "assets"
    bad_store = _helper(tmp_path, "store", inside.as_posix())
    assert bad_store.returncode != 0
    assert "fuera del checkout" in bad_store.stderr
    assert not inside.exists()


def test_capacity_failure_happens_before_any_publication(tmp_path: Path) -> None:
    source = _tree(tmp_path / "fixtures", "A")
    store = tmp_path / "host-assets"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_df = bin_dir / "df"
    fake_df.write_text(
        "#!/bin/sh\nprintf 'Filesystem 1024-blocks Used Available Capacity Mounted on\\n/dev/test 1 1 0 100%% /\\n'\n",
        encoding="utf-8",
    )
    fake_df.chmod(0o755)
    path = os.pathsep.join([str(bin_dir), os.environ.get("PATH", "")])

    result = _helper(
        tmp_path,
        "capacity",
        store.as_posix(),
        "1",
        source.as_posix(),
        env={"PATH": path},
    )

    assert result.returncode != 0
    assert "espacio insuficiente" in result.stderr
    assert not list((store / ".manifests").glob("*.manifest"))
    assert not list((store / "assets").rglob("*"))


def test_capacity_bytes_rejects_low_space_without_assets(tmp_path: Path) -> None:
    store = tmp_path / "host-assets"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_df = bin_dir / "df"
    fake_df.write_text(
        "#!/bin/sh\nprintf 'Filesystem 1024-blocks Used Available Capacity Mounted on\\n/dev/test 1 1 0 100%% /\\n'\n",
        encoding="utf-8",
    )
    fake_df.chmod(0o755)
    path = os.pathsep.join([str(bin_dir), os.environ.get("PATH", "")])

    result = _helper(
        tmp_path,
        "capacity-bytes",
        store.as_posix(),
        "0",
        "1024",
        env={"PATH": path},
    )

    assert result.returncode != 0
    assert "espacio insuficiente" in result.stderr
    assert not list((store / "assets").rglob("*"))


def test_gc_keeps_at_least_three_and_fourteen_days_and_shared_assets(
    tmp_path: Path,
) -> None:
    fixtures = tmp_path / "fixtures"
    store = tmp_path / "host-assets"
    releases = ("A", "B", "C", "D")
    for release in releases:
        _import(tmp_path, store, _tree(fixtures, release), release)
    now = int(time.time())
    for index, release in enumerate(releases, start=1):
        age = (len(releases) - index + 1) * AGE_14_DAYS
        _set_import_time(store / ".manifests" / f"{release}.manifest", now - age)

    result = _helper(
        tmp_path,
        "gc",
        store.as_posix(),
        "D",
        "C",
        str(AGE_14_DAYS),
        "3",
    )

    assert result.returncode == 0, result.stderr
    manifests = {p.stem for p in (store / ".manifests").glob("*.manifest")}
    assert manifests == {"B", "C", "D"}
    assert (store / "assets" / "shared.js").is_file()
    assert not (store / "assets" / "chunk-A.js").exists()
    for release in ("B", "C", "D"):
        assert (store / "assets" / f"chunk-{release}.js").is_file()


def test_gc_preserves_explicit_rollback_protection(tmp_path: Path) -> None:
    fixtures = tmp_path / "fixtures"
    store = tmp_path / "host-assets"
    for release in ("A", "B", "C", "D", "E"):
        _import(tmp_path, store, _tree(fixtures, release), release)
    now = int(time.time())
    releases = ("A", "B", "C", "D", "E")
    for index, release in enumerate(releases, start=1):
        age = (len(releases) - index + 1) * AGE_14_DAYS
        _set_import_time(store / ".manifests" / f"{release}.manifest", now - age)

    result = _helper(
        tmp_path,
        "gc",
        store.as_posix(),
        "E",
        "D",
        str(AGE_14_DAYS),
        "3",
        env={"DEPLOY_ASSET_PROTECTED_RELEASES": "A"},
    )

    assert result.returncode == 0, result.stderr
    manifests = {p.stem for p in (store / ".manifests").glob("*.manifest")}
    assert manifests == {"A", "C", "D", "E"}


def test_gc_does_not_remove_release_younger_than_fourteen_days(tmp_path: Path) -> None:
    fixtures = tmp_path / "fixtures"
    store = tmp_path / "host-assets"
    for release in ("A", "B", "C", "D"):
        _import(tmp_path, store, _tree(fixtures, release), release)
    now = int(time.time())
    _set_import_time(store / ".manifests" / "A.manifest", now - AGE_14_DAYS + 60)
    for release, days in (("B", 1), ("C", 2), ("D", 3)):
        _set_import_time(
            store / ".manifests" / f"{release}.manifest", now - days * 86400
        )

    result = _helper(
        tmp_path,
        "gc",
        store.as_posix(),
        "D",
        "C",
        str(AGE_14_DAYS),
        "3",
    )

    assert result.returncode == 0, result.stderr
    assert (store / ".manifests" / "A.manifest").exists()
    assert (store / "assets" / "chunk-A.js").exists()

    _set_import_time(store / ".manifests" / "A.manifest", now - AGE_14_DAYS - 60)
    eligible = _helper(
        tmp_path,
        "gc",
        store.as_posix(),
        "D",
        "C",
        str(AGE_14_DAYS),
        "3",
    )
    assert eligible.returncode == 0, eligible.stderr
    assert not (store / ".manifests" / "A.manifest").exists()


@pytest.mark.parametrize(
    ("age_seconds", "keep_min"),
    [("0", "3"), (str(AGE_14_DAYS), "2")],
)
def test_gc_rejects_retention_below_the_minimum(
    tmp_path: Path, age_seconds: str, keep_min: str
) -> None:
    fixtures = tmp_path / "fixtures"
    store = tmp_path / "host-assets"
    for release in ("A", "B", "C"):
        _import(tmp_path, store, _tree(fixtures, release), release)

    result = _helper(
        tmp_path,
        "gc",
        store.as_posix(),
        "C",
        "B",
        age_seconds,
        keep_min,
    )

    assert result.returncode != 0
    assert "al menos 14 dias y 3 releases" in result.stderr
    assert {p.stem for p in (store / ".manifests").glob("*.manifest")} == {
        "A",
        "B",
        "C",
    }


def test_nested_subdirectory_gets_world_traverse_under_umask_077(
    tmp_path: Path,
) -> None:
    if os.name == "nt":
        pytest.skip("Windows NTFS does not expose POSIX directory modes")
    fixtures = tmp_path / "fixtures"
    store = tmp_path / "host-assets"
    source = _tree(fixtures, "A")
    assert BASH is not None
    checkout = tmp_path / "checkout"
    checkout.mkdir(exist_ok=True)
    result = subprocess.run(
        [
            BASH,
            "-c",
            f'umask 077 && exec bash "{HELPER.as_posix()}" import "{store.as_posix()}" "A" "{_image_id("A")}" "{source.as_posix()}"',
        ],
        cwd=checkout,
        env={**os.environ, "SHIFTY_DIR": checkout.as_posix()},
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert (store / "assets" / "fonts").stat().st_mode & 0o777 == 0o755
    assert (store / "assets" / "fonts" / "font-A.woff2").stat().st_mode & 0o777 == 0o444


def test_gc_on_empty_store_preserves_public_assets_dir(tmp_path: Path) -> None:
    store = tmp_path / "host-assets"
    prep = _helper(tmp_path, "prepare", store.as_posix())
    assert prep.returncode == 0, prep.stderr

    result = _helper(tmp_path, "gc", store.as_posix(), "", "", str(AGE_14_DAYS), "3")

    assert result.returncode == 0, result.stderr
    assert (store / "assets").is_dir()


def test_gc_sweeps_orphaned_asset_and_stale_staging_after_crash(
    tmp_path: Path,
) -> None:
    fixtures = tmp_path / "fixtures"
    store = tmp_path / "host-assets"
    _import(tmp_path, store, _tree(fixtures, "A"), "A")
    orphan_dir = store / "assets" / "orphan"
    orphan_dir.mkdir()
    orphan_file = orphan_dir / "dead-chunk.js"
    orphan_file.write_text("orphan\n", encoding="utf-8")
    orphan_file.chmod(0o444)
    stale_helper = store / ".staging" / "file.leftover"
    stale_helper.write_text("leftover\n", encoding="utf-8")
    stale_staging = store / ".staging" / "shifty-assets.stale"
    stale_staging.mkdir()
    (stale_staging / "leftover.js").write_text("stale\n", encoding="utf-8")
    old = time.time() - 7200
    os.utime(stale_staging, (old, old))
    active_staging = store / ".staging" / "shifty-assets.active"
    active_staging.mkdir()
    (active_staging / "in-flight.js").write_text("active\n", encoding="utf-8")

    result = _helper(tmp_path, "gc", store.as_posix(), "A", "", str(AGE_14_DAYS), "3")

    assert result.returncode == 0, result.stderr
    assert not orphan_file.exists()
    assert not orphan_dir.exists()
    assert not stale_helper.exists()
    assert not stale_staging.exists()
    assert active_staging.is_dir()
    assert (store / "assets" / "chunk-A.js").is_file()


@pytest.mark.parametrize("relative", [".env", "sub/.env"])
def test_rejects_dotfile_asset_paths(tmp_path: Path, relative: str) -> None:
    store = tmp_path / "host-assets"
    source = _tree(tmp_path / "fixtures", "A")
    secret = source / relative
    secret.parent.mkdir(parents=True, exist_ok=True)
    secret.write_text("SECRET=value\n", encoding="utf-8")

    result = _helper(
        tmp_path,
        "import",
        store.as_posix(),
        "A",
        _image_id("A"),
        source.as_posix(),
    )

    assert result.returncode != 0
    assert "ruta de asset invalida" in result.stderr
    assert not (store / ".manifests" / "A.manifest").exists()
    assert not (store / "assets" / "chunk-A.js").exists()
    assert not (store / "assets" / relative).exists()


@pytest.mark.parametrize("subcommand", ["store", "prepare"])
def test_rejects_symlink_store_with_trailing_slash(
    tmp_path: Path, subcommand: str
) -> None:
    real_store = tmp_path / "real-store"
    real_store.mkdir()
    symlink_store = tmp_path / "symlink-store"
    try:
        symlink_store.symlink_to(real_store, target_is_directory=True)
    except OSError:
        pytest.skip("Windows symlink creation requires extra privileges")

    result = _helper(tmp_path, subcommand, symlink_store.as_posix() + "/")

    assert result.returncode != 0
    assert "symlink" in result.stderr
