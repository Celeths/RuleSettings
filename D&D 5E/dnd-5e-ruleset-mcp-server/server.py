#!/usr/bin/env python3
"""D&D 5E Ruleset MCP server — zero-dependency Python stdlib implementation.

Serves the D&D 5E rules database (index.json + per-entity .md files, bundled in
./data) to MCP clients over stdio using newline-delimited JSON-RPC 2.0.

Run:
    python3 server.py                        # serves ./data by default
    DND_DB_PATH=data python3 server.py       # relative paths anchor to this folder
    python3 server.py --db data              # ...or via --db (absolute paths work too)
    python3 server.py --selftest             # run internal checks and exit
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import traceback
from collections import Counter
from pathlib import Path

SERVER_NAME = "dnd-5e-ruleset"
SERVER_VERSION = "1.0.0"
SERVER_DIR = Path(__file__).resolve().parent
SUPPORTED_PROTOCOL_VERSIONS = ("2024-11-05", "2025-03-26", "2025-06-18")
DEFAULT_PROTOCOL_VERSION = SUPPORTED_PROTOCOL_VERSIONS[-1]

ENTITY_TYPES = (
    "rule", "class", "feat", "species", "equipment",
    "magic-item", "monster", "term", "service", "spell",
)

# [[Type Name]] cross-reference links as they appear in the documents.
LINK_RE = re.compile(r"\[\[([^\]]+)\]\]")
# Longest prefixes are tried first at the match site (e.g. "Magic Item" before "Magic").
LINK_PREFIXES = (
    "Magic Item", "Equipment", "Monster", "Spell", "Term",
    "Rule", "Class", "Feat", "Species", "Service", "Background",
)
PREFIX_TYPE = {
    "Magic Item": "magic-item", "Equipment": "equipment", "Monster": "monster",
    "Spell": "spell", "Term": "term", "Rule": "rule", "Class": "class",
    "Feat": "feat", "Species": "species", "Service": "service", "Background": "background",
}

# Type-specific fields exposed in listings; everything else just gets edition.
TYPE_FIELDS = {
    "spell": ("level", "school", "classes"),
    "monster": ("cr", "xp", "size", "alignment"),
    "magic-item": ("rarity",),
}

# Filterable fields per entity type (list_entities).
ALLOWED_FILTERS = {
    "spell": ("level", "school", "classes", "edition"),
    "monster": ("cr", "xp", "size", "alignment", "edition"),
    "magic-item": ("rarity", "edition"),
}
for _t in ENTITY_TYPES:
    ALLOWED_FILTERS.setdefault(_t, ("edition",))

# Tool registry: {"name": ..., "definition": {...}, "handler": callable(db, args)}
TOOLS: list[dict] = []


class JsonRpcError(Exception):
    """A JSON-RPC protocol-level error (surfaces as an `error` object, not a tool result)."""

    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def validate_arguments(args, schema: dict) -> list[str]:
    """Minimal JSON-Schema-subset validator for tool arguments (lenient on extra keys)."""
    if not isinstance(args, dict):
        return ["arguments must be a JSON object"]
    errors: list[str] = []
    props = schema.get("properties", {})
    for required in schema.get("required", []):
        if required not in args:
            errors.append(f"missing required argument '{required}'")
    for key, value in args.items():
        if key not in props:
            continue
        errors.extend(_check_value(key, value, props[key]))
    return errors


def _check_value(key: str, value, spec: dict) -> list[str]:
    errors: list[str] = []
    kind = spec.get("type")
    if kind == "string":
        if not isinstance(value, str):
            errors.append(f"'{key}' must be a string")
        else:
            if "minLength" in spec and len(value) < spec["minLength"]:
                errors.append(f"'{key}' must be at least {spec['minLength']} character(s)")
            if "enum" in spec and value not in spec["enum"]:
                errors.append(f"'{key}' must be one of: {', '.join(spec['enum'])}")
    elif kind == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            errors.append(f"'{key}' must be an integer")
        else:
            if "minimum" in spec and value < spec["minimum"]:
                errors.append(f"'{key}' must be >= {spec['minimum']}")
            if "maximum" in spec and value > spec["maximum"]:
                errors.append(f"'{key}' must be <= {spec['maximum']}")
    elif kind == "boolean":
        if not isinstance(value, bool):
            errors.append(f"'{key}' must be a boolean")
    elif kind == "object":
        if not isinstance(value, dict):
            errors.append(f"'{key}' must be an object")
    return errors


def normalize(text: str) -> str:
    """Normalize like index.json's `names` map: lowercase, strip punctuation, keep spaces."""
    text = text.lower()
    text = re.sub(r"[^a-z0-9 ]+", "", text)
    return re.sub(r"\s+", " ", text).strip()


