from pathlib import Path

from help_me_tibooo.__main__ import main
from help_me_tibooo.models import Post, SourceBatch, WatcherState
from help_me_tibooo.state import load_state, save_state


def make_post(post_id: str, text: str = "Codex usage reset") -> Post:
    return Post(
        id=post_id,
        text=text,
        created_at=None,
        url=f"https://x.com/thsottiaux/status/{post_id}",
        source="test",
        source_kind="candidate",
    )


def test_watch_requires_webhook(monkeypatch, capsys, tmp_path: Path) -> None:
    monkeypatch.delenv("DISCORD_WEBHOOK_URL", raising=False)

    exit_code = main(["watch", "--state-path", str(tmp_path / "watcher.json")])

    assert exit_code == 2
    assert "DISCORD_WEBHOOK_URL" in capsys.readouterr().err


def test_smoke_does_not_require_webhook_or_call_discord(monkeypatch, capsys) -> None:
    monkeypatch.delenv("DISCORD_WEBHOOK_URL", raising=False)
    monkeypatch.setattr(
        "help_me_tibooo.__main__.fetch_all_sources",
        lambda _client: (
            SourceBatch("reset", posts=(make_post("501"),)),
            SourceBatch("twiscan", error="private failure details"),
        ),
    )

    def reject_discord(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("Discord를 호출하면 안 됩니다")

    monkeypatch.setattr("help_me_tibooo.__main__.DiscordWebhook", reject_discord)

    assert main(["smoke"]) == 0
    assert capsys.readouterr().out.splitlines() == [
        "reset: 정상, 게시물 1개",
        "twiscan: 실패, 게시물 0개",
    ]


def test_test_discord_requires_webhook(monkeypatch, capsys) -> None:
    monkeypatch.delenv("DISCORD_WEBHOOK_URL", raising=False)

    exit_code = main(["test-discord"])

    assert exit_code == 2
    assert "DISCORD_WEBHOOK_URL" in capsys.readouterr().err


def test_test_discord_sends_only_test_message_without_state_access(monkeypatch) -> None:
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://discord.example/webhook")
    sent_payloads: list[dict[str, object]] = []
    monkeypatch.setattr(
        "help_me_tibooo.__main__.DiscordWebhook.send",
        lambda _self, payload: sent_payloads.append(payload),
    )

    def reject_state_access(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("상태 파일에 접근하면 안 됩니다")

    monkeypatch.setattr("help_me_tibooo.__main__.load_state", reject_state_access)
    monkeypatch.setattr("help_me_tibooo.__main__.save_state", reject_state_access)

    assert main(["test-discord"]) == 0
    assert sent_payloads == [
        {
            "content": "Help Me Tibooo 테스트 알림",
            "allowed_mentions": {"parse": []},
        }
    ]


def test_watch_persists_updated_state(monkeypatch, tmp_path: Path) -> None:
    state_path = tmp_path / "watcher.json"
    save_state(
        state_path,
        WatcherState(latest_id="500", seen_ids=("500",), initialized=True),
    )
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://discord.example/webhook")
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
    )


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
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://discord.example/webhook")
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
            raise RuntimeError("https://discord.example/webhook")

    monkeypatch.setattr(
        "help_me_tibooo.__main__.DiscordWebhook.send",
        fail_second_delivery,
    )

    assert main(["watch", "--state-path", str(state_path)]) == 1
    assert load_state(state_path) == WatcherState(
        latest_id="701",
        seen_ids=("700", "701"),
        initialized=True,
    )
    assert "discord.example" not in capsys.readouterr().err


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
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "https://discord.example/webhook")

    def fail_fetch(_client: object) -> tuple[SourceBatch, ...]:
        raise RuntimeError("https://discord.example/webhook")

    monkeypatch.setattr("help_me_tibooo.__main__.fetch_all_sources", fail_fetch)

    assert main(["watch", "--state-path", str(state_path)]) == 1
    assert load_state(state_path) == expected
    assert "discord.example" not in capsys.readouterr().err
