from pathlib import Path


def test_manual_smoke_step_does_not_receive_discord_credentials() -> None:
    workflow = (Path(__file__).parents[1] / ".github" / "workflows" / "watch.yml").read_text(
        encoding="utf-8"
    )

    smoke_step = workflow.split("- name: 공개 소스 smoke", maxsplit=1)[1].split(
        "- name:", maxsplit=1
    )[0]

    assert "DISCORD_BOT_TOKEN" not in smoke_step
    assert "DISCORD_CHANNEL_ID" not in smoke_step


def test_watch_and_test_bot_receive_minimum_discord_credentials() -> None:
    workflow = (Path(__file__).parents[1] / ".github" / "workflows" / "watch.yml").read_text(
        encoding="utf-8"
    )
    watch_step = workflow.split("- name: 감시 실행", maxsplit=1)[1].split(
        "- name:", maxsplit=1
    )[0]
    test_step = workflow.split("- name: Discord 봇 테스트", maxsplit=1)[1].split(
        "- name:", maxsplit=1
    )[0]

    for step in (watch_step, test_step):
        assert "DISCORD_BOT_TOKEN: ${{ secrets.DISCORD_BOT_TOKEN }}" in step
        assert "DISCORD_CHANNEL_ID: ${{ vars.DISCORD_CHANNEL_ID }}" in step
    assert "test-discord" not in workflow
    assert "test-bot" in workflow
