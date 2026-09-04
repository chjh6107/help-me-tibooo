from pathlib import Path

from help_me_tibooo.__main__ import main
from help_me_tibooo.models import (
    CheckpointPosition,
    Post,
    SourceBatch,
    SourceCheckpoint,
    SourceName,
    WatcherState,
)
from help_me_tibooo.state import load_state, save_state


def make_post(post_id: str, text: str = "Codex usage reset") -> Post:
    return Post(
        id=post_id,
        text=text,
        created_at=None,
        url=f"https://x.com/thsottiaux/status/{post_id}",
        source=SourceName.RESET,
        source_kind="candidate",
    )


def test_watch_requires_bot_credentials(monkeypatch, capsys, tmp_path: Path) -> None:
    monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)
    monkeypatch.delenv("DISCORD_CHANNEL_ID", raising=False)

    exit_code = main(["watch", "--state-path", str(tmp_path / "watcher.json")])

    assert exit_code == 2
    assert capsys.readouterr().err.splitlines() == [
        "DISCORD_BOT_TOKEN 환경 변수가 필요합니다.",
        "DISCORD_CHANNEL_ID 환경 변수가 필요합니다.",
    ]


def test_smoke_does_not_require_bot_credentials_or_call_discord(monkeypatch, capsys) -> None:
    monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)
    monkeypatch.delenv("DISCORD_CHANNEL_ID", raising=False)
    monkeypatch.setattr(
        "help_me_tibooo.__main__.fetch_all_sources",
        lambda _client: (
            SourceBatch("reset", posts=(make_post("501"),)),
            SourceBatch("twiscan", error="private failure details"),
        ),
    )

    def reject_discord(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("Discord를 호출하면 안 됩니다")

    monkeypatch.setattr("help_me_tibooo.__main__.DiscordBot", reject_discord)

    assert main(["smoke"]) == 0
    assert capsys.readouterr().out.splitlines() == [
        "reset: 정상, 게시물 1개",
        "twiscan: 실패, 게시물 0개",
    ]


def test_smoke_returns_failure_when_every_source_fails(monkeypatch, capsys) -> None:
    monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)
    monkeypatch.delenv("DISCORD_CHANNEL_ID", raising=False)
    monkeypatch.setattr(
        "help_me_tibooo.__main__.fetch_all_sources",
        lambda _client: (
            SourceBatch("reset", error="private reset response"),
            SourceBatch("twiscan", error="private timeline response"),
        ),
    )

    assert main(["smoke"]) == 1
    captured = capsys.readouterr()
    assert captured.out.splitlines() == [
        "reset: 실패, 게시물 0개",
        "twiscan: 실패, 게시물 0개",
    ]
    assert captured.err == ""
    assert "private reset response" not in captured.out
    assert "private timeline response" not in captured.out


def test_test_bot_requires_bot_credentials(monkeypatch, capsys) -> None:
    monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)
    monkeypatch.delenv("DISCORD_CHANNEL_ID", raising=False)

    exit_code = main(["test-bot"])

    assert exit_code == 2
    assert capsys.readouterr().err.splitlines() == [
        "DISCORD_BOT_TOKEN 환경 변수가 필요합니다.",
        "DISCORD_CHANNEL_ID 환경 변수가 필요합니다.",
    ]


def test_test_bot_rejects_invalid_credentials_without_traceback(monkeypatch, capsys) -> None:
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "secret.bot.token")
    monkeypatch.setenv("DISCORD_CHANNEL_ID", "not-a-channel")

    assert main(["test-bot"]) == 1
    assert capsys.readouterr().err == "실행 중 오류가 발생했습니다.\n"


def test_test_bot_sends_only_test_message_without_state_access(monkeypatch) -> None:
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "secret.bot.token")
    monkeypatch.setenv("DISCORD_CHANNEL_ID", "123")
    sent_payloads: list[dict[str, object]] = []
    monkeypatch.setattr(
        "help_me_tibooo.__main__.DiscordBot.send",
        lambda _self, payload: sent_payloads.append(payload),
    )

    def reject_state_access(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("상태 파일에 접근하면 안 됩니다")

    monkeypatch.setattr("help_me_tibooo.__main__.load_state", reject_state_access)
    monkeypatch.setattr("help_me_tibooo.__main__.save_state", reject_state_access)

    assert main(["test-bot"]) == 0
    assert sent_payloads == [
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
    ]


def test_watch_persists_updated_state(monkeypatch, tmp_path: Path) -> None:
    state_path = tmp_path / "watcher.json"
    save_state(
        state_path,
        WatcherState(latest_id="500", seen_ids=("500",), initialized=True),
    )
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "secret.bot.token")
    monkeypatch.setenv("DISCORD_CHANNEL_ID", "123")
    monkeypatch.setattr(
        "help_me_tibooo.__main__.fetch_all_sources",
        lambda _client: (
            SourceBatch("reset", posts=(make_post("501", "A quiet walk today."),)),
        ),
    )

    assert main(["watch", "--state-path", str(state_path)]) == 0
    assert load_state(state_path) == WatcherState(
        latest_id="501",
        seen_ids=("500", "501"),
        initialized=True,
        source_checkpoints=(
            SourceCheckpoint(
                source=SourceName.RESET,
                position=CheckpointPosition(id="501"),
            ),
        ),
    )


