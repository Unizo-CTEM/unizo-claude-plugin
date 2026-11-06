"""Named environments: file parsing, how the active one replaces plugin options, and the switch command."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from unizo_ctem_mcp import environments as envs
from unizo_ctem_mcp.config import Settings

REPO_ROOT = Path(__file__).resolve().parents[2]

STAGING = {
    "description": "Acme staging",
    "api_url": "https://ctem-staging.acme.com",
    "sso_issuer": "https://acme.okta.com/oauth2/default",
    "sso_client_id": "0oa-staging",
    "remote_mcp": {"url": "https://ctem-staging.acme.com/mcp", "client_id": "mcp-staging", "callback_port": 3118},
}
PROD = {
    "api_url": "https://ctem.acme.com",
    "sso_issuer": "https://login.example.com",
    "sso_client_id": "prod-client",
    "remote_mcp": {"url": "https://ctem.acme.com/mcp", "client_id": "mcp-prod"},
}


def write(path: Path, environments: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"environments": environments}))
    return path


@pytest.fixture
def user_file(isolated_config: Path) -> Path:
    return write(isolated_config / "config" / "unizo-ctem-mcp" / "environments.json", {"staging": STAGING, "prod": PROD})


class FakeClaude:
    """Stands in for the `claude` CLI and remembers the user-scope MCP servers."""

    def __init__(self, servers: dict | None = None) -> None:
        self.servers: dict[str, dict] = dict(servers or {})
        self.calls: list[list[str]] = []

    def __call__(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        self.calls.append(args)
        sub, name = args[2], args[-1] if args[2] != "add-json" else args[-2]
        if sub == "get":
            if name in self.servers:
                return subprocess.CompletedProcess(args, 0, f"{name}:\n  Scope: User config\n", "")
            return subprocess.CompletedProcess(args, 1, "", f"No MCP server found with name: {name}")
        if sub == "remove":
            self.servers.pop(name, None)
        elif sub == "add-json":
            self.servers[name] = json.loads(args[-1])
        return subprocess.CompletedProcess(args, 0, "ok", "")

    def subcommands(self) -> list[str]:
        return [c[2] for c in self.calls]


# ── Parsing ──


def test_bundled_environments_file_is_valid() -> None:
    found = envs.parse_file(REPO_ROOT / "environments.json")
    demo = found["demo"]
    assert demo.remote and demo.remote.url == "https://demo.unizo.ai/mcp" and demo.remote.client_id
    assert envs.parse_file(REPO_ROOT / "environments.example.json")["ci"].remote is None


def test_user_file_overrides_bundled_entry(isolated_config: Path, user_file: Path) -> None:
    write(isolated_config / "plugin" / "environments.json", {"staging": PROD, "demo": PROD})
    found = envs.load_environments()
    assert sorted(found) == ["demo", "prod", "staging"]
    assert found["staging"].settings["api_url"] == STAGING["api_url"]
    assert found["staging"].source == user_file


def test_custom_file_location(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    custom = write(tmp_path / "team" / "unizo-ctem-envs.json", {"qa": PROD})
    monkeypatch.setenv("UNIZO_CTEM_ENVIRONMENTS_FILE", str(custom))
    assert list(envs.load_environments()) == ["qa"]


@pytest.mark.parametrize(
    ("environment", "message"),
    [
        ({"api_url": "https://x", "api_token": "s3cret"}, "Secrets don't belong"),
        ({"api_url": "https://x", "cloud_url": "https://x"}, "unknown key(s) cloud_url"),
        ({"remote_mcp": {"url": "http://ctem.acme.com/mcp"}}, "must start with https://"),
        ({"remote_mcp": {"client_id": "x"}}, "url is required"),
        ({"remote_mcp": {"url": "https://x/mcp", "clientId": "x"}}, "unknown key(s) clientId"),
        ({"remote_mcp": {"url": "https://x/mcp", "callback_port": "3118"}}, "callback_port must be"),
        ({"use_plugin_secrets": "yes"}, "use_plugin_secrets must be"),
    ],
)
def test_invalid_environments_are_rejected(tmp_path: Path, environment: dict, message: str) -> None:
    path = write(tmp_path / "e.json", {"bad": environment})
    with pytest.raises(envs.EnvConfigError, match=message.replace("(", r"\(").replace(")", r"\)")):
        envs.parse_file(path)


def test_remote_server_config_for_claude() -> None:
    remote = envs.RemoteMcp("https://x/mcp", "cid", 3118, "openid email")
    assert remote.server_config() == {
        "type": "http",
        "url": "https://x/mcp",
        "oauth": {"clientId": "cid", "callbackPort": 3118, "scopes": "openid email"},
    }
    assert envs.RemoteMcp("https://x/mcp").server_config() == {"type": "http", "url": "https://x/mcp"}


# ── The active environment replaces the plugin options ──


def plugin_options(monkeypatch: pytest.MonkeyPatch) -> None:
    """Values a user set earlier with /plugin configure, for some other deployment."""
    for var, value in {
        "UNIZO_CTEM_API_URL": "https://old.example.com",
        "UNIZO_CTEM_API_TOKEN": "old-token",
        "UNIZO_CTEM_OIDC_ISSUER": "https://old-idp.example.com",
        "UNIZO_CTEM_OIDC_CLIENT_ID": "old-client",
        "UNIZO_CTEM_OIDC_AUDIENCE": "old-audience",
        "UNIZO_CTEM_OIDC_REDIRECT_PORT": "9999",
    }.items():
        monkeypatch.setenv(var, value)


def test_plugin_options_apply_when_no_environment_is_active(monkeypatch: pytest.MonkeyPatch) -> None:
    plugin_options(monkeypatch)
    s = Settings.from_env()
    assert s.environment == "" and s.api_url == "https://old.example.com" and s.auth_mode == "static-token"


def test_active_environment_replaces_every_plugin_option(
    monkeypatch: pytest.MonkeyPatch, user_file: Path
) -> None:
    plugin_options(monkeypatch)
    envs.use("staging", run=FakeClaude(), out=lambda _: None)
    s = Settings.from_env()
    assert s.environment == "staging" and s.environment_source == str(user_file)
    assert s.api_url == "https://ctem-staging.acme.com"
    assert s.oidc.issuer == STAGING["sso_issuer"] and s.oidc.client_id == "0oa-staging"
    # Nothing carries over from the old options: unset keys fall back to defaults, and the token isn't sent.
    assert s.api_token == "" and s.auth_mode == "sso"
    assert s.oidc.audience == "" and s.oidc.redirect_port == 8765


def test_plugin_secrets_only_when_the_environment_opts_in(
    monkeypatch: pytest.MonkeyPatch, isolated_config: Path
) -> None:
    plugin_options(monkeypatch)
    write(isolated_config / "config" / "unizo-ctem-mcp" / "environments.json",
          {"ci": {"api_url": "https://ctem.acme.com", "use_plugin_secrets": True}})
    envs.use("ci", run=FakeClaude(), out=lambda _: None)
    s = Settings.from_env()
    assert s.api_token == "old-token" and s.auth_mode == "static-token"


def test_missing_active_environment_is_reported_not_fatal(
    monkeypatch: pytest.MonkeyPatch, user_file: Path
) -> None:
    plugin_options(monkeypatch)
    envs.use("prod", run=FakeClaude(), out=lambda _: None)
    write(user_file, {"staging": STAGING})  # prod deleted from the file
    s = Settings.from_env()
    assert s.environment == "" and s.api_url == "https://old.example.com"
    assert any('"prod" is no longer' in p for p in s.problems)


# ── Switching ──


def test_use_registers_the_remote_server_with_its_client_id(user_file: Path) -> None:
    claude = FakeClaude()
    envs.use("staging", run=claude, out=lambda _: None)
    assert claude.servers["unizo-ctem-cloud"] == {
        "type": "http",
        "url": "https://ctem-staging.acme.com/mcp",
        "oauth": {"clientId": "mcp-staging", "callbackPort": 3118},
    }
    assert ["claude", "mcp", "add-json", "--scope", "user", "unizo-ctem-cloud"] == claude.calls[-1][:6]
    assert envs.read_state()["name"] == "staging"


def test_switching_signs_out_the_old_remote_and_replaces_it(user_file: Path) -> None:
    claude = FakeClaude()
    envs.use("staging", run=claude, out=lambda _: None)
    claude.calls.clear()
    envs.use("prod", run=claude, out=lambda _: None)
    assert claude.subcommands() == ["get", "logout", "remove", "add-json"]
    assert claude.servers["unizo-ctem-cloud"]["oauth"] == {"clientId": "mcp-prod"}


def test_reapplying_the_same_environment_keeps_the_remote_sign_in(user_file: Path) -> None:
    claude = FakeClaude()
    envs.use("staging", run=claude, out=lambda _: None)
    claude.calls.clear()
    envs.use("staging", run=claude, out=lambda _: None)
    assert "logout" not in claude.subcommands()


def test_environment_without_remote_removes_it(isolated_config: Path, user_file: Path) -> None:
    claude = FakeClaude()
    envs.use("staging", run=claude, out=lambda _: None)
    write(user_file, {"staging": STAGING, "local": {"api_url": "http://127.0.0.1:9401"}})
    envs.use("local", run=claude, out=lambda _: None)
    assert "unizo-ctem-cloud" not in claude.servers
    assert envs.read_state()["remote_registered"] is False


def test_wont_replace_a_server_it_did_not_add(user_file: Path) -> None:
    claude = FakeClaude({"unizo-ctem-cloud": {"type": "http", "url": "https://someone-elses/mcp"}})
    with pytest.raises(envs.EnvConfigError, match="already exists"):
        envs.use("staging", run=claude, out=lambda _: None)
    assert claude.servers["unizo-ctem-cloud"]["url"] == "https://someone-elses/mcp"
    envs.use("staging", force=True, run=claude, out=lambda _: None)
    assert claude.servers["unizo-ctem-cloud"]["url"] == "https://ctem-staging.acme.com/mcp"


def test_unknown_environment(user_file: Path) -> None:
    with pytest.raises(envs.EnvConfigError, match="Available: prod, staging"):
        envs.use("qa", run=FakeClaude(), out=lambda _: None)
    assert envs.read_state() is None


def test_add_failure_is_reported_and_state_unchanged(user_file: Path) -> None:
    def failing(args: list[str]) -> subprocess.CompletedProcess[str]:
        if args[2] == "add-json":
            return subprocess.CompletedProcess(args, 1, "", "Invalid configuration")
        return subprocess.CompletedProcess(args, 1, "", "not found")

    with pytest.raises(envs.EnvConfigError, match="Invalid configuration"):
        envs.use("staging", run=failing, out=lambda _: None)
    assert envs.read_state() is None


def test_off_restores_plugin_options_and_removes_remote(monkeypatch: pytest.MonkeyPatch, user_file: Path) -> None:
    plugin_options(monkeypatch)
    claude = FakeClaude()
    envs.use("staging", run=claude, out=lambda _: None)
    envs.off(run=claude, out=lambda _: None)
    assert "unizo-ctem-cloud" not in claude.servers and envs.read_state() is None
    assert Settings.from_env().api_url == "https://old.example.com"


def test_cli_list_marks_active(user_file: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert envs.cli(["list"]) == 0
    assert "* " not in capsys.readouterr().out
    envs.use("prod", run=FakeClaude(), out=lambda _: None)
    envs.cli(["list"])
    lines = capsys.readouterr().out.splitlines()
    assert any(line.startswith("* prod") for line in lines) and any(line.startswith("  staging") for line in lines)


def test_cli_usage_and_errors(capsys: pytest.CaptureFixture[str]) -> None:
    assert envs.cli(["frobnicate"]) == 2
    assert "usage: unizo-ctem-mcp env" in capsys.readouterr().err
    assert envs.cli(["list"]) == 1  # no files at all
    assert envs.cli(["use", "nope"]) == 1
    assert 'No environment named "nope"' in capsys.readouterr().err


# ── --file: environments from a file the user names ──


def test_use_with_file_reads_only_that_file(tmp_path: Path, user_file: Path) -> None:
    custom = write(tmp_path / "elsewhere" / "acme.json", {"qa": PROD})
    fake = FakeClaude()
    env = envs.use("qa", file=custom, run=fake, out=lambda _: None)
    assert env.source == custom
    assert fake.servers["unizo-ctem-cloud"]["url"] == PROD["remote_mcp"]["url"]
    # The default files don't define "qa", but the active environment is still found through its source file.
    assert envs.active_environment().name == "qa"
    with pytest.raises(envs.EnvConfigError, match=r'No environment named "staging".*acme\.json'):
        envs.use("staging", file=custom, run=fake, out=lambda _: None)


def test_cli_list_and_use_with_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    custom = write(tmp_path / "acme.json", {"qa": STAGING, "uat": PROD})
    monkeypatch.chdir(tmp_path)
    fake = FakeClaude()
    monkeypatch.setattr(envs.use, "__kwdefaults__", {**envs.use.__kwdefaults__, "run": fake})

    assert envs.cli(["list", "--file", "acme.json"]) == 0
    listed = capsys.readouterr().out
    assert "qa" in listed and "uat" in listed and "*" not in listed

    assert envs.cli(["use", "uat", "--file=acme.json"]) == 0
    assert envs.read_state()["source"] == str(custom.resolve())
    assert envs.cli(["list", "-f", str(custom)]) == 0
    assert "* uat" in capsys.readouterr().out


def test_cli_file_errors(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert envs.cli(["list", "--file", str(tmp_path / "missing.json")]) == 1
    assert "Environments file not found" in capsys.readouterr().err
    assert envs.cli(["list", "--file"]) == 1
    assert "needs a path" in capsys.readouterr().err