def split_frontmatter(text: str) -> tuple[str, str]:
    """Return (content, frontmatter_block) — content has the `---` block removed."""
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return text, ""
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return "\n".join(lines[i + 1:]).lstrip("\n"), "\n".join(lines[1:i])
    return text, ""


class Database:
    """Read-only view over the D&D database: index.json + per-entity .md files."""

    def __init__(self, root: Path, index: dict):
        self.root = Path(root)
        self.index = index
        self.entities: dict[str, dict] = index.get("entities", {})
        self.names: dict[str, list[str]] = index.get("names", {})
        self.counts: dict[str, int] = index.get("counts", {})

        # name/alias (lowercased) -> entity keys, for direct name lookups
        self.name_lookup: dict[str, list[str]] = {}
        for key, ent in self.entities.items():
            names = [ent.get("name")] + list(ent.get("aliases", []))
            for nm in names:
                if nm:
                    self.name_lookup.setdefault(nm.lower(), []).append(key)

        # space-stripped variant of the names index (for 'fireball' vs 'fire ball')
        self.stripped_names: dict[str, list[str]] = {}
        for name, keys in self.names.items():
            self.stripped_names.setdefault(name.replace(" ", ""), []).extend(keys)

    # -- lookup -----------------------------------------------------------

    def resolve(self, name) -> list[str]:
        """Resolution chain: exact key -> name/alias -> normalized -> stripped.
        Returns every matching entity key (ambiguous names yield all candidates)."""
        if not isinstance(name, str) or not name.strip():
            return []
        name = name.strip()
        if name in self.entities:
            return [name]
        keys = self.name_lookup.get(name.lower())
        if keys:
            return list(dict.fromkeys(keys))
        norm = normalize(name)
        keys = self.names.get(norm)
        if keys:
            return list(keys)
        keys = self.stripped_names.get(norm.replace(" ", ""))
        if keys:
            return list(keys)
        return []

    def summary(self, key: str, with_type_fields: bool = False) -> dict:
        ent = self.entities[key]
        out = {
            "key": key,
            "name": ent.get("name", key),
            "type": ent.get("type"),
            "edition": ent.get("edition"),
        }
        if with_type_fields:
            for field in TYPE_FIELDS.get(ent.get("type"), ()):
                if field in ent:
                    out[field] = ent[field]
        return out

    # -- search -----------------------------------------------------------

    def search(self, query: str, entity_type=None, limit: int = 20) -> list[dict]:
        q = normalize(query)
        q_stripped = q.replace(" ", "")
        if not q:
            return []
        scored: dict[str, int] = {}
        for norm_name, keys in self.names.items():
            if q in norm_name or q_stripped in norm_name.replace(" ", ""):
                for key in keys:
                    ent = self.entities.get(key)
                    if ent is None:
                        continue
                    if entity_type and ent.get("type") != entity_type:
                        continue
                    rank = 0 if ent.get("name", "").lower().startswith(q) else (
                        1 if norm_name.startswith(q) else 2
                    )
                    if key not in scored or rank < scored[key]:
                        scored[key] = rank
        # direct name/alias prefix matches that the names index may not cover
        for lower_name, keys in self.name_lookup.items():
            if lower_name.startswith(q):
                for key in keys:
                    ent = self.entities.get(key)
                    if ent is None:
                        continue
                    if entity_type and ent.get("type") != entity_type:
                        continue
                    scored.setdefault(key, 0)
        ordered = sorted(scored.items(), key=lambda kv: (kv[1], kv[0].lower()))
        return [self.summary(key) for key, _ in ordered[:limit]]

    # -- listings ---------------------------------------------------------

    def list_types(self) -> list[dict]:
        counter = Counter(e.get("type") for e in self.entities.values())
        return [{"type": t, "count": n} for t, n in sorted(counter.items())]

    def list_entities(self, entity_type: str, filters: dict, limit: int = 100):
        allowed = ALLOWED_FILTERS.get(entity_type, ("edition",))
        unknown = [k for k in filters if k not in allowed]
        if unknown:
            raise ValueError(
                f"Unknown filter(s) for type '{entity_type}': {', '.join(sorted(unknown))}. "
                f"Allowed filters: {', '.join(allowed)}"
            )
        results = []
        for key, ent in self.entities.items():
            if ent.get("type") != entity_type:
                continue
            ok = True
            for fk, fv in filters.items():
                ev = ent.get(fk)
                if ev is None:
                    ok = False
                    break
                if fk == "classes":
                    if not any(str(fv).lower() in str(c).lower() for c in ev):
                        ok = False
                        break
                elif str(ev).lower() != str(fv).lower():
                    ok = False
                    break
            if ok:
                results.append(self.summary(key, with_type_fields=True))
        results.sort(key=lambda r: r["name"].lower())
        return len(results), results[:limit]

    # -- document access --------------------------------------------------

    def read_entity(self, key: str) -> dict:
        ent = self.entities[key]
        root = self.root.resolve()
        path = (self.root / ent["file"]).resolve()
        if not path.is_relative_to(root):
            raise ValueError(f"entity file escapes the database root: {ent['file']}")
        text = path.read_text(encoding="utf-8")
        content, _frontmatter = split_frontmatter(text)
        links, seen = [], set()
        for inner in LINK_RE.findall(content):
            if inner in seen:
                continue
            seen.add(inner)
            links.append(self.resolve_link(inner))
        return {
            "key": key,
            "name": ent.get("name", key),
            "type": ent.get("type"),
            "edition": ent.get("edition"),
            "aliases": ent.get("aliases", []),
            "metadata": {
                k: v for k, v in ent.items()
                if k not in ("file", "name", "type", "edition", "aliases")
            },
            "content": content,
            "links": links,
        }

    def resolve_link(self, inner: str) -> dict:
        """Resolve one [[...]] link body to an entity, or report it as unresolved."""
        info = {"text": inner, "resolved": False}
        if inner in self.entities:
            ent = self.entities[inner]
            info.update({
                "key": inner, "name": ent.get("name", inner),
                "type": ent.get("type"), "resolved": True,
            })
            return info
        for prefix in sorted(LINK_PREFIXES, key=len, reverse=True):
            if inner.startswith(prefix + " "):
                keys = [
                    k for k in self.resolve(inner[len(prefix) + 1:])
                    if self.entities[k].get("type") == PREFIX_TYPE[prefix]
                ]
                if len(keys) == 1:
                    ent = self.entities[keys[0]]
                    info.update({
                        "key": keys[0], "name": ent.get("name", inner),
                        "type": ent.get("type"), "resolved": True,
                    })
                return info
        return info


