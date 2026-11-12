"""scripts/unizo_env.py: environments file parsing and registering unizo-cloud with the claude CLI."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "unizo_env.py"
_spec = importlib.util.spec_from_file_location("unizo_env", SCRIPT)
assert _spec and _spec.loader
envs = importlib.util.module_from_spec(_spec)
sys.modules["unizo_env"] = envs
_spec.loader.exec_module(envs)

STAGING = {
    "description": "Acme staging",
    "remote_mcp": {"url": "https://unizo-staging.acme.com/mcp", "client_id": "mcp-staging", "callback_port": 3118},
}
PROD = {
    # Keys from earlier plugin versions (gateway and SSO for the local server) are accepted and ignored.
    "api_url": "https://unizo.acme.com",
    "sso_issuer": "https://login.example.com",
    "sso_client_id": "prod-client",
    "remote_mcp": {"url": "https://unizo.acme.com/mcp", "client_id": "mcp-prod"},
}


def write(path: Path, environments: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"environments": environments}))
    return path


@pytest.fixture
def env_file(tmp_path: Path) -> Path:
    return write(tmp_path / "envs" / "acme.json", {"staging": STAGING, "prod": PROD})


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


def quiet(_: str) -> None:
    pass


# ── Parsing ──


@pytest.mark.parametrize(
    ("environment", "message"),
    [
        ({"remote_mcp": {"url": "https://x/mcp"}, "api_token": "YOUR_API_KEY"}, "Secrets don't belong"),
        ({"remote_mcp": {"url": "https://x/mcp"}, "sso_client_secret": "YOUR_API_KEY"}, "Secrets don't belong"),
        ({"remote_mcp": {"url": "https://x/mcp"}, "colour": "blue"}, "unknown key"),
        ({"remote_mcp": {"url": "http://example.com/mcp"}}, "https://"),
        ({"remote_mcp": {"url": "https://x/mcp", "callback_port": 70000}}, "callback_port"),
        ({"remote_mcp": {"url": "https://x/mcp", "headers": {}}}, "unknown key"),
        ({"remote_mcp": {}}, "url is required"),
        ({"description": 5, "remote_mcp": {"url": "https://x/mcp"}}, "description must be a string"),
    ],
)
def test_invalid_environments_are_rejected(tmp_path: Path, environment: dict, message: str) -> None:
    path = write(tmp_path / "bad.json", {"bad": environment})
    with pytest.raises(envs.EnvConfigError, match=message):
        envs.parse_file(path)


def test_invalid_json_and_shape(tmp_path: Path) -> None:
    path = tmp_path / "x.json"
    path.write_text("{not json")
    with pytest.raises(envs.EnvConfigError, match="not valid JSON"):
        envs.parse_file(path)
    path.write_text("[]")
    with pytest.raises(envs.EnvConfigError, match='"environments" object'):
        envs.parse_file(path)


def test_server_config_for_claude(env_file: Path) -> None:
    parsed = envs.parse_file(env_file)
    assert parsed["staging"].server_config() == {
        "type": "http",
        "url": "https://unizo-staging.acme.com/mcp",
        "oauth": {"clientId": "mcp-staging", "callbackPort": 3118},
    }
    assert parsed["prod"].server_config() == {
        "type": "http",
        "url": "https://unizo.acme.com/mcp",
        "oauth": {"clientId": "mcp-prod"},
    }


def test_dynamic_client_registration_and_localhost(tmp_path: Path) -> None:
    path = write(tmp_path / "e.json", {"local": {"remote_mcp": {"url": "http://localhost:9402/mcp"}}})
    assert envs.parse_file(path)["local"].server_config() == {"type": "http", "url": "http://localhost:9402/mcp"}


# ── Switching ──


def test_use_registers_the_remote_server_without_a_headers_helper(env_file: Path) -> None:
    claude = FakeClaude()
    envs.use("staging", file=env_file, run=claude, out=quiet)
    assert claude.servers["unizo-cloud"] == {
        "type": "http",
        "url": "https://unizo-staging.acme.com/mcp",
        "oauth": {"clientId": "mcp-staging", "callbackPort": 3118},
    }
    assert ["claude", "mcp", "add-json", "--scope", "user", "unizo-cloud"] == claude.calls[-1][:6]
    state = envs.read_state()
    assert state["name"] == "staging" and state["source"] == str(env_file) and "setup_complete" not in state


def test_switching_signs_out_the_old_remote_and_replaces_it(env_file: Path) -> None:
    claude = FakeClaude()
    envs.use("staging", file=env_file, run=claude, out=quiet)
    claude.calls.clear()
    envs.use("prod", file=env_file, run=claude, out=quiet)
    assert claude.subcommands() == ["get", "logout", "remove", "add-json"]
    assert claude.servers["unizo-cloud"]["oauth"] == {"clientId": "mcp-prod"}


def test_reapplying_the_same_environment_keeps_the_remote_sign_in(env_file: Path) -> None:
    claude = FakeClaude()
    envs.use("staging", file=env_file, run=claude, out=quiet)
    claude.calls.clear()
    envs.use("staging", file=env_file, run=claude, out=quiet)
    assert "logout" not in claude.subcommands()


def test_registration_from_an_older_version_is_replaced_and_signed_out(env_file: Path, isolated_config: Path) -> None:
    old = {
        "type": "http",
        "url": "https://unizo-staging.acme.com/mcp",
        "headersHelper": "old-unizo-helper headers",
        "oauth": {"clientId": "mcp-staging", "callbackPort": 3118},
    }
    state = isolated_config / "config" / "unizo-mcp" / "active-environment.json"
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text(json.dumps({"name": "staging", "source": str(env_file), "remote": old, "remote_registered": True}))
    claude = FakeClaude({"unizo-cloud": old})
    envs.use("staging", file=env_file, run=claude, out=quiet)
    assert claude.subcommands() == ["get", "logout", "remove", "add-json"]
    assert "headersHelper" not in claude.servers["unizo-cloud"]


def test_environment_without_remote_is_refused(env_file: Path) -> None:
    write(env_file, {"staging": STAGING, "empty": {"description": "no server"}})
    claude = FakeClaude()
    with pytest.raises(envs.EnvConfigError, match="no remote_mcp.url"):
        envs.use("empty", file=env_file, run=claude, out=quiet)
    assert claude.calls == [] and envs.read_state() is None


def test_wont_replace_a_server_it_did_not_add(env_file: Path) -> None:
    claude = FakeClaude({"unizo-cloud": {"type": "http", "url": "https://someone-elses/mcp"}})
    with pytest.raises(envs.EnvConfigError, match="already exists"):
        envs.use("staging", file=env_file, run=claude, out=quiet)
    assert claude.servers["unizo-cloud"]["url"] == "https://someone-elses/mcp"
    envs.use("staging", file=env_file, force=True, run=claude, out=quiet)
    assert claude.servers["unizo-cloud"]["url"] == "https://unizo-staging.acme.com/mcp"


def test_unknown_environment(env_file: Path) -> None:
    with pytest.raises(envs.EnvConfigError, match=r"Available: prod, staging in .*acme\.json"):
        envs.use("qa", file=env_file, run=FakeClaude(), out=quiet)
    assert envs.read_state() is None


def test_add_failure_is_reported_and_state_unchanged(env_file: Path) -> None:
    def failing(args: list[str]) -> subprocess.CompletedProcess[str]:
        if args[2] == "add-json":
            return subprocess.CompletedProcess(args, 1, "", "Invalid configuration")
        return subprocess.CompletedProcess(args, 1, "", "not found")

    with pytest.raises(envs.EnvConfigError, match="Invalid configuration"):
        envs.use("staging", file=env_file, run=failing, out=quiet)
    assert envs.read_state() is None


def test_off_removes_the_remote_and_the_state(env_file: Path) -> None:
    claude = FakeClaude()
    envs.use("staging", file=env_file, run=claude, out=quiet)
    envs.off(run=claude, out=quiet)
    assert "unizo-cloud" not in claude.servers and envs.read_state() is None


def test_setup_done_is_recorded_and_reset_by_the_next_switch(env_file: Path) -> None:
    claude = FakeClaude()
    envs.use("staging", file=env_file, run=claude, out=quiet)
    envs.mark_setup_complete(out=quiet)
    assert envs.read_state()["setup_complete"] is True
    envs.use("prod", file=env_file, run=claude, out=quiet)
    assert "setup_complete" not in envs.read_state()


def test_setup_done_needs_an_active_environment() -> None:
    with pytest.raises(envs.EnvConfigError, match="No Unizo environment is active"):
        envs.mark_setup_complete(out=quiet)


# ── CLI, run as the configure command runs it ──


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True, text=True, check=False)


def test_cli_list_needs_a_file_and_shows_remote_urls(env_file: Path) -> None:
    missing = run_cli("list")
    assert missing.returncode == 1 and "needs --file" in missing.stderr
    listed = run_cli("list", "--file", str(env_file))
    assert listed.returncode == 0
    assert "staging" in listed.stdout and "https://unizo-staging.acme.com/mcp" in listed.stdout


def test_cli_errors_and_usage(tmp_path: Path) -> None:
    assert "not found" in run_cli("list", "--file", str(tmp_path / "nope.json")).stderr
    usage = run_cli("bogus")
    assert usage.returncode == 2 and "usage:" in usage.stderr


def test_cli_current_with_nothing_active() -> None:
    result = run_cli("current")
    assert result.returncode == 0 and "No Unizo environment is active" in result.stdout
