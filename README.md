# ctem-claude-plugin

A Claude Code plugin for Unizo CTEM (Continuous Threat Exposure Management).

## What's included

| Type | Name | Purpose |
|---|---|---|
| Command | `/ctem:ctem-hello` | Check that the plugin is installed and list what it provides |
| Skill | `ctem-basics` | Explains CTEM concepts and the five-stage cycle |
| Agent | `exposure-triage` | Triages a finding and recommends a priority and next step |

## Install

This repo is both a plugin and a single-plugin marketplace.

```
/plugin marketplace add Unizo-CTEM/ctem-claude-plugin
/plugin install ctem@unizo-ctem
```

For local development:

```
claude --plugin-dir ./ctem-claude-plugin
```

## Layout

```
.claude-plugin/
  plugin.json        # plugin manifest
  marketplace.json   # marketplace catalog (lists this plugin)
commands/            # slash commands
skills/              # skills (one folder per skill, with SKILL.md)
agents/              # subagents
```

## Validate

```
claude plugin validate .
```
