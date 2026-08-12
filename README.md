# RuleSettings

**RuleSettings** is a database of game rules, formatted specifically for AI agents to read, understand, and apply.

Instead of messy PDFs or rulebooks that humans have to parse, RuleSettings provides clean, structured rulesets that any agent (or app) can query to answer questions like:

- *"Is this move legal?"*
- *"Is this move legal?"*
- *"What happens when I roll a double?"*
- *"Anything I need to keep track of right now?"*
- *"What are the win conditions?"*

## Why does this exist?

AI agents are becoming great at helping people play games. But to be truly helpful, they need a reliable source of truth for the rules.

That's what RuleSettings is: **the source of truth.** It's a database of rules, not as paragraphs of text, but as data—so agents can reference them quickly and confidently.

## What's inside?

- Game rulesets for a variety of board games, card games, and tabletop RPGs
- Each ruleset is formatted in a consistent, machine-readable structure (JSON)
- Every rule is labeled and organized so it's easy to find specific sections like setup, turn order, scoring, or special abilities
- **Only rulesets that have been released to the public domain or under a Creative Commons Attribution (CC-BY) license.** No illegal or licensed content is included.

## Content Licensing

All rulesets in this repo are **free to share** and have been sourced from games that explicitly allow redistribution through public domain or CC-BY licenses.

If you own or know of a game that is available under such a license and would like it added, feel free to contribute.

## Copyright & Infringement

This project is meant to be a free, open resource. If you believe any ruleset included here infringes on a copyright or was accidentally included without permission, please **open an issue** and I will review and remove it as soon as possible. Your cooperation helps keep this project safe and legal for everyone.

## How to use it

### For agents (developers)

1. Browse the `games/` folder to find a game you want.
2. Load the JSON file for that game.
3. Query it using whatever logic you want—function calling, retrieval, or direct search.

Example structure:

```json
{
  "game": "Example Game",
  "version": "1.0",
  "rules": {
    "setup": "...",
    "turn": "...",
    "scoring": "..."
  }
}
```

### For humans

If you just want to read a ruleset, each JSON file is human-readable too. Open it in any text editor or just view it on GitHub.

## Contributing

If you want to add a new game or improve an existing ruleset:

1. Fork the repo.
2. Add or update the JSON file for your game.
3. Make sure it follows the same format as other files.
4. Submit a pull request.

Please keep the rules as neutral and factual as possible—no house rules, no interpretations, just the official rules as written. Also make sure the game is public domain or CC-BY licensed before submitting.

## License

This project is licensed under the MIT License.