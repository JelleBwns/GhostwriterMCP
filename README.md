# Ghostwriter MCP

A lightweight Python MCP server that lets OpenCode, Claude Code, Codex CLI, and other MCP clients work with an external [Ghostwriter](https://github.com/GhostManager/Ghostwriter) instance.

Includes **23 tools** for reports, findings, summaries, evidence, templates, and JSON exports. Runs over stdio—no Docker, database, workers, or separate LLM service. Your AI client writes the content; Ghostwriter stores it.

## Install

Requires Python 3.12+, [uv](https://docs.astral.sh/uv/), and a Ghostwriter API token with the appropriate permissions.

```sh
git clone https://github.com/JelleBwns/GhostwriterMCP.git
cd GhostwriterMCP
uv sync --frozen --python 3.12
cp .env.example .env
chmod 600 .env
```

Edit `.env` with your instance and scope (replace the example client ID):

```env
GW_BASE_URL=https://ghostwriter.example.com
GW_TOKEN=your-api-token
ALLOWED_CLIENTS=[1]
ALLOWED_PROJECTS=[]
GW_ENABLED_TOOLS=[]
GW_DISABLED_TOOLS=["gw_create_report","gw_delete_finding","gw_delete_evidence"]
```

Create the API token from your Ghostwriter profile's **API Tokens** card. Keep it in the ignored `.env` file.

## Connect your client

Complete the installation above, then run the commands for your client from this repository. Each registration uses absolute paths and reads credentials from your private `.env`.

### OpenCode

With OpenCode 2 installed:

```sh
opencode mcp add --global \
  --env GW_REPORTING_ENV_FILE="$(pwd)/.env" \
  ghostwriter -- "$(pwd)/.venv/bin/python" -m gw_reporting
opencode reload
```

### Claude Code

[Install and sign in to Claude Code](https://code.claude.com/docs/en/setup), then register the server for your user:

```sh
claude mcp add --transport stdio --scope user ghostwriter \
  --env GW_REPORTING_ENV_FILE="$(pwd)/.env" \
  -- "$(pwd)/.venv/bin/python" -m gw_reporting
```

Restart Claude Code and use `/mcp` to check the connection. See the [Claude Code MCP documentation](https://code.claude.com/docs/en/mcp).

### Codex CLI

[Install and sign in to Codex CLI](https://developers.openai.com/codex/cli/), then register the server:

```sh
codex mcp add ghostwriter \
  --env GW_REPORTING_ENV_FILE="$(pwd)/.env" \
  -- "$(pwd)/.venv/bin/python" -m gw_reporting
codex mcp list
```

Restart Codex and use `/mcp` to check the connection. See the [Codex MCP documentation](https://learn.chatgpt.com/docs/extend/mcp).

Other MCP clients can launch `.venv/bin/python -m gw_reporting`, setting `GW_REPORTING_ENV_FILE` to the absolute `.env` path.

## Permissions and usage

- `GW_ENABLED_TOOLS`: optional allowlist. `GW_DISABLED_TOOLS`: blacklist; blacklist wins.
- If both tool lists are empty or absent, **all 23 tools are enabled**, including deletion tools.
- Nonempty `ALLOWED_CLIENTS` and `ALLOWED_PROJECTS` lists both have to match. Empty scope lists add no restriction beyond the token's permissions.
- Restart the MCP process after changing settings. Tool policy does not restrict an agent's independent shell/filesystem access.

Example prompt: “Inspect my test report, draft an informational finding from these notes, and add it to the report.”

Inspect available tools offline with `uv run python -m gw_reporting tools`. See the [tool list](docs/api-coverage.md), [API limitations](docs/ghostwriter-api-mapping.md), and [agent skill](.agents/skills/ghostwriter-mcp/SKILL.md).

JSON export is supported; automatic Word/PowerPoint rendering is not. Evidence deletion verifies record removal; physical file cleanup may remain unverified.

## Development

```sh
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

Automated tests block real network connections. Credentials, assessment data, and local live-test results are excluded from Git.
