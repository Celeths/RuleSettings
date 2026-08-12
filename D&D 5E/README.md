# D&D 5E Database

An edition-tagged, per-entity Markdown database of the D&D System. Built for machine consumption: each game object or rule concept is one
file with YAML frontmatter, and `index.json` maps every natural name to its file.


## Directory layout

| Directory | Contents |
|---|---|
| `Rules/` | Rule topic pages (`Rule *.md`) |
| `Rules/Glossary/` | Glossary terms (`Term *.md`) |
| `Character Options/` | Character creation, classes, species, backgrounds, feats |
| `Spells/` | All spells, flat (`Spell *.md`) |
| `Monsters/` | All monsters, flat (`Monster *.md`) |
| `Magic Items/` | All magic items, flat (`Magic Item *.md`) |
| `Equipment/` | Mundane equipment and equipment tables (`Equipment *.md`) |
| `Services/` | Purchasable services (`Service *.md`) |

## Naming convention

Every content file is named `<Prefix> <Name>.md`. The prefix encodes the entity type, which
makes filenames **globally unique** (a flat database cannot contain two files with the same
name) and **self-describing** (the type is visible without opening the file).

| Prefix | Type | Example |
|---|---|---|
| `Spell` | spell | `Spell Acid Arrow.md` |
| `Monster` | monster / NPC | `Monster Aboleth.md` |
| `Magic Item` | magic item | `Magic Item Ring of Protection.md` |
| `Equipment` | equipment item or table | `Equipment Chain Mail.md` |
| `Class` | class, or a class's spell list | `Class Druid.md`, `Class Wizard Spell List.md` |
| `Species` | species | `Species Dwarf.md` |
| `Feat` | feat | `Feat Alert.md` |
| `Background` | background | (reserved; 5.1 backgrounds kept as `Rule Backgrounds.md`) |
| `Service` | purchasable service | `Service Hirelings.md` |
| `Term` | glossary term | `Term Grappled.md` |
| `Rule` | rule / process topic page | `Rule Combat.md`, `Rule Character Creation.md` |

Only root-level files (`README.md`, `ATTRIBUTION.md`, `index.json`) are unprefixed.

## Frontmatter schema

Every file starts with a YAML frontmatter block. Common fields:

| Field | Meaning |
|---|---|
| `name` | Natural entity name, e.g. `Acid Arrow` |
| `aliases` | Other names/forms, e.g. `Antipathy/Sympathy` for `Antipathy-Sympathy` |
| `type` | One of the prefix values, lowercase: `spell`, `monster`, `magic-item`, `equipment`, `class`, `species`, `feat`, `background`, `service`, `term`, `rule` |
| `edition` | `5.2` (canon, may be omitted) or `5.1` |

Type-specific fields (canon files; left out when the source doesn't state them):

| Type | Fields |
|---|---|
| `spell` | `level` (0 = cantrip), `school`, `classes` |
| `monster` | `cr`, `xp`, `size`, `alignment` |
| `magic-item` | `rarity` |
| `class` | — |
| `species` / `feat` / `equipment` / `service` / `term` / `rule` | — |

Example:

```markdown
---
name: Acid Arrow
aliases:
  - Acid Arrow
type: spell
edition: 5.2
level: 2
school: evocation
classes:
  - Wizard
---

# Acid Arrow

_Level 2 Evocation (Wizard)_
...
```

## index.json

tructure:

- `entities`: one entry per file, keyed by prefixed name, with path and frontmatter fields.
- `names`: normalized (lowercased, punctuation-stripped) natural names → list of entity
  keys, so a query term like `darkness` or `druid` surfaces every candidate.

## License

See `ATTRIBUTION.md`. This database is a compilation of Wizards of the Coast SRD content
under CC-BY-4.0.
