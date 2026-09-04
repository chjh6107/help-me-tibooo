from pathlib import Path


def test_manual_smoke_step_does_not_receive_discord_secret() -> None:
    workflow = (Path(__file__).parents[1] / ".github" / "workflows" / "watch.yml").read_text(
        encoding="utf-8"
    )

    smoke_step = workflow.split("- name: 공개 소스 smoke", maxsplit=1)[1].split(
        "- name:", maxsplit=1
    )[0]

    assert "DISCORD_WEBHOOK_URL" not in smoke_step
