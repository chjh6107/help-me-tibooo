import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from help_me_tibooo.__main__ import main
from help_me_tibooo.diagnostics import DiagnosticRun
from help_me_tibooo.models import (
    AlertDeliveryCheckpoint,
    AlertCategory,
    CheckpointPosition,
    Post,
    SourceBatch,
    SourceCheckpoint,
    SourceName,
    SourceSnapshot,
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
        "reset: 정상 응답 · 게시물 1개",
        "twiscan: 실패 · 알 수 없는 오류",
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
        "reset: 실패 · 알 수 없는 오류",
        "twiscan: 실패 · 알 수 없는 오류",
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
        "reset: 정상 응답 · 게시물 1개",
        "twiscan: 실패 · 알 수 없는 오류",
        "게시물 901 분류: 리셋",
        "게시물 901 Discord 알림 전송 성공",
        "실행 요약: 수집 정상 · 게시물 알림 1건",
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
        handled_reset_ids=("701",),
        initialized=True,
        source_checkpoints=(
            SourceCheckpoint(
                source=SourceName.RESET,
                position=CheckpointPosition(id="701"),
            ),
        ),
        alert_delivery=AlertDeliveryCheckpoint(
            post=make_post("702"),
            categories=(AlertCategory.RESET,),
            sources=(SourceName.RESET,),
            next_payload_index=0,
        ),
    )
    captured = capsys.readouterr()
    assert captured.err.splitlines() == [
        "게시물 702 Discord 알림 전송 실패",
        "감시 실행 실패: alert delivery failed",
    ]
    assert "secret.bot.token" not in captured.out + captured.err


def test_watch_resumes_long_alert_from_first_unsent_payload(
    monkeypatch,
    capsys,
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "watcher.json"
    save_state(
        state_path,
        WatcherState(
            latest_id="900",
            seen_ids=("900",),
            initialized=True,
            source_checkpoints=(
                SourceCheckpoint(
                    source=SourceName.RESET,
                    position=CheckpointPosition(id="900"),
                ),
            ),
        ),
    )
    text = "Codex usage reset " + ("a" * 8_200)
    post = make_post("901", text)
    newer_post = make_post("902", "Codex usage reset 902")
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "secret.bot.token")
    monkeypatch.setenv("DISCORD_CHANNEL_ID", "123")
    source_runs = iter(
        (
            (SourceBatch("reset", posts=(post,)),),
            (SourceBatch("reset", posts=(newer_post,)),),
        )
    )
    monkeypatch.setattr(
        "help_me_tibooo.__main__.fetch_all_sources",
        lambda _client: next(source_runs),
    )
    first_attempt: list[str] = []

    def fail_second_payload(_self: object, payload: dict[str, object]) -> None:
        first_attempt.append(payload["embeds"][0]["description"])
        if len(first_attempt) == 2:
            raise RuntimeError("bot unavailable")

    monkeypatch.setattr(
        "help_me_tibooo.__main__.DiscordBot.send",
        fail_second_payload,
    )

    assert main(["watch", "--state-path", str(state_path)]) == 1
    interrupted_state = load_state(state_path)
    assert interrupted_state is not None
    assert interrupted_state.alert_delivery == AlertDeliveryCheckpoint(
        post=post,
        categories=(AlertCategory.RESET,),
        sources=(SourceName.RESET,),
        next_payload_index=1,
    )

    resumed_payloads: list[str] = []
    monkeypatch.setattr(
        "help_me_tibooo.__main__.DiscordBot.send",
        lambda _self, payload: resumed_payloads.append(
            payload["embeds"][0]["description"]
        ),
    )

    assert main(["watch", "--state-path", str(state_path)]) == 0
    final_state = load_state(state_path)
    assert final_state is not None
    assert final_state.alert_delivery is None
    assert final_state.seen_ids == ("900", "901", "902")
    assert len(first_attempt) == 2
    assert "".join(resumed_payloads[:-1]) == text[4_096:]
    assert resumed_payloads[-1] == newer_post.text
    assert first_attempt[0] not in resumed_payloads
    assert "bot unavailable" not in capsys.readouterr().err


