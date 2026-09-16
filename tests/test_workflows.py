from pathlib import Path

import yaml


def _workflow_steps() -> dict[str, dict[str, object]]:
    workflow_path = Path(__file__).parents[1] / ".github" / "workflows" / "watch.yml"
    workflow = yaml.load(workflow_path.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    return {
        step["name"]: step
        for step in workflow["jobs"]["run"]["steps"]
        if "name" in step
    }


def test_manual_smoke_step_does_not_receive_discord_credentials() -> None:
    smoke_step = _workflow_steps()["공개 소스 smoke"]

    assert "env" not in smoke_step
    assert smoke_step["run"] == "python -m help_me_tibooo smoke"


def test_watch_and_test_bot_receive_minimum_discord_credentials() -> None:
    steps = _workflow_steps()

    for name in ("감시 실행", "Discord 봇 테스트"):
        assert steps[name]["env"] == {
            "DISCORD_BOT_TOKEN": "${{ secrets.DISCORD_BOT_TOKEN }}",
            "DISCORD_CHANNEL_ID": "${{ vars.DISCORD_CHANNEL_ID }}",
        }
    assert steps["감시 실행"]["run"] == (
        "python -m help_me_tibooo watch --state-path .state/watcher.json"
    )
    assert steps["Discord 봇 테스트"]["run"] == "python -m help_me_tibooo test-bot"
