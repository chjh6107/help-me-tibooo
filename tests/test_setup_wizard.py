import os
import subprocess
from pathlib import Path


def _run_wizard(
    tmp_path: Path,
    user_input: str,
    *,
    auth_exit: int = 0,
    secret_failures: int = 0,
) -> tuple[subprocess.CompletedProcess[str], Path, Path]:
    repository = Path(__file__).parents[1]
    script = repository / "scripts" / "setup-discord-bot.sh"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    calls = tmp_path / "calls.log"
    opened = tmp_path / "opened.log"

    fake_gh = fake_bin / "gh"
    fake_gh.write_text(
        """#!/bin/sh
printf '%s\n' "$*" >> "$GH_CALLS"
if [ "$1 $2" = "auth status" ]; then
  exit "$GH_AUTH_EXIT"
fi
if [ "$1 $2" = "secret set" ]; then
  value=$(cat)
  [ "$value" = "$EXPECTED_TOKEN" ] || exit 4
  attempts=0
  [ ! -f "$SECRET_ATTEMPTS" ] || attempts=$(cat "$SECRET_ATTEMPTS")
  attempts=$((attempts + 1))
  printf '%s' "$attempts" > "$SECRET_ATTEMPTS"
  [ "$attempts" -gt "$SECRET_FAILURES" ] || exit 5
fi
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
            "GH_AUTH_EXIT": str(auth_exit),
            "SECRET_ATTEMPTS": str(tmp_path / "secret-attempts"),
            "SECRET_FAILURES": str(secret_failures),
            "OPENED_URLS": str(opened),
            "ENV_FILE": str(tmp_path / ".env"),
        }
    )
    result = subprocess.run(
        ["bash", str(script)],
        cwd=repository,
        env=environment,
        input=user_input,
        capture_output=True,
        text=True,
        check=False,
    )
    return result, calls, opened


def test_setup_wizard_registers_bot_credentials_without_persisting_token(
    tmp_path: Path,
) -> None:
    result, calls, opened = _run_wizard(
        tmp_path,
        (
            "\n"
            "123456789012345678\n"
            "secret.bot.token\n"
            "\n"
            "234567890123456789\n"
            "n\n"
        ),
    )

    assert result.returncode == 0, result.stderr
    assert "secret.bot.token" not in result.stdout + result.stderr
    assert not (tmp_path / ".env").exists()
    assert calls.read_text(encoding="utf-8").splitlines() == [
        "auth status",
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
    for english_library_text in (
        "Setup complete",
        "Stage ",
        "You drive",
        "Ready to start",
        "opening",
        "still to do by hand",
    ):
        assert english_library_text not in result.stdout


def test_setup_wizard_stops_before_token_generation_when_github_is_not_ready(
    tmp_path: Path,
) -> None:
    result, calls, _ = _run_wizard(
        tmp_path,
        "\n123456789012345678\n",
        auth_exit=1,
    )

    assert result.returncode != 0
    assert calls.read_text(encoding="utf-8").splitlines() == ["auth status"]
    assert "Bot Token을 발급하기 전에" in result.stdout
    assert "Bot Token:" not in result.stdout


def test_setup_wizard_retries_failed_secret_write_without_disclosing_token(
    tmp_path: Path,
) -> None:
    result, calls, _ = _run_wizard(
        tmp_path,
        (
            "\n"
            "123456789012345678\n"
            "secret.bot.token\n"
            "y\n"
            "\n"
            "234567890123456789\n"
            "n\n"
        ),
        secret_failures=1,
    )

    assert result.returncode == 0, result.stderr
    assert calls.read_text(encoding="utf-8").splitlines().count(
        "secret set DISCORD_BOT_TOKEN"
    ) == 2
    assert "secret.bot.token" not in result.stdout + result.stderr
    assert "Secret 저장에 실패했습니다" in result.stdout
    assert not (tmp_path / ".env").exists()


def test_setup_wizard_reprompts_for_invalid_discord_ids(tmp_path: Path) -> None:
    result, _, _ = _run_wizard(
        tmp_path,
        (
            "\n"
            "not-an-id\n"
            "123456789012345678\n"
            "secret.bot.token\n"
            "\n"
            "123\n"
            "234567890123456789\n"
            "n\n"
        ),
    )

    assert result.returncode == 0, result.stderr
    assert "Application ID는 17~20자리 숫자여야 합니다." in result.stdout
    assert "Channel ID는 17~20자리 숫자여야 합니다." in result.stdout
