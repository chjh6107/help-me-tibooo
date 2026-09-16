from datetime import UTC, datetime, timedelta

import httpx
import pytest

from help_me_tibooo.classifier import classify
from help_me_tibooo.models import AlertCategory, SourceBatch, WatcherState
from help_me_tibooo.sources import fetch_all_sources
from help_me_tibooo.state import load_state, save_state
from help_me_tibooo.watcher import run_watcher
from help_me_tibooo.__main__ import main


def response_data(items, more=False, cursor=None):
    return {"data": items, "pagination": {"has_more": more, "next_cursor": cursor},
            "meta": {"api_version": "v1", "generated_at": datetime.now(UTC).isoformat()}}


def reset_record(post_id="2098685367058612394", text="Hi. It is done."):
    return {"id": post_id, "reset_type": "regular", "announced_at": "2026-09-12T08:09:17Z",
            "text": text, "source": {"type": "x_post", "author": "thsottiaux",
            "url": f"https://x.com/thsottiaux/status/{post_id}"}}


def test_public_api_collects_paginated_confirmed_resets_despite_old_sources_403():
    def handler(request):
        if request.url.host != "codex-resets.com":
            return httpx.Response(403)
        assert request.url.path == "/api/v1/resets"
        assert request.url.params["limit"] == "100"
        if "cursor" not in request.url.params:
            return httpx.Response(200, json=response_data([reset_record()], True, "page2"))
        assert request.url.params["cursor"] == "page2"
        return httpx.Response(200, json=response_data([reset_record("2098685367058612393")]))

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        batches = fetch_all_sources(client)
    public = next(batch for batch in batches if str(batch.source) == "resets")
    assert public.error is None
    assert [post.id for post in public.posts] == ["2098685367058612394", "2098685367058612393"]
    assert classify(public.posts[0]) == (AlertCategory.RESET,)
    assert all(batch.error == "HTTP status 403" for batch in batches if batch is not public)


def test_partial_reset_recovery_does_not_claim_full_recovery_or_repeat_outage(tmp_path):
    def handler(request):
        return httpx.Response(200, json=response_data([reset_record()])) if request.url.host == "codex-resets.com" else httpx.Response(403)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        batches = fetch_all_sources(client)
    now = datetime(2026, 9, 16, tzinfo=UTC)
    state = WatcherState(consecutive_failures=99, outage_notified=True)
    sent, recovered = [], []
    state = run_watcher(batches, state, lambda *_: None, sent.append,
                        send_recovery=lambda: recovered.append(True), now=now)
    assert recovered == []
    assert state.consecutive_failures == 100
    path = tmp_path / "state.json"
    save_state(path, state)
    for days in range(1, 5):
        state = run_watcher(batches, load_state(path), lambda *_: None, sent.append,
                            send_recovery=lambda: recovered.append(True), now=now + timedelta(days=days))
        save_state(path, state)
    assert sent == [100]
    assert recovered == []


def test_same_total_outage_does_not_repeat_after_six_hours_but_changed_cause_alerts():
    now = datetime(2026, 9, 16, tzinfo=UTC)
    sent = []
    failed = (SourceBatch("reset", error="HTTP status 403"), SourceBatch("twiscan", error="HTTP status 403"))
    state = run_watcher(failed, WatcherState(consecutive_failures=2), lambda *_: None, sent.append, now=now)
    state = run_watcher(failed, state, lambda *_: None, sent.append, now=now + timedelta(days=2))
    assert sent == [3]
    changed = (SourceBatch("reset", error="request timed out"), SourceBatch("twiscan", error="HTTP status 403"))
    run_watcher(changed, state, lambda *_: None, sent.append, now=now + timedelta(days=3))
    assert sent == [3, 5]


def test_smoke_partial_collection_is_failure_without_discord(monkeypatch):
    def handler(request):
        return httpx.Response(200, json=response_data([reset_record()])) if request.url.host == "codex-resets.com" else httpx.Response(403)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        batches = fetch_all_sources(client)
    monkeypatch.setattr("help_me_tibooo.__main__.fetch_all_sources", lambda _: batches)
    assert main(["smoke"]) == 1


