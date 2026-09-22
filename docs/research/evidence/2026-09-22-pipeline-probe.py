"""Read-only offline reproduction for deployed revision 0e9dfca; never sends Discord."""
from datetime import UTC, datetime
import httpx
from help_me_tibooo.classifier import classify
from help_me_tibooo.models import CheckpointPosition, Post, SourceBatch, SourceCheckpoint, WatcherState
from help_me_tibooo.sources import fetch_all_sources
from help_me_tibooo.watcher import run_watcher


def post(i, text, kind=None, source='reset'):
    return Post(str(i), text, datetime(2026, 9, 21, tzinfo=UTC),
                f'https://x.com/thsottiaux/status/{i}', source, source_kind=kind)


for name, text, kind in [
    ('keyword_only', '@melvindvivas 👁️codex👁️', None),
    ('context_only_teaser', "We'll have some things next week already, with the keynote in two weeks", None),
    ('limits_chat', 'You main Sol? And out of curiosity, you never buy credits?', 'limits'),
    ('limits_plan', 'We are going to pause subscriptions to our $200 Pro plan.', 'limits'),
    ('substring_ship', 'Our Codex partnership continues.', None),
]:
    print('CLASSIFY', name, [str(x) for x in classify(post(101, text, kind))])

state = WatcherState(initialized=True, source_checkpoints=(SourceCheckpoint('reset', CheckpointPosition('100')),))
a = []
state = run_watcher((SourceBatch('reset', (post(101, 'A quiet day.'),)),), state, lambda p,c: a.append(p.id), lambda _: None)
b = []
state = run_watcher((SourceBatch('reset', (post(101, 'Codex usage reset is tonight.'),)),), state, lambda p,c: b.append(p.id), lambda _: None)
print('REENRICH', a, b, state.source_checkpoints[0].position.id)

state = WatcherState(initialized=True, source_checkpoints=(SourceCheckpoint('twiscan', CheckpointPosition('100')),))
a = []
state = run_watcher((SourceBatch('twiscan', tuple(post(i, 'Codex launch', source='twiscan') for i in range(103,108))),), state, lambda p,c: a.append(p.id), lambda _: None)
b = []
state = run_watcher((SourceBatch('twiscan', tuple(post(i, 'Codex launch', source='twiscan') for i in (101,102))),), state, lambda p,c: b.append(p.id), lambda _: None)
print('WINDOW_GAP', a, b, state.source_checkpoints[0].position.id)

html = '<ul id="feed-list"><li class="feed-item" data-kind="limits"><a class="feed-time" href="https://x.com/thsottiaux/status/201">now</a><p class="feed-text">New capacity details.</p></li></ul>'


def handler(request):
    if request.url.path == '/api/feed':
        return httpx.Response(200, json={'tweets': [{'id':'201','text':'New capacity details.','at':'2026-09-21T00:00:00Z','url':'https://x.com/thsottiaux/status/201'}]})
    if request.url.path == '/tibo':
        return httpx.Response(200, text=html)
    if request.url.host == 'twiscan.com':
        return httpx.Response(200, text='<div id="timeline"></div>')
    return httpx.Response(200, json={'data':[{'id':'300','reset_type':'regular','announced_at':'2026-09-21T00:00:00Z','text':'done','source':{'type':'x_post','author':'thsottiaux','url':'https://x.com/thsottiaux/status/300'}}],'pagination':{'has_more':False}})


with httpx.Client(transport=httpx.MockTransport(handler)) as client:
    merged = fetch_all_sources(client)[0].posts[0]
print('MERGE_COLLISION', merged.source_kind, [str(x) for x in classify(merged)])
a = []
s = run_watcher((SourceBatch('reset', (post(101, 'Codex launch'),)),), None, lambda p,c: a.append(p.id), lambda _: None)
print('BOOTSTRAP', a, s.initialized, s.source_checkpoints[0].position.id)
