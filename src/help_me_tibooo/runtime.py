import errno
import os
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import ContextManager

import fcntl


def exclusive_state(path: Path) -> ContextManager[None]:
    return _exclusive_state(path)


@contextmanager
def _exclusive_state(path: Path) -> Iterator[None]:
    canonical_state_path = _resolve_path(path)
    _reject_hardlinked_state(canonical_state_path)
    lock_path = _state_lock_path(canonical_state_path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        descriptor = os.open(
            lock_path,
            os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW,
            0o600,
        )
    except OSError as error:
        raise RuntimeError("상태 잠금을 열 수 없습니다") from error

    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            if error.errno in {errno.EACCES, errno.EAGAIN}:
                raise RuntimeError("상태 잠금이 이미 사용 중입니다") from None
            raise RuntimeError("상태 잠금을 획득할 수 없습니다") from error
        try:
            yield
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
    finally:
        os.close(descriptor)


def validate_shadow_paths(production_state_path: Path | None, shadow_dir: Path) -> None:
    canonical_shadow_dir = _resolve_path(shadow_dir)
    output_paths = (
        canonical_shadow_dir / "metrics.jsonl",
        canonical_shadow_dir / "observations.json",
    )

    for output_path in _paths_with_companions(output_paths):
        if not _is_within(output_path, canonical_shadow_dir):
            raise ValueError("관측 출력 경로는 shadow 디렉터리 안에 있어야 합니다")

    protected_paths: tuple[Path, ...] = ()
    if production_state_path is not None:
        canonical_state_path = _resolve_path(production_state_path)
        if _is_within(canonical_state_path, canonical_shadow_dir) or _is_within(
            canonical_shadow_dir, canonical_state_path
        ):
            raise ValueError("shadow 디렉터리는 운영 상태 경로와 분리되어야 합니다")
        protected_paths = (canonical_state_path,)

    validate_output_paths(protected_paths, output_paths)


def validate_output_paths(
    protected_paths: tuple[Path, ...], output_paths: tuple[Path, ...]
) -> None:
    canonical_protected_paths = _paths_with_companions(protected_paths)
    canonical_output_paths = _paths_with_companions(output_paths)

    for output_path in canonical_output_paths:
        if any(_paths_alias(output_path, protected_path) for protected_path in canonical_protected_paths):
            raise ValueError("출력 경로가 보호된 운영 경로와 겹칩니다")

    for index, output_path in enumerate(canonical_output_paths):
        for other_output_path in canonical_output_paths[index + 1 :]:
            if _paths_alias(output_path, other_output_path):
                raise ValueError("출력 경로끼리 겹칩니다")


def require_existing_state(path: Path) -> None:
    try:
        metadata = path.stat()
    except FileNotFoundError:
        raise ValueError("운영 상태 파일이 존재하지 않습니다") from None
    except OSError as error:
        raise ValueError("운영 상태 파일을 확인할 수 없습니다") from error

    if not stat.S_ISREG(metadata.st_mode):
        raise ValueError("운영 상태 경로는 일반 파일이어야 합니다")


def _resolve_path(path: Path) -> Path:
    try:
        return path.resolve(strict=False)
    except OSError as error:
        raise ValueError("경로를 확인할 수 없습니다") from error


def _state_lock_path(canonical_state_path: Path) -> Path:
    return canonical_state_path.with_name(f"{canonical_state_path.name}.lock")


def _reject_hardlinked_state(canonical_state_path: Path) -> None:
    try:
        metadata = canonical_state_path.stat()
    except FileNotFoundError:
        return
    except OSError as error:
        raise ValueError("운영 상태 파일을 확인할 수 없습니다") from error

    if stat.S_ISREG(metadata.st_mode) and metadata.st_nlink > 1:
        raise ValueError("운영 상태 파일은 하드링크일 수 없습니다")


def _paths_with_companions(paths: tuple[Path, ...]) -> tuple[Path, ...]:
    expanded_paths: list[Path] = []
    for path in paths:
        canonical_path = _resolve_path(path)
        for companion_path in (*_companion_paths(path), *_companion_paths(canonical_path)):
            resolved_path = _resolve_path(companion_path)
            if resolved_path not in expanded_paths:
                expanded_paths.append(resolved_path)
    return tuple(expanded_paths)


def _companion_paths(path: Path) -> tuple[Path, Path, Path]:
    return (
        path,
        path.with_suffix(".tmp"),
        path.with_name(f"{path.name}.lock"),
    )


def _is_within(path: Path, directory: Path) -> bool:
    try:
        path.relative_to(directory)
    except ValueError:
        return False
    return True


def _paths_alias(left_path: Path, right_path: Path) -> bool:
    if left_path == right_path:
        return True

    try:
        left_metadata = left_path.stat()
    except FileNotFoundError:
        left_metadata = None
    except OSError as error:
        raise ValueError("경로를 확인할 수 없습니다") from error

    try:
        right_metadata = right_path.stat()
    except FileNotFoundError:
        right_metadata = None
    except OSError as error:
        raise ValueError("경로를 확인할 수 없습니다") from error

    return (
        left_metadata is not None
        and right_metadata is not None
        and os.path.samestat(left_metadata, right_metadata)
    )