def test_watch_logs_successful_health_delivery_safely(
    monkeypatch,
    capsys,
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "watcher.json"
    save_state(state_path, WatcherState(consecutive_failures=2, initialized=True))
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "secret.bot.token")
    monkeypatch.setenv("DISCORD_CHANNEL_ID", "123")
    monkeypatch.setenv("GITHUB_REPOSITORY", "chjh6107/help-me-tibooo")
    monkeypatch.setenv("GITHUB_RUN_ID", "987654321")
    monkeypatch.setattr(
        "help_me_tibooo.__main__.fetch_all_sources",
        lambda _client: (
            SourceBatch("reset", error="private reset response"),
            SourceBatch("twiscan", error="private timeline response"),
        ),
    )
    sent_payloads: list[dict[str, object]] = []
    monkeypatch.setattr(
        "help_me_tibooo.__main__.DiscordBot.send",
        lambda _self, payload: sent_payloads.append(payload),
    )

    assert main(["watch", "--state-path", str(state_path)]) == 1
    captured = capsys.readouterr()
    assert captured.out.splitlines() == [
        "reset: 실패 · 알 수 없는 오류",
        "twiscan: 실패 · 알 수 없는 오류",
        "Discord 감시 장애 알림 전송 성공: 연속 실패 3회",
        "실행 요약: 수집 실패 · 게시물 알림 0건",
    ]
    assert captured.err == ""
    assert "private reset response" not in captured.out
    assert "private timeline response" not in captured.out
    assert "discord.example" not in captured.out
    description = sent_payloads[0]["embeds"][0]["description"]
    assert "reset: 실패 · 알 수 없는 오류" in description
    assert "twiscan: 실패 · 알 수 없는 오류" in description
    assert (
        "실행 로그: [GitHub Actions에서 열기]"
        "(https://github.com/chjh6107/help-me-tibooo/actions/runs/987654321)"
        in description
    )
    assert "private reset response" not in str(sent_payloads)
    assert "private timeline response" not in str(sent_payloads)


@pytest.mark.parametrize(
    ("repository", "run_id"),
    (
        (None, None),
        ("owner/..", "123"),
        ("./repo", "123"),
        ("owner/.", "123"),
        ("../repo", "123"),
        ("chjh6107/help-me-tibooo/extra", "123"),
        ("chjh6107/help me tibooo", "123"),
        ("chjh6107/help-me-tibooo", "not-a-run"),
        ("chjh6107/help-me-tibooo", "１２３"),
        (("a" * 201) + "/help-me-tibooo", "123"),
    ),
)
def test_watch_omits_actions_link_for_missing_or_invalid_environment(
    monkeypatch,
    tmp_path: Path,
    repository: str | None,
    run_id: str | None,
) -> None:
    state_path = tmp_path / "watcher.json"
    save_state(state_path, WatcherState(consecutive_failures=2, initialized=True))
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "secret.bot.token")
    monkeypatch.setenv("DISCORD_CHANNEL_ID", "123")
    if repository is None:
        monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
    else:
        monkeypatch.setenv("GITHUB_REPOSITORY", repository)
    if run_id is None:
        monkeypatch.delenv("GITHUB_RUN_ID", raising=False)
    else:
        monkeypatch.setenv("GITHUB_RUN_ID", run_id)
    monkeypatch.setattr(
        "help_me_tibooo.__main__.fetch_all_sources",
        lambda _client: (
            SourceBatch("reset", error="HTTP status 503"),
            SourceBatch("twiscan", error="request failed"),
        ),
    )
    sent_payloads: list[dict[str, object]] = []
    monkeypatch.setattr(
        "help_me_tibooo.__main__.DiscordBot.send",
        lambda _self, payload: sent_payloads.append(payload),
    )

    assert main(["watch", "--state-path", str(state_path)]) == 1

    description = sent_payloads[0]["embeds"][0]["description"]
    assert "reset: 실패 · HTTP 503" in description
    assert "twiscan: 실패 · request failed" in description
    assert "실행 로그" not in description


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

    assert main(["watch", "--state-path", str(state_path)]) == 1
    captured = capsys.readouterr()
    assert captured.err.splitlines() == [
        "Discord 감시 장애 알림 전송 실패: 연속 실패 3회"
    ]
    assert "secret.bot.token" not in captured.out + captured.err


def test_watch_reports_recovery_and_distinguishes_no_alerts_from_failed_collection(
    monkeypatch, capsys, tmp_path,
):
    path = tmp_path / "state.json"
    save_state(path, WatcherState(outage_notified=True, consecutive_failures=3))
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "secret.bot.token")
    monkeypatch.setenv("DISCORD_CHANNEL_ID", "123")
    monkeypatch.setattr("help_me_tibooo.__main__.fetch_all_sources", lambda _: (
        SourceBatch("reset", posts=(make_post("123", "quiet day"),)),
        SourceBatch("twiscan", error="private failure details"),
    ))
    sent = []
    monkeypatch.setattr("help_me_tibooo.__main__.DiscordBot.send", lambda _, p: sent.append(p))
    assert main(["watch", "--state-path", str(path)]) == 0
    assert sent[0]["embeds"][0]["title"] == "티보햄 · 감시 복구"
    assert sent[0]["allowed_mentions"] == {"parse": []}
    assert "전체 소식 감시 소스" in sent[0]["embeds"][0]["description"]
    assert "수집 정상 · 게시물 알림 0건" in capsys.readouterr().out
    assert "private failure details" not in str(sent)
    assert main(["watch", "--state-path", str(path)]) == 0
    assert len(sent) == 1


