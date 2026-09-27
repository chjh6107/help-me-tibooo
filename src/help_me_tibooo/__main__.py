import argparse
import os
import re
import sys
import time
from collections.abc import Callable
from pathlib import Path

import httpx

from help_me_tibooo.discord import (
    DiscordBot,
    DiscordBotCredentials,
    build_alert_payloads,
    build_health_payload,
    build_recovery_payload,
    format_source_diagnostic,
)
from help_me_tibooo.diagnostics import DiagnosticIndexError, DiagnosticRun
from help_me_tibooo.models import AlertCategory, Post, SourceBatch, SourceName, WatcherState
from help_me_tibooo.polling import run_polling_session
from help_me_tibooo.runtime import (
    exclusive_state,
    require_existing_state,
    validate_output_paths,
    validate_shadow_paths,
)
from help_me_tibooo.sources import (
    batches_from_snapshots,
    collection_status,
    fetch_all_sources,
    fetch_source_snapshots,
)
from help_me_tibooo.source_transport import SourceTransport
from help_me_tibooo.state import load_state, save_state
from help_me_tibooo.watcher import (
    AlertDeliveryInterrupted,
    WatcherRunError,
    run_watcher,
)


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        credentials: DiscordBotCredentials | None = None
        if args.command in {"watch", "watch-loop", "test-bot"}:
            bot_token = os.environ.get("DISCORD_BOT_TOKEN")
            channel_id = os.environ.get("DISCORD_CHANNEL_ID")
            missing = tuple(
                name
                for name, value in (
                    ("DISCORD_BOT_TOKEN", bot_token),
                    ("DISCORD_CHANNEL_ID", channel_id),
                )
                if not value
            )
            if missing:
                for name in missing:
                    print(f"{name} 환경 변수가 필요합니다.", file=sys.stderr)
                return 2
            credentials = DiscordBotCredentials(bot_token, channel_id)

        if args.command == "watch":
            assert credentials is not None
            return _watch(
                Path(args.state_path),
                credentials,
                require_state=args.require_existing_state,
                metrics_path=(
                    Path(args.metrics_path) if args.metrics_path is not None else None
                ),
            )
        if args.command == "watch-loop":
            assert credentials is not None
            return run_polling_session(
                lambda: _watch(
                    Path(args.state_path),
                    credentials,
                    require_state=True,
                    metrics_path=Path(args.metrics_path) if args.metrics_path else None,
                ),
                interval_seconds=args.interval_seconds,
                duration_seconds=args.duration_seconds,
            )
        if args.command == "test-bot":
            assert credentials is not None
            return _test_bot(credentials)
        if args.command == "observe":
            production_state_path = (
                Path(args.production_state_path)
                if args.production_state_path is not None
                else None
            )
            return _observe(Path(args.shadow_dir), production_state_path)
        return _smoke(args.scope)
    except WatcherRunError as error:
        print(f"감시 실행 실패: {error}", file=sys.stderr)
        return 1
    except DiagnosticIndexError as error:
        print(f"관측 실행 실패: {error}", file=sys.stderr)
        return 2 if args.command == "watch-loop" else 1
    except Exception:
        print("실행 중 오류가 발생했습니다.", file=sys.stderr)
        return 2 if args.command == "watch-loop" else 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="help-me-tibooo")
    subparsers = parser.add_subparsers(dest="command", required=True)
    watch_parser = subparsers.add_parser("watch")
    watch_parser.add_argument("--state-path", default=".state/watcher.json")
    watch_parser.add_argument("--require-existing-state", action="store_true")
    watch_parser.add_argument("--metrics-path")
    loop_parser = subparsers.add_parser("watch-loop")
    loop_parser.add_argument("--state-path", default=".state/watcher.json")
    loop_parser.add_argument("--metrics-path")
    loop_parser.add_argument("--interval-seconds", type=float, default=120)
    loop_parser.add_argument("--duration-seconds", type=float, default=600)
    subparsers.add_parser("test-bot")
    smoke_parser = subparsers.add_parser("smoke")
    smoke_parser.add_argument("--scope", choices=("all", "resets"), default="all")
    observe_parser = subparsers.add_parser("observe")
    observe_parser.add_argument("--shadow-dir", required=True)
    observe_parser.add_argument("--production-state-path")
    return parser


