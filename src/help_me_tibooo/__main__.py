import argparse
import os
import sys
import time
from pathlib import Path

import httpx

from help_me_tibooo.discord import (
    DiscordBot,
    build_alert_payload,
    build_health_payload,
)
from help_me_tibooo.models import AlertCategory, Post, SourceBatch, WatcherState
from help_me_tibooo.sources import fetch_all_sources
from help_me_tibooo.state import load_state, save_state
from help_me_tibooo.watcher import WatcherRunError, run_watcher


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    bot_token = os.environ.get("DISCORD_BOT_TOKEN")
    channel_id = os.environ.get("DISCORD_CHANNEL_ID")
    if args.command in {"watch", "test-bot"}:
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

    try:
        if args.command == "watch":
            return _watch(Path(args.state_path), bot_token, channel_id)
        if args.command == "test-bot":
            return _test_bot(bot_token, channel_id)
        return _smoke()
    except WatcherRunError as error:
        print(f"감시 실행 실패: {error}", file=sys.stderr)
        return 1
    except Exception:
        print("실행 중 오류가 발생했습니다.", file=sys.stderr)
        return 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="help-me-tibooo")
    subparsers = parser.add_subparsers(dest="command", required=True)
    watch_parser = subparsers.add_parser("watch")
    watch_parser.add_argument("--state-path", default=".state/watcher.json")
    subparsers.add_parser("test-bot")
    subparsers.add_parser("smoke")
    return parser


def _watch(state_path: Path, bot_token: str, channel_id: str) -> int:
    state = load_state(state_path)
    state_to_save: WatcherState | None = state
    with httpx.Client() as client:
        bot = DiscordBot(bot_token, channel_id, client, time.sleep)
        try:
            batches = fetch_all_sources(client)
            _log_source_statuses(batches)
            try:
                state_to_save = run_watcher(
                    batches,
                    state,
                    lambda post, categories: _send_alert(
                        bot,
                        post,
                        categories,
                    ),
                    lambda failure_count: _send_health(bot, failure_count),
                )
            except WatcherRunError as error:
                state_to_save = error.state
                raise
        finally:
            if state_to_save is not None:
                save_state(state_path, state_to_save)
    return 0


def _test_bot(bot_token: str, channel_id: str) -> int:
    with httpx.Client() as client:
        DiscordBot(bot_token, channel_id, client, time.sleep).send(
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


def _smoke() -> int:
    with httpx.Client() as client:
        batches = fetch_all_sources(client)
    _log_source_statuses(batches)
    return 0 if any(batch.error is None for batch in batches) else 1


def _log_source_statuses(batches: tuple[SourceBatch, ...]) -> None:
    for batch in batches:
        status = "정상" if batch.error is None else "실패"
        print(f"{batch.source}: {status}, 게시물 {len(batch.posts)}개")


def _send_alert(
    bot: DiscordBot,
    post: Post,
    categories: tuple[AlertCategory, ...],
) -> None:
    labels = ", ".join(category.value for category in categories)
    print(f"게시물 {post.id} 분류: {labels}")
    try:
        bot.send(build_alert_payload(post, categories))
    except Exception:
        print(f"게시물 {post.id} Discord 알림 전송 실패", file=sys.stderr)
        raise
    print(f"게시물 {post.id} Discord 알림 전송 성공")


def _send_health(bot: DiscordBot, failure_count: int) -> None:
    try:
        bot.send(build_health_payload(failure_count))
    except Exception:
        print(
            f"Discord 감시 장애 알림 전송 실패: 연속 실패 {failure_count}회",
            file=sys.stderr,
        )
        raise
    print(f"Discord 감시 장애 알림 전송 성공: 연속 실패 {failure_count}회")


if __name__ == "__main__":
    raise SystemExit(main())
