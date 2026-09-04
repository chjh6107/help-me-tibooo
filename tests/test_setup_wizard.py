import os
import subprocess
from pathlib import Path


def test_setup_wizard_registers_bot_credentials_without_persisting_token(
    tmp_path: Path,
) -> None:
    repository = Path(__file__).parents[1]
    script = repository / "scripts" / "setup-discord-bot.sh"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    calls = tmp_path / "calls.log"
    opened = tmp_path / "opened.log"

    fake_gh = fake_bin / "gh"
    fake_gh.write_text(
        """#!/bin/sh
if [ "$1 $2" = "auth status" ]; then
  exit 0
fi
if [ "$1 $2" = "secret set" ]; then
  value=$(cat)
  [ "$value" = "$EXPECTED_TOKEN" ] || exit 4
fi
printf '%s\n' "$*" >> "$GH_CALLS"
""",
        encoding="utf-8",
    )
    fake_gh.chmod(0o755)
    fake_open = fake_bin / "open"
    fake_open.write_text(
        """#!/bin/sh
printf '%s\n' "$1" >> "$OPENED_URLS"
""",
        encoding="utf-8",
    )
    fake_open.chmod(0o755)

    environment = os.environ.copy()
    environment.update(
        {
            "PATH": f"{fake_bin}:{environment['PATH']}",
            "EXPECTED_TOKEN": "secret.bot.token",
            "GH_CALLS": str(calls),
            "OPENED_URLS": str(opened),
            "ENV_FILE": str(tmp_path / ".env"),
        }
    )
    result = subprocess.run(
        ["bash", str(script)],
        cwd=repository,
        env=environment,
        input=(
            "\n"
            "123456789012345678\n"
            "secret.bot.token\n"
            "\n"
            "234567890123456789\n"
            "n\n"
        ),
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "secret.bot.token" not in result.stdout + result.stderr
    assert not (tmp_path / ".env").exists()
    assert calls.read_text(encoding="utf-8").splitlines() == [
        "secret set DISCORD_BOT_TOKEN",
        "variable set DISCORD_CHANNEL_ID --body 234567890123456789",
    ]
    assert opened.read_text(encoding="utf-8").splitlines() == [
        "https://discord.com/developers/applications",
        "https://discord.com/developers/applications/123456789012345678/bot",
        (
            "https://discord.com/oauth2/authorize?client_id=123456789012345678"
            "&permissions=3072&scope=bot"
        ),
        "https://github.com/chjh6107/help-me-tibooo/actions",
    ]