def run_selftest(db: Database) -> bool:
    checks: list[tuple[str, bool, str]] = []

    def check(label: str, cond: bool, detail: str = "") -> None:
        checks.append((label, bool(cond), detail))

    expected_total = sum(db.counts.values())
    check("index loads and counts agree", len(db.entities) == expected_total,
          f"{len(db.entities)} entities vs counts sum {expected_total}")

    check("resolve exact key", db.resolve("Spell Fireball") == ["Spell Fireball"])
    check("resolve by name", db.resolve("Fireball") == ["Spell Fireball"])
    check("resolve by alias", "Magic Item Bag of Holding" in db.resolve("Bag of Holding"))
    check("resolve normalized", "Term Advantage" in db.resolve("advantage"))
    check("resolve stripped", "Spell Fireball" in db.resolve("Fire Ball"))
    check("resolve ambiguous returns all", sorted(db.resolve("druid")) == ["Class Druid", "Monster Druid"])
    check("resolve unknown", db.resolve("zzz definitely not an entity") == [])

    spell = db.read_entity("Spell Fireball")
    check("read_entity content", "8d6" in spell["content"])
    check("read_entity metadata", spell["metadata"].get("level") == "3"
          and spell["metadata"].get("school") == "Evocation")
    links = {l["text"]: l for l in spell["links"]}
    check("read_entity links extracted",
          "Term Action" in links and links["Term Action"]["resolved"] is True
          and links["Term Action"]["key"] == "Term Action")
    check("read_entity link prefix resolution",
          db.resolve_link("Spell Fire Ball")["resolved"] is True
          and db.resolve_link("Spell Fire Ball")["key"] == "Spell Fireball")

    dragon = db.read_entity("Monster Ancient Red Dragon")
    dlinks = {l["text"]: l for l in dragon["links"]}
    check("read_entity spell links from monster doc",
          "Spell Scorching Ray" in dlinks and dlinks["Spell Scorching Ray"]["resolved"] is True
          and dlinks["Spell Scorching Ray"]["key"] == "Spell Scorching Ray"
          and "Spell Command" in dlinks and dlinks["Spell Command"]["resolved"] is True)

    hits = db.search("fire", entity_type="spell", limit=50)
    hit_keys = {h["key"] for h in hits}
    check("search finds Fireball", "Spell Fireball" in hit_keys)
    check("search respects type filter", all(h["type"] == "spell" for h in hits))

    total, rows = db.list_entities("spell", {"level": "3", "school": "Evocation"})
    check("list_entities filters", total >= 1 and any(r["key"] == "Spell Fireball" for r in rows))
    total, rows = db.list_entities("monster", {"cr": "24"})
    check("list_entities monster cr", any(r["key"] == "Monster Ancient Red Dragon" for r in rows))
    try:
        db.list_entities("spell", {"bogus_filter": "x"})
        check("list_entities rejects unknown filters", False)
    except ValueError:
        check("list_entities rejects unknown filters", True)

    counts = {t["type"]: t["count"] for t in db.list_types()}
    check("list_types matches index counts", counts == db.counts)

    failed = [c for c in checks if not c[1]]
    for label, ok, detail in checks:
        print(f"{'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail and not ok else ""))
    print(f"\nselftest: {len(checks) - len(failed)}/{len(checks)} checks passed")
    return not failed


# ---------------------------------------------------------------------------
# Tools — MCP tool definitions + handlers
# ---------------------------------------------------------------------------

def _format_entity(entity: dict) -> str:
    lines = [
        f"key: {entity['key']}",
        f"name: {entity['name']}",
        f"type: {entity['type']}",
    ]
    if entity.get("edition"):
        lines.append(f"edition: {entity['edition']}")
    for k, v in sorted(entity["metadata"].items()):
        if isinstance(v, list):
            v = ", ".join(str(x) for x in v)
        lines.append(f"{k}: {v}")
    lines += ["", "--- content ---", entity["content"].rstrip(), "", "--- links ---"]
    resolved = [l for l in entity["links"] if l["resolved"]]
    unresolved = [l for l in entity["links"] if not l["resolved"]]
    for l in resolved:
        lines.append(f"[{l['text']}] -> {l['key']} ({l['type']})")
    for l in unresolved:
        lines.append(f"[{l['text']}] -> (unresolved)")
    if not entity["links"]:
        lines.append("(none)")
    return "\n".join(lines)


def _not_found_text(db: Database, name: str) -> str:
    suggestions = db.search(name, limit=5)
    if not suggestions and len(name) > 2:
        # cheap typo fallback: retry without the last character
        suggestions = db.search(name[:-1], limit=5)
    text = f"No entity found for '{name}'."
    if suggestions:
        names = ", ".join(s["name"] for s in suggestions)
        text += f" Did you mean: {names}?"
    return text


def _ambiguous_text(db: Database, name: str, keys: list[str]) -> str:
    lines = [
        f"Name '{name}' is ambiguous — it matches {len(keys)} entities:",
    ]
    for key in keys:
        ent = db.entities[key]
        lines.append(f"  {key}  (name: {ent.get('name', key)}, type: {ent.get('type')})")
    lines.append("Call get_entity / resolve_links again with one of the exact keys above.")
    return "\n".join(lines)


def _resolve_single(db: Database, name: str):
    """Returns (text, is_error) for get_entity/resolve_links shared resolution."""
    keys = db.resolve(name)
    if not keys:
        return _not_found_text(db, name), True
    if len(keys) > 1:
        return _ambiguous_text(db, name, keys), True
    return keys[0], False


def _tool_list_types(db: Database, args):
    return {"text": json.dumps(db.list_types(), indent=2), "isError": False}


def _tool_search_entities(db: Database, args):
    query = args["query"]
    entity_type = args.get("type")
    limit = args.get("limit", 20)
    results = db.search(query, entity_type=entity_type, limit=limit)
    text = json.dumps(
        {"query": query, "type": entity_type, "count": len(results), "results": results},
        indent=2,
    )
    if not results:
        text += "\nNo matches. Try a shorter query or drop the type filter."
    return {"text": text, "isError": False}


def _tool_get_entity(db: Database, args):
    key, is_error = _resolve_single(db, args["name"])
    if is_error:
        return {"text": key, "isError": True}
    return {"text": _format_entity(db.read_entity(key)), "isError": False}


def _tool_list_entities(db: Database, args):
    entity_type = args["type"]
    filters = args.get("filters") or {}
    limit = args.get("limit", 100)
    try:
        total, rows = db.list_entities(entity_type, filters, limit=limit)
    except ValueError as exc:
        return {"text": str(exc), "isError": True}
    text = json.dumps(
        {"type": entity_type, "total": total, "returned": len(rows), "results": rows},
        indent=2,
    )
    if total > len(rows):
        text += f"\n(total {total}; increase 'limit' up to 500 to see more)"
    return {"text": text, "isError": False}


def _tool_resolve_links(db: Database, args):
    key, is_error = _resolve_single(db, args["name"])
    if is_error:
        return {"text": key, "isError": True}
    entity = db.read_entity(key)
    text = json.dumps(
        {
            "key": entity["key"],
            "name": entity["name"],
            "type": entity["type"],
            "links": entity["links"],
        },
        indent=2,
    )
    return {"text": text, "isError": False}


def _register_tools() -> None:
    TOOLS.extend([
        {
            "name": "list_types",
            "definition": {
                "name": "list_types",
                "description": (
                    "List the entity types available in the D&D 5E database with their "
                    "counts (spell, monster, magic-item, equipment, term, rule, class, "
                    "feat, species, service). Use this first to learn what the database "
                    "contains."
                ),
                "inputSchema": {"type": "object", "properties": {}, "required": []},
            },
            "handler": _tool_list_types,
        },
        {
            "name": "search_entities",
            "definition": {
                "name": "search_entities",
                "description": (
                    "Search the database index for entities whose name or alias matches "
                    "the query (substring match, case-insensitive). Returns lightweight "
                    "results: key, name, type, edition. Use this to find the right entity "
                    "before calling get_entity. Optionally restrict to one type and cap "
                    "the result count."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "minLength": 1,
                            "description": "Search text, e.g. 'fire' or 'dragon'.",
                        },
                        "type": {
                            "type": "string",
                            "enum": list(ENTITY_TYPES),
                            "description": "Restrict results to one entity type.",
                        },
                        "limit": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 100,
                            "description": "Max results (default 20).",
                        },
                    },
                    "required": ["query"],
                },
            },
            "handler": _tool_search_entities,
        },
        {
            "name": "get_entity",
            "definition": {
                "name": "get_entity",
                "description": (
                    "Fetch the full document for one entity by name, alias, or exact key "
                    "(e.g. 'Fireball', 'Bag of Holding', or 'Monster Ancient Red Dragon'). "
                    "Returns the entity's metadata (level, school, CR, rarity, ...), the "
                    "complete markdown content, and every [[Type Name]] cross-reference "
                    "link resolved to its target entity. Ambiguous names return all "
                    "candidates so you can pick the exact key."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "minLength": 1,
                            "description": "Entity name, alias, or exact index key.",
                        },
                    },
                    "required": ["name"],
                },
            },
            "handler": _tool_get_entity,
        },
        {
            "name": "list_entities",
            "definition": {
                "name": "list_entities",
                "description": (
                    "List entities of one type, optionally filtered by their indexed "
                    "fields. Filters per type — spell: level (0-9), school, classes, "
                    "edition; monster: cr (e.g. '3' or '1/2'), xp, size, alignment, "
                    "edition; magic-item: rarity, edition; all other types: edition. "
                    "Filters are case-insensitive exact matches (classes is a substring "
                    "match). Returns key, name, type, edition and type-specific fields."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "type": {
                            "type": "string",
                            "enum": list(ENTITY_TYPES),
                            "description": "Entity type to list.",
                        },
                        "filters": {
                            "type": "object",
                            "description": (
                                "Field filters, e.g. {\"level\": \"3\", \"school\": "
                                "\"Evocation\"} or {\"cr\": \"24\"} or {\"rarity\": "
                                "\"Uncommon\"}."
                            ),
                        },
                        "limit": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 500,
                            "description": "Max results (default 100).",
                        },
                    },
                    "required": ["type"],
                },
            },
            "handler": _tool_list_entities,
        },
        {
            "name": "resolve_links",
            "definition": {
                "name": "resolve_links",
                "description": (
                    "Resolve the [[Type Name]] cross-reference links in one entity's "
                    "document without returning the full content. Returns the list of "
                    "links with their resolved target key, name, and type — useful for "
                    "navigating related rules, spells, monsters, and terms cheaply. "
                    "Ambiguous names return all candidates."
                ),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "minLength": 1,
                            "description": "Entity name, alias, or exact index key.",
                        },
                    },
                    "required": ["name"],
                },
            },
            "handler": _tool_resolve_links,
        },
    ])