def _watch(
    state_path: Path,
    credentials: DiscordBotCredentials,
    *,
    require_state: bool = False,
    metrics_path: Path | None = None,
) -> int:
    canonical_state_path = state_path.resolve(strict=False)
    canonical_metrics_path: Path | None = None
    canonical_index_path: Path | None = None
    if metrics_path is not None:
        index_path = metrics_path.with_suffix(".observations.json")
        validate_output_paths((canonical_state_path,), (metrics_path, index_path))
        canonical_metrics_path = metrics_path.resolve(strict=False)
        canonical_index_path = index_path.resolve(strict=False)

    with exclusive_state(canonical_state_path):
        if require_state:
            require_existing_state(canonical_state_path)
        return _watch_locked(
            canonical_state_path,
            credentials,
            canonical_metrics_path,
            canonical_index_path,
        )


def _watch_locked(
    state_path: Path,
    credentials: DiscordBotCredentials,
    metrics_path: Path | None,
    index_path: Path | None,
) -> int:
    state = load_state(state_path)
    state_to_save: WatcherState | None = state
    sent_count = 0
    diagnostic_context: DiagnosticRun | None = None
    diagnostics: DiagnosticRun | None = None

    if metrics_path is not None and index_path is not None:
        diagnostic_context = DiagnosticRun(metrics_path, index_path)
        try:
            diagnostics = diagnostic_context.__enter__()
        except Exception:
            diagnostic_context = None
            print("진단 기록 실패 · 감시 결과는 계속 저장합니다", file=sys.stderr)

    def record_diagnostic(action: Callable[[DiagnosticRun], None]) -> None:
        nonlocal diagnostics
        if diagnostics is None:
            return
        try:
            action(diagnostics)
        except Exception:
            diagnostics = None
            print("진단 기록 실패 · 감시 결과는 계속 저장합니다", file=sys.stderr)

    with httpx.Client() as client:
        bot = DiscordBot(credentials, client, time.sleep)

        def send_post(post: Post, categories: tuple[AlertCategory, ...]) -> None:
            nonlocal sent_count
            record_diagnostic(
                lambda recorder: recorder.record_alert(post, "attempted", categories)
            )
            try:
                _send_alert(bot, post, categories, _next_payload_index(state, post))
            except Exception:
                record_diagnostic(
                    lambda recorder: recorder.record_alert(post, "failed", categories)
                )
                raise
            record_diagnostic(
                lambda recorder: recorder.record_alert(post, "succeeded", categories)
            )
            sent_count += 1

        def send_health(failure_count: int) -> None:
            record_diagnostic(
                lambda recorder: recorder.record_delivery("health", "health", "attempted")
            )
            try:
                _send_health(bot, failure_count, batches, actions_url)
            except Exception:
                record_diagnostic(
                    lambda recorder: recorder.record_delivery("health", "health", "failed")
                )
                raise
            record_diagnostic(
                lambda recorder: recorder.record_delivery("health", "health", "succeeded")
            )

        def send_recovery() -> None:
            record_diagnostic(
                lambda recorder: recorder.record_delivery(
                    "recovery", "recovery", "attempted"
                )
            )
            try:
                _send_recovery(bot, batches, actions_url)
            except Exception:
                record_diagnostic(
                    lambda recorder: recorder.record_delivery(
                        "recovery", "recovery", "failed"
                    )
                )
                raise
            record_diagnostic(
                lambda recorder: recorder.record_delivery(
                    "recovery", "recovery", "succeeded"
                )
            )

        try:
            with httpx.Client(transport=SourceTransport()) as source_client:
                if metrics_path is None:
                    batches = fetch_all_sources(source_client)
                else:
                    snapshots = []
                    for snapshot in fetch_source_snapshots(source_client):
                        record_diagnostic(
                            lambda recorder, item=snapshot: recorder.record_snapshot(item)
                        )
                        snapshots.append(snapshot)
                    batches = batches_from_snapshots(tuple(snapshots))
            _log_source_statuses(batches)
            actions_url = _github_actions_run_url()
            try:
                state_to_save = run_watcher(
                    batches,
                    state,
                    send_post,
                    send_health,
                    send_recovery=send_recovery,
                )
            except WatcherRunError as error:
                state_to_save = error.state
                raise
            finally:
                status = collection_status(batches)
                record_diagnostic(lambda recorder: recorder.finish(status))
                print(f"실행 요약: {status} · 게시물 알림 {sent_count}건")
        finally:
            try:
                if state_to_save is not None:
                    save_state(state_path, state_to_save)
            finally:
                if diagnostic_context is not None:
                    try:
                        diagnostic_context.__exit__(*sys.exc_info())
                    except Exception:
                        print(
                            "진단 기록 실패 · 감시 결과는 계속 저장합니다",
                            file=sys.stderr,
                        )
    return 0 if collection_status(batches) == "수집 정상" else 1