def test_observed_reset_uses_real_source_url_id_not_observed_suffix():
    record = reset_record("observed-2097043464538264003", "All reset for everyone.")
    record["source"] = {"type": "observed", "url": "https://x.com/thsottiaux/status/2097174560412246215"}
    def handler(request):
        return httpx.Response(200, json=response_data([record])) if request.url.host == "codex-resets.com" else httpx.Response(403)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        batch = fetch_all_sources(client)[2]
    assert batch.error is None
    assert batch.posts[0].id == "2097174560412246215"
    assert batch.posts[0].url == "https://x.com/thsottiaux/status/2097174560412246215"


def test_failed_second_page_discards_first_page_to_prevent_checkpoint_gap():
    def handler(request):
        if request.url.host != "codex-resets.com" or "cursor" in request.url.params:
            return httpx.Response(503)
        return httpx.Response(200, json=response_data([reset_record()], True, "page2"))
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        batch = fetch_all_sources(client)[2]
    assert batch.error == "HTTP status 503"
    assert batch.posts == ()


def test_smoke_resets_scope_succeeds_with_partial_coverage(monkeypatch):
    def handler(request):
        return httpx.Response(200, json=response_data([reset_record()])) if request.url.host == "codex-resets.com" else httpx.Response(403)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        batches = fetch_all_sources(client)
    monkeypatch.setattr("help_me_tibooo.__main__.fetch_all_sources", lambda _: batches)
    assert main(["smoke", "--scope", "resets"]) == 0


def test_public_classification_wins_over_same_unclassified_timeline_post():
    from help_me_tibooo.models import Post
    timeline = Post("2098685367058612394", "Hi. It is done.", None,
                    "https://x.com/thsottiaux/status/2098685367058612394", "reset")
    def handler(request):
        return httpx.Response(200, json=response_data([reset_record()])) if request.url.host == "codex-resets.com" else httpx.Response(403)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        public = fetch_all_sources(client)[2]
    state = WatcherState(latest_id="1", initialized=True, seen_ids=("1",))
    sent = []
    run_watcher((SourceBatch("reset", (timeline,)), public), state,
                lambda post, categories: sent.append((post.id, categories)), lambda _: None)
    assert sent == [("2098685367058612394", (AlertCategory.RESET,))]


def test_delayed_confirmation_of_previously_seen_older_post_is_delivered_once(tmp_path):
    from help_me_tibooo.models import CheckpointPosition, Post, SourceCheckpoint
    post = Post("100", "Hi. It is done.", datetime(2026, 9, 10, tzinfo=UTC),
                "https://x.com/thsottiaux/status/100", "resets")
    state = WatcherState(initialized=True, latest_id="200", seen_ids=("100", "200"),
                         source_checkpoints=(SourceCheckpoint("resets", CheckpointPosition("200")),))
    sent = []
    for _ in range(2):
        state = run_watcher((SourceBatch("resets", (post,)),), state,
                            lambda post, categories: sent.append((post.id, categories)), lambda _: None)
        path = tmp_path / "state.json"
        save_state(path, state)
        state = load_state(path)
    assert sent == [("100", (AlertCategory.RESET,))]


def test_public_opaque_and_numeric_records_are_delivered_in_announcement_order():
    from help_me_tibooo.models import CheckpointPosition, Post, SourceCheckpoint
    old = Post("observed-early", "confirmed", datetime(2026, 9, 2, tzinfo=UTC), "https://codex-resets.com/", "resets")
    new = Post("3", "confirmed", datetime(2026, 9, 3, tzinfo=UTC), "https://x.com/thsottiaux/status/3", "resets")
    state = WatcherState(initialized=True, source_checkpoints=(SourceCheckpoint("resets", CheckpointPosition("1")),))
    sent = []
    run_watcher((SourceBatch("resets", (new, old)),), state, lambda post, _: sent.append(post.id), lambda _: None)
    assert sent == ["observed-early", "3"]


def test_url_less_observed_numeric_id_is_not_accepted_as_x_evidence():
    record = reset_record("123")
    record["source"] = {"type": "observed"}
    def handler(request):
        return httpx.Response(200, json=response_data([record])) if request.url.host == "codex-resets.com" else httpx.Response(403)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        batch = fetch_all_sources(client)[2]
    assert batch.error == "invalid response"


