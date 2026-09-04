import json
from pathlib import Path

import pytest

from help_me_tibooo.models import Post, SourceName


@pytest.fixture
def load_json_fixture():
    return lambda name: json.loads((Path(__file__).parent / "fixtures" / name).read_text())


@pytest.fixture
def load_text_fixture():
    return lambda name: (Path(__file__).parent / "fixtures" / name).read_text()


@pytest.fixture
def make_post():
    return lambda **changes: Post(
        id=changes.pop("id", "999"),
        text=changes.pop("text", ""),
        created_at=changes.pop("created_at", None),
        url=changes.pop("url", "https://x.com/thsottiaux/status/999"),
        source=changes.pop("source", SourceName.RESET),
        **changes,
    )