def test_watch_summary_marks_failed_collection(monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "secret.bot.token")
    monkeypatch.setenv("DISCORD_CHANNEL_ID", "123")
    monkeypatch.setattr("help_me_tibooo.__main__.fetch_all_sources", lambda _: (
        SourceBatch("reset"), SourceBatch("twiscan", error="HTTP status 403"),
    ))
    assert main(["watch", "--state-path", str(tmp_path / "state.json")]) == 1
    assert "수집 실패 · 게시물 알림 0건" in capsys.readouterr().out


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


def test_watch_without_metrics_preserves_fetch_all_sources_seam(
    monkeypatch,
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "watcher.json"
    save_state(state_path, WatcherState(initialized=True))
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "secret.bot.token")
    monkeypatch.setenv("DISCORD_CHANNEL_ID", "123")
    monkeypatch.setattr(
        "help_me_tibooo.__main__.fetch_all_sources",
        lambda _client: (SourceBatch("reset", posts=(make_post("100"),)),),
    )

    def reject_snapshots(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("metrics 없는 watch가 snapshot 경로를 사용했습니다")

    monkeypatch.setattr(
        "help_me_tibooo.__main__.fetch_source_snapshots",
        reject_snapshots,
    )
    monkeypatch.setattr("help_me_tibooo.__main__.DiscordBot.send", lambda *_: None)

    assert main(["watch", "--state-path", str(state_path)]) == 0


def test_watch_require_existing_state_fails_before_collection(
    monkeypatch,
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "missing.json"
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "secret.bot.token")
    monkeypatch.setenv("DISCORD_CHANNEL_ID", "123")
    collections = 0

    def count_collection(_client: object) -> tuple[SourceBatch, ...]:
        nonlocal collections
        collections += 1
        return ()

    monkeypatch.setattr(
        "help_me_tibooo.__main__.fetch_all_sources",
        count_collection,
    )

    assert main(
        [
            "watch",
            "--state-path",
            str(state_path),
            "--require-existing-state",
        ]
    ) == 1
    assert collections == 0
    assert not state_path.exists()


def test_watch_metrics_uses_snapshots_and_records_actual_delivery(
    monkeypatch,
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "watcher.json"
    metrics_path = tmp_path / "watch-metrics.jsonl"
    save_state(
        state_path,
        WatcherState(latest_id="900", seen_ids=("900",), initialized=True),
    )
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "secret.bot.token")
    monkeypatch.setenv("DISCORD_CHANNEL_ID", "123")
    post = make_post("901")
    observed_at = datetime(2026, 9, 22, 3, 0, tzinfo=UTC)
    snapshot = SourceSnapshot(
        source=SourceName.RESET,
        provider="codex-reset.com",
        endpoint="https://codex-reset.com/api/feed",
        request_started_at=observed_at - timedelta(seconds=2),
        response_received_at=observed_at - timedelta(seconds=1),
        observed_at=observed_at,
        posts=(post,),
        http_status=200,
        representation_hash="b" * 64,
        origin_time_bases=((post.id, "unknown"),),
    )
    monkeypatch.setattr(
        "help_me_tibooo.__main__.fetch_source_snapshots",
        lambda _client: iter((snapshot,)),
    )

    def reject_legacy_fetch(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("metrics watch가 legacy 수집 경로를 사용했습니다")

    monkeypatch.setattr(
        "help_me_tibooo.__main__.fetch_all_sources",
        reject_legacy_fetch,
    )
    sent: list[str] = []
    monkeypatch.setattr(
        "help_me_tibooo.__main__.DiscordBot.send",
        lambda _self, _payload: sent.append(post.id),
    )

    assert main(
        [
            "watch",
            "--state-path",
            str(state_path),
            "--metrics-path",
            str(metrics_path),
        ]
    ) == 0

    assert sent == [post.id]
    assert metrics_path.is_file()
    assert metrics_path.with_suffix(".observations.json").is_file()
    events = [
        json.loads(line)
        for line in metrics_path.read_text(encoding="utf-8").splitlines()
    ]
    deliveries = [event for event in events if event["event"] == "alert_delivery"]
    assert [event["outcome"] for event in deliveries] == ["attempted", "succeeded"]
    assert load_state(state_path).latest_id == post.id


def test_watch_saves_successful_delivery_when_post_send_metrics_logging_fails(
    monkeypatch,
    capsys,
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "watcher.json"
    metrics_path = tmp_path / "watch-metrics.jsonl"
    save_state(
        state_path,
        WatcherState(latest_id="900", seen_ids=("900",), initialized=True),
    )
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "secret.bot.token")
    monkeypatch.setenv("DISCORD_CHANNEL_ID", "123")
    post = make_post("901")
    observed_at = datetime(2026, 9, 22, 3, 0, tzinfo=UTC)
    snapshot = SourceSnapshot(
        source=SourceName.RESET,
        provider="codex-reset.com",
        endpoint="https://codex-reset.com/api/feed",
        request_started_at=observed_at,
        response_received_at=observed_at,
        observed_at=observed_at,
        posts=(post,),
        origin_time_bases=((post.id, "unknown"),),
    )
    monkeypatch.setattr(
        "help_me_tibooo.__main__.fetch_source_snapshots",
        lambda _client: iter((snapshot,)),
    )
    sent = 0

    def send_once(_self: object, _payload: object) -> None:
        nonlocal sent
        sent += 1

    monkeypatch.setattr("help_me_tibooo.__main__.DiscordBot.send", send_once)
    original_record_alert = DiagnosticRun.record_alert

    def fail_after_send(self, recorded_post, outcome, categories):
        if outcome == "succeeded":
            raise OSError("private telemetry path")
        return original_record_alert(self, recorded_post, outcome, categories)

    monkeypatch.setattr(
        "help_me_tibooo.__main__.DiagnosticRun.record_alert",
        fail_after_send,
    )

    assert main(
        [
            "watch",
            "--state-path",
            str(state_path),
            "--metrics-path",
            str(metrics_path),
        ]
    ) == 0
    assert sent == 1
    state = load_state(state_path)
    assert state is not None
    assert state.latest_id == post.id
    assert state.alert_delivery is None
    captured = capsys.readouterr()
    assert "진단 기록 실패 · 감시 결과는 계속 저장합니다" in captured.err
    assert "private telemetry path" not in captured.out + captured.err


def test_watch_metrics_records_actual_delivery_failure(
    monkeypatch,
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "watcher.json"
    metrics_path = tmp_path / "watch-metrics.jsonl"
    save_state(
        state_path,
        WatcherState(latest_id="900", seen_ids=("900",), initialized=True),
    )
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "secret.bot.token")
    monkeypatch.setenv("DISCORD_CHANNEL_ID", "123")
    post = make_post("901")
    observed_at = datetime(2026, 9, 22, 3, 0, tzinfo=UTC)
    snapshot = SourceSnapshot(
        source=SourceName.RESET,
        provider="codex-reset.com",
        endpoint="https://codex-reset.com/api/feed",
        request_started_at=observed_at,
        response_received_at=observed_at,
        observed_at=observed_at,
        posts=(post,),
        origin_time_bases=((post.id, "unknown"),),
    )
    monkeypatch.setattr(
        "help_me_tibooo.__main__.fetch_source_snapshots",
        lambda _client: iter((snapshot,)),
    )

    def fail_send(_self: object, _payload: object) -> None:
        raise RuntimeError("private Discord response")

    monkeypatch.setattr("help_me_tibooo.__main__.DiscordBot.send", fail_send)

    assert main(
        [
            "watch",
            "--state-path",
            str(state_path),
            "--metrics-path",
            str(metrics_path),
        ]
    ) == 1

    events = [
        json.loads(line)
        for line in metrics_path.read_text(encoding="utf-8").splitlines()
    ]
    deliveries = [event for event in events if event["event"] == "alert_delivery"]
    assert [event["outcome"] for event in deliveries] == ["attempted", "failed"]
    state = load_state(state_path)
    assert state is not None
    assert state.alert_delivery is not None
    assert state.alert_delivery.post_id == post.id
    assert "private Discord response" not in metrics_path.read_text(encoding="utf-8")


def test_watch_rejects_metrics_alias_before_collection_or_output(
    monkeypatch,
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "watcher.json"
    save_state(state_path, WatcherState(initialized=True))
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "secret.bot.token")
    monkeypatch.setenv("DISCORD_CHANNEL_ID", "123")
    collections = 0

    def count_collection(_client: object) -> tuple[SourceBatch, ...]:
        nonlocal collections
        collections += 1
        return ()

    monkeypatch.setattr(
        "help_me_tibooo.__main__.fetch_source_snapshots",
        count_collection,
    )

    assert main(
        [
            "watch",
            "--state-path",
            str(state_path),
            "--metrics-path",
            str(state_path.with_suffix(".tmp")),
        ]
    ) == 1
    assert collections == 0
    assert not state_path.with_suffix(".tmp").exists()
