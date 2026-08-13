# D&D 5E Ruleset MCP Server

Zero-dependency Python MCP (Model Context Protocol) server that serves the
D&D 5E SRD rules database — spells, monsters, magic items, equipment, classes,
feats, species, glossary terms, and rules — to any MCP-capable AI client
(Reasonix, Claude Desktop, Cursor, Claude Code, …).

The database is bundled in [`data/`](data/) (`index.json` + one Markdown file
per entity). The server only **reads** it; it never writes anything.

## Requirements

- Python **3.9+** (stdlib only — no `pip install`, no network needed)
- The `data/` folder that ships next to `server.py`

## Run

```bash
python3 server.py                        # serves ./data by default
python3 server.py --selftest             # verify the install (19 checks)
DND_DB_PATH=data python3 server.py       # relative paths anchor to this folder
python3 server.py --db /path/to/db       # absolute overrides also work
```

Portable: the whole folder is self-contained — copy it anywhere and the server
finds its data automatically. No absolute paths are stored inside the folder.

## Tools

| Tool | Purpose |
|---|---|
| `list_types` | Entity types with counts |
| `search_entities(query, type?, limit?)` | Search names/aliases to find the right entity |
| `get_entity(name)` | Full document: metadata + markdown content + resolved `[[...]]` links |
| `list_entities(type, filters?, limit?)` | Filtered listings (spell level/school/class, monster CR/size, item rarity) |
| `resolve_links(name)` | Cross-reference navigation without full content |

Lookup is forgiving: exact key (`Spell Fireball`), name, alias, or normalized
spelling (`fire ball`) all resolve; ambiguous names return every candidate;
typos get "Did you mean …?" suggestions.

## Register with a client

```json
{
  "mcpServers": {
    "dnd-5e-ruleset": {
      "command": "python3",
      "args": ["/path/to/dnd-5e-ruleset-mcp-server/server.py"]
    }
  }
}
```

- **Reasonix**: run `/install-capability`, source = this folder, op = install.
- **Claude Desktop**: add the block to `claude_desktop_config.json`.
- **Cursor**: add it to `.cursor/mcp.json`.

## License

The database is a CC-BY-4.0 compilation of Wizards of the Coast SRD content —
see [`data/ATTRIBUTION.md`](data/ATTRIBUTION.md). Redistribution must preserve
that attribution.