def test_watch_logs_source_classification_and_successful_delivery_safely(
    monkeypatch,
    capsys,
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "watcher.json"
    save_state(
        state_path,
        WatcherState(latest_id="900", seen_ids=("900",), initialized=True),
    )
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "secret.bot.token")
    monkeypatch.setenv("DISCORD_CHANNEL_ID", "123")
    monkeypatch.setattr(
        "help_me_tibooo.__main__.fetch_all_sources",
        lambda _client: (
            SourceBatch("reset", posts=(make_post("901"),)),
            SourceBatch("twiscan", error="private source response"),
        ),
    )
    monkeypatch.setattr(
        "help_me_tibooo.__main__.DiscordBot.send",
        lambda _self, _payload: None,
    )

    assert main(["watch", "--state-path", str(state_path)]) == 0
    captured = capsys.readouterr()
    assert captured.out.splitlines() == [
        "reset: 정상, 게시물 1개",
        "twiscan: 실패, 게시물 0개",
        "게시물 901 분류: 리셋",
        "게시물 901 Discord 알림 전송 성공",
    ]
    assert captured.err == ""
    assert "Codex usage reset" not in captured.out
    assert "private source response" not in captured.out
    assert "discord.example" not in captured.out


def test_watch_persists_partial_state_after_delivery_failure(
    monkeypatch,
    capsys,
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "watcher.json"
    save_state(
        state_path,
        WatcherState(latest_id="700", seen_ids=("700",), initialized=True),
    )
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "secret.bot.token")
    monkeypatch.setenv("DISCORD_CHANNEL_ID", "123")
    monkeypatch.setattr(
        "help_me_tibooo.__main__.fetch_all_sources",
        lambda _client: (
            SourceBatch("reset", posts=(make_post("702"), make_post("701"))),
        ),
    )
    send_count = 0

    def fail_second_delivery(_self: object, _payload: dict[str, object]) -> None:
        nonlocal send_count
        send_count += 1
        if send_count == 2:
            raise RuntimeError("secret.bot.token")

    monkeypatch.setattr(
        "help_me_tibooo.__main__.DiscordBot.send",
        fail_second_delivery,
    )

    assert main(["watch", "--state-path", str(state_path)]) == 1
    assert load_state(state_path) == WatcherState(
        latest_id="701",
        seen_ids=("700", "701"),
        initialized=True,
        source_checkpoints=(
            SourceCheckpoint(
                source=SourceName.RESET,
                position=CheckpointPosition(id="701"),
            ),
        ),
    )
    captured = capsys.readouterr()
    assert captured.err.splitlines() == [
        "게시물 702 Discord 알림 전송 실패",
        "감시 실행 실패: alert delivery failed",
    ]
    assert "secret.bot.token" not in captured.out + captured.err


def test_watch_logs_successful_health_delivery_safely(
    monkeypatch,
    capsys,
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "watcher.json"
    save_state(state_path, WatcherState(consecutive_failures=2, initialized=True))
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "secret.bot.token")
    monkeypatch.setenv("DISCORD_CHANNEL_ID", "123")
    monkeypatch.setattr(
        "help_me_tibooo.__main__.fetch_all_sources",
        lambda _client: (
            SourceBatch("reset", error="private reset response"),
            SourceBatch("twiscan", error="private timeline response"),
        ),
    )
    monkeypatch.setattr(
        "help_me_tibooo.__main__.DiscordBot.send",
        lambda _self, _payload: None,
    )

    assert main(["watch", "--state-path", str(state_path)]) == 0
    captured = capsys.readouterr()
    assert captured.out.splitlines() == [
        "reset: 실패, 게시물 0개",
        "twiscan: 실패, 게시물 0개",
        "Discord 감시 장애 알림 전송 성공: 연속 실패 3회",
    ]
    assert captured.err == ""
    assert "private reset response" not in captured.out
    assert "private timeline response" not in captured.out
    assert "discord.example" not in captured.out


def test_watch_logs_failed_health_delivery_without_error_details(
    monkeypatch,
    capsys,
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "watcher.json"
    save_state(state_path, WatcherState(consecutive_failures=2, initialized=True))
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "secret.bot.token")
    monkeypatch.setenv("DISCORD_CHANNEL_ID", "123")
    monkeypatch.setattr(
        "help_me_tibooo.__main__.fetch_all_sources",
        lambda _client: (
            SourceBatch("reset", error="down"),
            SourceBatch("twiscan", error="down"),
        ),
    )

    def fail_delivery(_self: object, _payload: dict[str, object]) -> None:
        raise RuntimeError("secret.bot.token")

    monkeypatch.setattr(
        "help_me_tibooo.__main__.DiscordBot.send",
        fail_delivery,
    )

    assert main(["watch", "--state-path", str(state_path)]) == 0
    captured = capsys.readouterr()
    assert captured.err.splitlines() == [
        "Discord 감시 장애 알림 전송 실패: 연속 실패 3회"
    ]
    assert "secret.bot.token" not in captured.out + captured.err


def test_watch_retains_last_valid_state_after_unexpected_failure(
    monkeypatch,
    capsys,
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "watcher.json"
    expected = WatcherState(
        latest_id="800",
        seen_ids=("799", "800"),
        consecutive_failures=1,
        initialized=True,
    )
    save_state(state_path, expected)
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "secret.bot.token")
    monkeypatch.setenv("DISCORD_CHANNEL_ID", "123")

    def fail_fetch(_client: object) -> tuple[SourceBatch, ...]:
        raise RuntimeError("secret.bot.token")

    monkeypatch.setattr("help_me_tibooo.__main__.fetch_all_sources", fail_fetch)

    assert main(["watch", "--state-path", str(state_path)]) == 1
    assert load_state(state_path) == expected
    assert "secret.bot.token" not in capsys.readouterr().err