_register_tools()


def resolve_root(cli_value: str | None) -> Path:
    """Data root: --db flag > DND_DB_PATH env var > data/ next to this script.

    Relative paths (e.g. `data` or `./data`) are anchored to the server's own
    folder, so they work no matter which directory the process is launched
    from. Absolute paths are used as-is.
    """
    for value in (cli_value, os.environ.get("DND_DB_PATH")):
        if value:
            path = Path(value)
            return path if path.is_absolute() else (SERVER_DIR / path).resolve()
    return SERVER_DIR / "data"


def load_database(root: Path) -> dict:
    index_path = root / "index.json"
    if not index_path.is_file():
        raise FileNotFoundError(
            f"index.json not found at {index_path}. "
            "Pass --db <root> or set DND_DB_PATH to the database folder "
            "(the one containing index.json)."
        )
    with index_path.open("r", encoding="utf-8") as fh:
        return json.load(fh)


class McpServer:
    """Minimal MCP server: JSON-RPC 2.0 over newline-delimited stdio."""

    def __init__(self, db: Database):
        self.db = db
        self.entities = db.entities

    # -- wire protocol ----------------------------------------------------

    def handle_line(self, line: str):
        """Handle one incoming JSON-RPC message; return the response dict, or None for notifications."""
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            return {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32700, "message": "Parse error"},
            }
        if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0":
            return {
                "jsonrpc": "2.0",
                "id": None,
                "error": {"code": -32600, "message": "Invalid Request"},
            }
        if "id" not in msg:
            return None  # notification — no response expected

        request_id = msg.get("id")
        method = msg.get("method")
        params = msg.get("params")
        if not isinstance(params, dict):
            params = {}
        try:
            result = self.dispatch(method, params)
            return {"jsonrpc": "2.0", "id": request_id, "result": result}
        except JsonRpcError as exc:
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": exc.code, "message": exc.message},
            }
        except Exception as exc:  # noqa: BLE001 — last-resort protocol safety
            traceback.print_exc(file=sys.stderr)
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": -32603, "message": f"Internal error: {type(exc).__name__}"},
            }

    def dispatch(self, method, params):
        if not isinstance(method, str) or not method:
            raise JsonRpcError(-32600, "Invalid Request")
        if method == "initialize":
            requested = params.get("protocolVersion")
            if requested in SUPPORTED_PROTOCOL_VERSIONS:
                chosen = requested
            elif isinstance(requested, str):
                older = [v for v in SUPPORTED_PROTOCOL_VERSIONS if v <= requested]
                chosen = older[-1] if older else DEFAULT_PROTOCOL_VERSION
            else:
                chosen = DEFAULT_PROTOCOL_VERSION
            return {
                "protocolVersion": chosen,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            }
        if method == "ping":
            return {}
        if method == "tools/list":
            return {"tools": [t["definition"] for t in TOOLS]}
        if method == "tools/call":
            return self.call_tool(params)
        raise JsonRpcError(-32601, f"Method not found: {method}")

    def call_tool(self, params):
        name = params.get("name")
        if not isinstance(name, str) or not name:
            raise JsonRpcError(-32602, "Invalid arguments: missing or invalid 'name'")
        tool = next((t for t in TOOLS if t["name"] == name), None)
        if tool is None:
            raise JsonRpcError(-32601, f"Unknown tool: {name}")
        args = params.get("arguments")
        if args is None:
            args = {}
        errors = validate_arguments(args, tool["definition"]["inputSchema"])
        if errors:
            raise JsonRpcError(-32602, "Invalid arguments: " + "; ".join(errors))
        try:
            out = tool["handler"](self.db, args)
        except Exception as exc:  # noqa: BLE001 — tool-level failure, not a crash
            traceback.print_exc(file=sys.stderr)
            return {
                "content": [{"type": "text", "text": f"Internal error: {type(exc).__name__}"}],
                "isError": True,
            }
        result = {"content": [{"type": "text", "text": out["text"]}]}
        if out.get("isError"):
            result["isError"] = True
        return result


def serve(server: McpServer) -> None:
    sys.stderr.write(
        f"{SERVER_NAME} {SERVER_VERSION} ready — {len(server.entities)} entities indexed\n"
    )
    sys.stderr.flush()
    stdin = sys.stdin.buffer
    stdout = sys.stdout.buffer
    for raw in stdin:  # loop ends on EOF (client closed stdin) -> clean exit
        line = raw.decode("utf-8", errors="replace").strip()
        if not line:
            continue
        response = server.handle_line(line)
        if response is not None:
            try:
                stdout.write(json.dumps(response).encode("utf-8") + b"\n")
                stdout.flush()
            except (BrokenPipeError, OSError):
                return  # client disconnected mid-response — exit cleanly


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
