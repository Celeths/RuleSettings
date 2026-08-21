#!/usr/bin/env python3
"""Lite MCP server for small local models (8B class).

Same D&D 5E database and lookup engine as server.py, but exposes only three
tools — get_skill (behavior instructions), list_types, and get_entity —
because small models choose and chain tools unreliably. get_entity resolves
names, aliases, misspellings, and 'fire ball'-style input directly, so the
whole lookup workflow is ONE tool call: no search step, no multi-step chains.
get_skill lets the model load its own behavior instructions (the contents of
D&D-5E-Lite-MCP-Skill.md) in apps that don't support skills.

Usage:
    python3 server-lite.py                  # serve ./data
    python3 server-lite.py --selftest       # verify the install

Register in a client as:
    {"mcpServers": {"dnd-5e-ruleset-lite": {
        "command": "python3", "args": ["server-lite.py"]}}}
"""

import argparse
import json
import sys

import server as full
from server import (
    SERVER_DIR,
    Database,
    McpServer,
    _tool_get_entity,
    _tool_list_types,
    load_database,
    resolve_root,
    serve,
    split_frontmatter,
)

SKILL_FILE = SERVER_DIR / "D&D-5E-Lite-MCP-Skill.md"


def _tool_get_skill(db, args):
    """Return the rulebook behavior instructions (D&D-5E-Lite-MCP-Skill.md)."""
    try:
        text = SKILL_FILE.read_text(encoding="utf-8")
    except OSError:
        return {
            "text": (
                "Skill file not found (expected D&D-5E-Lite-MCP-Skill.md next to "
                "server-lite.py)."
            ),
            "isError": True,
        }
    body, _ = split_frontmatter(text)
    return {
        "text": "D&D 5E Lite Rulebook — behavior instructions (follow these):\n\n" + body,
        "isError": False,
    }


LITE_TOOLS = [
    {
        "name": "get_skill",
        "definition": {
            "name": "get_skill",
            "description": (
                "Load this rulebook's behavior instructions: how to format cards, "
                "which lookup rules to follow, and what not to do. Call this once at "
                "the very start of the conversation, before looking anything up, and "
                "follow what it says."
            ),
            "inputSchema": {"type": "object", "properties": {}, "required": []},
        },
        "handler": _tool_get_skill,
    },
    {
        "name": "list_types",
        "definition": {
            "name": "list_types",
            "description": (
                "List the entity types in the D&D 5E database with their counts "
                "(spell, monster, magic-item, equipment, term, rule, class, feat, "
                "species, service). Rarely needed."
            ),
            "inputSchema": {"type": "object", "properties": {}, "required": []},
        },
        "handler": _tool_list_types,
    },
    {
        "name": "get_entity",
        "definition": {
            "name": "get_entity",
            "description": (
                "Look up ONE D&D 5E book entry by the name exactly as the player "
                "said it — e.g. 'owlbear', 'fire ball', 'bag of holding', 'poisoned', "
                "'short rest'. Misspellings, aliases, and missing spaces usually "
                "still resolve. ALWAYS call this tool directly when the player names "
                "or implies an entry; do not search first and do not answer from "
                "memory. If the result is an error, it lists candidate names or a "
                "suggestion: call this tool again with the best candidate name, or "
                "show '— Not in the book.' if nothing fits."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "minLength": 1,
                        "description": "Entity name as the player said it (e.g. 'owlbear').",
                    },
                },
                "required": ["name"],
            },
        },
        "handler": _tool_get_entity,
    },
]

# Point the shared serving layer at the lite tool set.
full.TOOLS = LITE_TOOLS
full.SERVER_NAME = "dnd-5e-ruleset-lite"
full.SERVER_VERSION = "1.0-lite"


def run_selftest(db: Database) -> bool:
    checks = [
        ("only 3 tools registered", len(LITE_TOOLS) == 3),
        ("skill file exists next to server", SKILL_FILE.is_file()),
        ("get_skill returns instructions",
         not _tool_get_skill(db, {})["isError"]),
        ("get_entity resolves 'owlbear'",
         db.resolve("owlbear") == ["Monster Owlbear"]),
        ("get_entity resolves 'fire ball'",
         db.resolve("fire ball") == ["Spell Fireball"]),
        ("get_entity resolves uppercase 'FIREBALL'",
         db.resolve("FIREBALL") == ["Spell Fireball"]),
        ("typo 'frieball' yields no key (error path)",
         db.resolve("frieball") == []),
        ("get_entity tool returns content",
         _tool_get_entity(db, {"name": "owlbear"})["isError"] is False),
    ]
    ok = True
    for label, cond in checks:
        print(("PASS  " if cond else "FAIL  ") + label)
        ok = ok and cond
    print(f"selftest: {sum(1 for _, c in checks if c)}/{len(checks)} checks passed")
    return ok


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", help="Database root folder (must contain index.json).")
    parser.add_argument("--selftest", action="store_true", help="Run internal checks and exit.")
    args = parser.parse_args(argv)

    root = resolve_root(args.db)
    try:
        index = load_database(root)
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except json.JSONDecodeError as exc:
        print(f"error: {root / 'index.json'} is not valid JSON: {exc}", file=sys.stderr)
        return 1

    db = Database(root, index)
    if args.selftest:
        return 0 if run_selftest(db) else 1

    serve(McpServer(db))
    return 0


if __name__ == "__main__":
    sys.exit(main())
