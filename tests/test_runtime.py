import os
import subprocess
import sys
from pathlib import Path

import pytest

from help_me_tibooo.runtime import (
    exclusive_state,
    require_existing_state,
    validate_output_paths,
    validate_shadow_paths,
)


def test_exclusive_state_blocks_another_process_through_a_symlink_alias(tmp_path: Path) -> None:
    state_path = tmp_path / "state.json"
    state_path.write_text("{}", encoding="utf-8")
    state_alias = tmp_path / "state-alias.json"
    state_alias.symlink_to(state_path)

    holder = _start_holder(state_alias)
    try:
        assert holder.stdout.readline().strip() == "locked"

        temporary_state_path = state_path.with_suffix(".tmp")
        temporary_state_path.write_text('{"version": 4}', encoding="utf-8")
        temporary_state_path.replace(state_path)

        assert _try_lock(state_path) == "contended"

        holder.stdin.write("release\n")
        holder.stdin.flush()
        assert holder.stdout.readline().strip() == "released"
        assert holder.wait(timeout=5) == 0

        assert _try_lock(state_alias) == "entered"
    finally:
        _stop_process(holder)


def test_exclusive_state_releases_the_lock_after_an_exception(tmp_path: Path) -> None:
    state_path = tmp_path / "state.json"

    with pytest.raises(ValueError, match="boom"):
        with exclusive_state(state_path):
            raise ValueError("boom")

    with exclusive_state(state_path):
        pass


def test_exclusive_state_rejects_an_existing_hardlinked_state_file(tmp_path: Path) -> None:
    state_path = tmp_path / "state.json"
    state_path.write_text("{}", encoding="utf-8")
    os.link(state_path, tmp_path / "state-copy.json")

    with pytest.raises(ValueError):
        with exclusive_state(state_path):
            pass


def test_validate_shadow_paths_rejects_a_shadow_directory_containing_state(
    tmp_path: Path,
) -> None:
    shadow_dir = tmp_path / "shadow"
    production_state_path = shadow_dir / "state.json"

    with pytest.raises(ValueError):
        validate_shadow_paths(production_state_path, shadow_dir)


def test_validate_shadow_paths_rejects_output_symlink_to_production_state(
    tmp_path: Path,
) -> None:
    production_state_path = tmp_path / "state.json"
    production_state_path.write_text("{}", encoding="utf-8")
    shadow_dir = tmp_path / "shadow"
    shadow_dir.mkdir()
    (shadow_dir / "metrics.jsonl").symlink_to(production_state_path)

    with pytest.raises(ValueError):
        validate_shadow_paths(production_state_path, shadow_dir)


def test_validate_shadow_paths_rejects_output_hardlink_to_production_state(
    tmp_path: Path,
) -> None:
    production_state_path = tmp_path / "state.json"
    production_state_path.write_text("{}", encoding="utf-8")
    shadow_dir = tmp_path / "shadow"
    shadow_dir.mkdir()
    os.link(production_state_path, shadow_dir / "observations.json")

    with pytest.raises(ValueError):
        validate_shadow_paths(production_state_path, shadow_dir)


def test_validate_shadow_paths_rejects_lexical_temp_alias_of_symlinked_output(
    tmp_path: Path,
) -> None:
    production_state_path = tmp_path / "state.json"
    production_state_path.write_text("production", encoding="utf-8")
    shadow_dir = tmp_path / "shadow"
    shadow_dir.mkdir()
    target_path = shadow_dir / "target.json"
    target_path.write_text("observation", encoding="utf-8")
    (shadow_dir / "observations.json").symlink_to(target_path)
    os.link(production_state_path, shadow_dir / "observations.tmp")

    with pytest.raises(ValueError):
        validate_shadow_paths(production_state_path, shadow_dir)


