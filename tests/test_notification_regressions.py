from help_me_tibooo.models import AlertCategory, SourceBatch, SourceName
from help_me_tibooo.sources import parse_reset_feed, parse_tibo_html
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
