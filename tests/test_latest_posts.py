import httpx
import pytest

from help_me_tibooo.classifier import classify
from help_me_tibooo.models import AlertCategory, CheckpointPosition, SourceCheckpoint, SourceName, WatcherState
from help_me_tibooo.sources import fetch_all_sources
from help_me_tibooo.watcher import run_watcher


@pytest.fixture
def latest_html():
    return '''<ul id="feed-list">
    <li class="feed-item" data-kind="context"><a class="feed-time" href="https://x.com/thsottiaux/status/2100363668051603608">3h ago</a><p class="feed-text">Sometimes physics can't be cheated</p></li>
    <li class="feed-item" data-kind="context"><a class="feed-time" href="https://x.com/thsottiaux/status/2100297380968997327">8h ago</a><p class="feed-text">Astra<br>✅ Fast<br>✅ Frontier<br>✅ Efficient<br>✅ For everyone</p></li>
    </ul>'''


def test_live_timeline_fills_posts_missing_from_json_and_delivers_once(latest_html):
    def handler(request):
        if request.url.path == "/tibo":
            return httpx.Response(200, text=latest_html)
        if request.url.path == "/api/feed":
            return httpx.Response(200, json={"tweets": []})
        return httpx.Response(503)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        batches = fetch_all_sources(client)
    posts = batches[0].posts
    assert {p.id for p in posts} == {"2100363668051603608", "2100297380968997327"}
    state = WatcherState(initialized=True, source_checkpoints=(
        SourceCheckpoint(SourceName.RESET, CheckpointPosition(id="2099886370319978506")),
    ))
    delivered = []
    state = run_watcher(batches, state, lambda post, cats: delivered.append((post.id, cats)), lambda _: None)
    run_watcher(batches, state, lambda post, cats: delivered.append((post.id, cats)), lambda _: None)
    assert delivered == [("2100297380968997327", (AlertCategory.NEWS,))]


@pytest.mark.parametrize("text", ["Astra ✅ Fast ✅ Frontier ✅ Efficient ✅ For everyone", "What is ChatGPT", "OpenAI is improving reliability.", "Codex availability is improving."])
def test_related_posts_do_not_need_release_keywords(make_post, text):
    assert classify(make_post(text=text)) == (AlertCategory.NEWS,)


@pytest.mark.parametrize("text", ["Sometimes physics can't be cheated", "11pm on a Tuesday, big startup energy", "An astronaut saw the stars"])
def test_unrelated_posts_are_excluded(make_post, text):
    assert classify(make_post(text=text)) == ()


def test_latest_page_must_have_valid_author_and_posts(latest_html):
    from help_me_tibooo.sources import parse_tibo_html

    with pytest.raises(ValueError):
        parse_tibo_html(latest_html.replace("/thsottiaux/", "/someone_else/"))
    with pytest.raises(ValueError):
        parse_tibo_html('<ul id="feed-list"></ul>')
