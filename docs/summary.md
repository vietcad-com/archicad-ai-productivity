# Archicad AI Productivity Tools

**Nemetschek Design AI Productivity Challenge 2027 · VietCAD**

## The problem

Two routine Archicad tasks are slow, repetitive and prone to errors:

1. **Doors with no fire rating.** Before issuing drawings, someone must find every door with an empty Fire Rating. They check its type and host wall, decide and enter its rating, door by door, storey by storey.
2. **Early wall cost estimates.** A quantity surveyor measures every wall, groups them by type, applies rates per m² and builds an Excel cost table. The design often changes next week.

## The solution

A software connection (an MCP server) lets the AI assistant Claude work directly in the open Archicad project through the free Tapir add-on. Users ask in plain language. Nine small tools handle specific tasks:

- **Part 1, fire ratings:** find → check → preview → *user confirms* → update in one batch. Doors are highlighted red in Archicad, then green when corrected.
- **Part 2, wall costs:** measure every wall by type → agree rates and assumptions with the user → cost table (low/mid/high) and Excel file.

**Controlled changes.** Every change is previewed with old → new values and requires user confirmation via a one-time token. Only property values change. Nothing is created, moved or deleted. One Undo step reverses the batch. Wall costing is read-only. Names in requests are checked against the project, never guessed.

## Results on the Villa Patio sample (3 storeys, 387 walls, 24 doors)

| Task | By hand (estimate) | With the AI (measured) |
|---|---|---|
| Find and check 24 doors, decide a rule | ~30 min | 27 s |
| Preview and apply the ratings | ~15 min | 48 s (including your confirmation) |
| Measure walls and create a priced Excel table | ~2–3 h | 25 s |
| **Total** | **~3 h** | **about 1 min 40 s** |

Tools generally take well under a second (find 0.2 s, write 0.5 s, measure 387 walls 1 s, price 0.6 s). The rest is conversation. Manual times are estimates for an experienced Archicad user.

## Value to customers

- Saves hours per project on routine checks and early estimates, with fewer missed doors.
- Works on any Archicad 27–30 project with Tapir. No model changes needed; users only need to learn how to ask.
- The steps (find → check → preview → confirm → fix) apply to any property audit: acoustic ratings, U-values, classifications.

**Open source:** github.com/vietcad-com/archicad-ai-productivity
