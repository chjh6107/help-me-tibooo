from html import escape

import pytest

from help_me_tibooo.models import AlertCategory, SourceBatch, SourceName
from help_me_tibooo.sources import parse_reset_feed, parse_tibo_html, parse_twiscan_html
from help_me_tibooo.watcher import run_watcher


def test_feed_reset_hint_and_timeline_devday_reach_delivery_once(make_post) -> None:
    alerts = []
    send = lambda post, categories: alerts.append((post.id, categories))
    baseline = make_post(id="2103911959544610829", text="Baseline")
    state = run_watcher(
        (SourceBatch(SourceName.RESET, (baseline,)),), None, send, lambda _: None,
    )
    hint = parse_reset_feed({"tweets": [{
        "id": "2103963215885701493",
        "text": "Sorry Gia. More resets coming next week",
        "at": "2026-09-26T21:41:35Z",
        "url": "https://x.com/thsottiaux/status/2103963215885701493",
        "kind": "signal",
    }]})
    devday = parse_tibo_html('''
        <div id="feed-list"><div class="feed-item" data-kind="post">
          <a class="feed-time" href="https://x.com/thsottiaux/status/2104462713296683467">time</a>
          <div class="feed-text">@mark_k DevDay</div>
        </div></div>
    ''')
    batches = (SourceBatch(SourceName.RESET, devday + hint),)

    state = run_watcher(batches, state, send, lambda _: None)
    run_watcher(batches, state, send, lambda _: None)

    assert alerts == [
        ("2103963215885701493", (AlertCategory.RESET,)),
        ("2104462713296683467", (AlertCategory.NEWS,)),
    ]


@pytest.mark.parametrize("provider", ("feed", "tibo", "twiscan"))
def test_conversational_posts_are_handled_without_delivery(make_post, provider) -> None:
    alerts = []
    send = lambda post, categories: alerts.append((post.id, categories, post.text))
    source = SourceName.TWISCAN if provider == "twiscan" else SourceName.RESET
    state = run_watcher(
        (SourceBatch(source, (make_post(id="2105489877727064271", source=source),)),),
        None, send, lambda _: None,
    )
    originals = (
        ("2105489877727064272", "@_bgian @OpenAI Thanks for playing"),
        ("2105519215092584786", "ChatGPT can now build and deploy MCP servers, and restrict their access."),
        ("2105519686280790252", "@imjustnewatai For the Pro 200 shenanigans"),
    )
    if provider == "feed":
        posts = parse_reset_feed({"tweets": [
            {"id": post_id, "text": text, "at": "2026-10-01T00:00:00Z", "url": f"https://x.com/thsottiaux/status/{post_id}"}
            for post_id, text in originals
        ]})
    elif provider == "tibo":
        posts = parse_tibo_html('<div id="feed-list">' + "".join(
            f'<div class="feed-item" data-kind="post"><a class="feed-time" href="https://x.com/thsottiaux/status/{post_id}">time</a><div class="feed-text">{escape(text)}</div></div>'
            for post_id, text in originals
        ) + '</div>')
    else:
        posts = parse_twiscan_html("".join(
            f'<div id="clamp-{post_id}-0">{escape(text)}</div>'
            for post_id, text in originals
        ))
    batches = (SourceBatch(source, posts),)

    state = run_watcher(batches, state, send, lambda _: None)
    state = run_watcher(batches, state, send, lambda _: None)

    assert alerts == [(originals[1][0], (AlertCategory.NEWS,), originals[1][1])]
    assert set(post_id for post_id, _ in originals) <= set(state.seen_ids)
    checkpoint = next(item for item in state.source_checkpoints if item.source == source)
    assert checkpoint.position.id == originals[-1][0]