@pytest.mark.parametrize("field", ["reset_type", "source_type"])
def test_malformed_public_enum_is_isolated_not_an_unhandled_exception(field):
    record = reset_record()
    if field == "reset_type":
        record["reset_type"] = []
    else:
        record["source"]["type"] = []
    def handler(request):
        return httpx.Response(200, json=response_data([record])) if request.url.host == "codex-resets.com" else httpx.Response(403)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        batch = fetch_all_sources(client)[2]
    assert batch.error == "invalid response"


def test_watch_partial_outage_saves_state_returns_failure_and_sends_one_notice(monkeypatch, tmp_path):
    def handler(request):
        return httpx.Response(200, json=response_data([reset_record()])) if request.url.host == "codex-resets.com" else httpx.Response(403)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        batches = fetch_all_sources(client)
    monkeypatch.setattr("help_me_tibooo.__main__.fetch_all_sources", lambda _: batches)
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "test-token")
    monkeypatch.setenv("DISCORD_CHANNEL_ID", "123")
    sent = []
    monkeypatch.setattr("help_me_tibooo.__main__.DiscordBot.send", lambda _, payload: sent.append(payload))
    path = tmp_path / "state.json"
    save_state(path, WatcherState(consecutive_failures=99, outage_notified=True))
    assert main(["watch", "--state-path", str(path)]) == 1
    assert load_state(path).consecutive_failures == 100
    assert "전체 Tibo 소식 감시는 사용할 수 없습니다" in sent[0]["embeds"][0]["description"]
    assert "resets: 정상 응답" in sent[0]["embeds"][0]["description"]
    assert main(["watch", "--state-path", str(path)]) == 1
    assert len(sent) == 1


def test_empty_public_history_is_not_reported_as_healthy(monkeypatch):
    def handler(request):
        return httpx.Response(200, json=response_data([])) if request.url.host == "codex-resets.com" else httpx.Response(403)
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        batches = fetch_all_sources(client)
    public = batches[2]
    assert public.error == "invalid response"
    monkeypatch.setattr("help_me_tibooo.__main__.fetch_all_sources", lambda _: batches)
    assert main(["smoke", "--scope", "resets"]) == 1


@pytest.mark.parametrize("legacy_checkpoint", [True, False])
def test_first_public_collection_baselines_legacy_state_without_historical_flood(legacy_checkpoint):
    from help_me_tibooo.models import CheckpointPosition, Post, SourceCheckpoint
    old = Post("100", "confirmed", datetime(2026, 9, 2, tzinfo=UTC), "https://x.com/thsottiaux/status/100", "resets")
    checkpoints = (SourceCheckpoint("*", CheckpointPosition("999")),) if legacy_checkpoint else ()
    state = WatcherState(initialized=True, latest_id="999", source_checkpoints=checkpoints)
    sent = []
    state = run_watcher((SourceBatch("resets", (old,)),), state, lambda post, _: sent.append(post.id), lambda _: None)
    assert sent == []
    assert state.handled_reset_ids == ("100",)
    assert any(checkpoint.source == "resets" for checkpoint in state.source_checkpoints)


def test_public_announcement_order_survives_overlap_with_timeline():
    from help_me_tibooo.models import CheckpointPosition, Post, SourceCheckpoint
    old = Post("observed-early", "confirmed", datetime(2026, 9, 2, tzinfo=UTC), "https://codex-resets.com/", "resets")
    new = Post("3", "confirmed", datetime(2026, 9, 3, tzinfo=UTC), "https://x.com/thsottiaux/status/3", "resets")
    timeline = Post("3", "quiet day", None, "https://x.com/thsottiaux/status/3", "reset")
    state = WatcherState(initialized=True, source_checkpoints=(SourceCheckpoint("resets", CheckpointPosition("1")), SourceCheckpoint("reset", CheckpointPosition("1"))))
    sent = []
    run_watcher((SourceBatch("reset", (timeline,)), SourceBatch("resets", (new, old))), state, lambda post, _: sent.append(post.id), lambda _: None)
    assert sent == ["observed-early", "3"]