def _test_bot(credentials: DiscordBotCredentials) -> int:
    with httpx.Client() as client:
        DiscordBot(credentials, client, time.sleep).send(
            {
                "embeds": [
                    {
                        "title": "티보햄 · 연결 테스트",
                        "description": "Discord 봇 연결이 정상입니다.",
                        "color": 0x22C55E,
                    }
                ],
                "allowed_mentions": {"parse": []},
            }
        )
    return 0


def _smoke(scope: str = "all") -> int:
    with httpx.Client(transport=SourceTransport()) as client:
        batches = fetch_all_sources(client)
    _log_source_statuses(batches)
    if scope == "resets":
        return 0 if any(batch.source == SourceName.RESETS and batch.error is None for batch in batches) else 1
    return 0 if collection_status(batches) == "수집 정상" else 1


def _observe(shadow_dir: Path, production_state_path: Path | None) -> int:
    validate_shadow_paths(production_state_path, shadow_dir)
    canonical_shadow_dir = shadow_dir.resolve(strict=False)
    metrics_path = (canonical_shadow_dir / "metrics.jsonl").resolve(strict=False)
    index_path = (canonical_shadow_dir / "observations.json").resolve(strict=False)
    snapshots = []
    with DiagnosticRun(metrics_path, index_path) as diagnostics:
        with httpx.Client(transport=SourceTransport()) as client:
            for snapshot in fetch_source_snapshots(client):
                diagnostics.record_snapshot(snapshot)
                snapshots.append(snapshot)
        batches = batches_from_snapshots(tuple(snapshots))
        status = collection_status(batches)
        diagnostics.finish(status)
    _log_source_statuses(batches)
    return 0 if status == "수집 정상" else 1


def _log_source_statuses(batches: tuple[SourceBatch, ...]) -> None:
    for batch in batches:
        print(f"{batch.source}: {format_source_diagnostic(batch)}")


def _github_actions_run_url() -> str | None:
    repository = os.environ.get("GITHUB_REPOSITORY")
    run_id = os.environ.get("GITHUB_RUN_ID")
    if not (
        repository
        and len(repository) <= 200
        and re.fullmatch(r"[A-Za-z0-9._-]+/[A-Za-z0-9._-]+", repository)
        and all(part not in {".", ".."} for part in repository.split("/"))
        and run_id
        and run_id.isascii()
        and run_id.isdigit()
        and 1 <= len(run_id) <= 20
    ):
        return None
    return f"https://github.com/{repository}/actions/runs/{run_id}"


def _send_alert(
    bot: DiscordBot,
    post: Post,
    categories: tuple[AlertCategory, ...],
    next_payload_index: int = 0,
) -> None:
    labels = ", ".join(category.value for category in categories)
    print(f"게시물 {post.id} 분류: {labels}")
    payloads = build_alert_payloads(post, categories)
    if next_payload_index > len(payloads):
        raise RuntimeError("Discord 알림 재개 지점이 잘못되었습니다")
    for payload_index, payload in enumerate(
        payloads[next_payload_index:],
        start=next_payload_index,
    ):
        try:
            bot.send(payload)
        except Exception:
            print(f"게시물 {post.id} Discord 알림 전송 실패", file=sys.stderr)
            raise AlertDeliveryInterrupted(payload_index) from None
    print(f"게시물 {post.id} Discord 알림 전송 성공")


def _next_payload_index(state: WatcherState | None, post: Post) -> int:
    if state is None or state.alert_delivery is None:
        return 0
    if state.alert_delivery.post_id != post.id:
        return 0
    return state.alert_delivery.next_payload_index


def _send_health(
    bot: DiscordBot,
    failure_count: int,
    batches: tuple[SourceBatch, ...],
    actions_url: str | None,
) -> None:
    try:
        bot.send(build_health_payload(failure_count, batches, actions_url))
    except Exception:
        print(
            f"Discord 감시 장애 알림 전송 실패: 연속 실패 {failure_count}회",
            file=sys.stderr,
        )
        raise
    print(f"Discord 감시 장애 알림 전송 성공: 연속 실패 {failure_count}회")


def _send_recovery(
    bot: DiscordBot, batches: tuple[SourceBatch, ...], actions_url: str | None,
) -> None:
    try:
        bot.send(build_recovery_payload(batches, actions_url))
    except Exception:
        print("Discord 감시 복구 알림 전송 실패", file=sys.stderr)
        raise
    print("Discord 감시 복구 알림 전송 성공")


if __name__ == "__main__":
    raise SystemExit(main())