def test_validate_shadow_paths_rejects_output_alias_to_production_state_lock(
    tmp_path: Path,
) -> None:
    production_state_path = tmp_path / "state.json"
    production_lock_path = tmp_path / "state.json.lock"
    production_lock_path.write_text("lock", encoding="utf-8")
    shadow_dir = tmp_path / "shadow"
    shadow_dir.mkdir()
    (shadow_dir / "metrics.jsonl").symlink_to(production_lock_path)

    with pytest.raises(ValueError):
        validate_shadow_paths(production_state_path, shadow_dir)


def test_validate_shadow_paths_rejects_output_files_that_alias_each_other(
    tmp_path: Path,
) -> None:
    shadow_dir = tmp_path / "shadow"
    shadow_dir.mkdir()
    metrics_path = shadow_dir / "metrics.jsonl"
    metrics_path.write_text("metric", encoding="utf-8")
    os.link(metrics_path, shadow_dir / "observations.json")

    with pytest.raises(ValueError):
        validate_shadow_paths(None, shadow_dir)


def test_validate_output_paths_rejects_output_aliasing_a_protected_temp_companion(
    tmp_path: Path,
) -> None:
    protected_path = tmp_path / "state.json"
    protected_path.write_text("{}", encoding="utf-8")
    protected_temporary_path = protected_path.with_suffix(".tmp")
    protected_temporary_path.write_text("{}", encoding="utf-8")
    output_path = tmp_path / "metrics.jsonl"
    os.link(protected_temporary_path, output_path)

    with pytest.raises(ValueError):
        validate_output_paths((protected_path,), (output_path,))


def test_require_existing_state_rejects_missing_non_regular_and_dangling_symlink(
    tmp_path: Path,
) -> None:
    missing_path = tmp_path / "missing.json"
    directory_path = tmp_path / "state-directory"
    directory_path.mkdir()
    dangling_alias = tmp_path / "dangling.json"
    dangling_alias.symlink_to(missing_path)

    for path in (missing_path, directory_path, dangling_alias):
        with pytest.raises(ValueError):
            require_existing_state(path)


def test_require_existing_state_accepts_a_regular_file_through_a_symlink_alias(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "state.json"
    state_path.write_text("{}", encoding="utf-8")
    state_alias = tmp_path / "state-alias.json"
    state_alias.symlink_to(state_path)

    require_existing_state(state_alias)


def _start_holder(state_path: Path) -> subprocess.Popen[str]:
    return subprocess.Popen(
        [sys.executable, "-c", _HOLDER_PROGRAM, str(state_path)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=_child_environment(),
    )


def _try_lock(state_path: Path) -> str:
    completed = subprocess.run(
        [sys.executable, "-c", _TRY_LOCK_PROGRAM, str(state_path)],
        capture_output=True,
        check=True,
        text=True,
        env=_child_environment(),
    )
    return completed.stdout.strip()


def _stop_process(process: subprocess.Popen[str]) -> None:
    if process.poll() is None:
        process.stdin.write("release\n")
        process.stdin.flush()
        process.wait(timeout=5)


def _child_environment() -> dict[str, str]:
    source_path = str(Path(__file__).parents[1] / "src")
    existing_python_path = os.environ.get("PYTHONPATH")
    return {
        **os.environ,
        "PYTHONPATH": (
            f"{source_path}{os.pathsep}{existing_python_path}"
            if existing_python_path
            else source_path
        ),
    }


_HOLDER_PROGRAM = """
import sys
from pathlib import Path
from help_me_tibooo.runtime import exclusive_state

with exclusive_state(Path(sys.argv[1])):
    print('locked', flush=True)
    sys.stdin.readline()
    print('released', flush=True)
"""


_TRY_LOCK_PROGRAM = """
import sys
from pathlib import Path
from help_me_tibooo.runtime import exclusive_state

try:
    with exclusive_state(Path(sys.argv[1])):
        print('entered', flush=True)
except RuntimeError:
    print('contended', flush=True)
"""
