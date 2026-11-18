# Archicad AI Productivity Tools

**Nemetschek Design AI Productivity Challenge 2027 · VietCAD**

## The problem

Two everyday Archicad tasks are slow, repetitive and easy to get wrong:

1. **Doors with no fire rating.** Before issuing drawings someone has to find every door with an empty Fire Rating, check what kind of door it is and which wall it sits in, decide the rating and type it in, door by door, storey by storey.
2. **Early cost estimates for walls.** A quantity surveyor has to take off every wall, group them by type, apply a rate per m² and build a cost table in Excel, often for a design that will change next week.

## The solution

An MCP server that lets an AI assistant (Claude) work directly in the open Archicad project through the free Tapir add-on. The user asks in plain language. The AI calls nine small, purpose-built tools:

- **Part 1, fire ratings:** find → check → preview → *user confirms* → fix in one batch. Doors are highlighted red in Archicad, then green when fixed.
- **Part 2, wall costs:** measure every wall by type → agree rates and assumptions with the user → cost table (low/mid/high) and Excel file.

**Safe by design.** Every change is previewed with old → new values, and nothing is written without the user's confirmation (a one-time token). Only property values change; nothing is created, moved or deleted, and the batch is one Undo step. Wall costing is read-only. Names from the user's words are checked against the project, never guessed.

## Results on the Villa Patio sample (3 storeys, 387 walls, 24 doors)

| Task | By hand (estimate) | With the AI (measured) |
|---|---|---|
| Find and check 24 doors, decide a rule | ~30 min | {P1_FIND} |
| Preview and write the ratings | ~15 min | {P1_FIX} |
| Wall take-off and priced cost table in Excel | ~2–3 h | {P2} |
| **Total** | **~3 h** | **{TOTAL}** |

Tool calls themselves take well under a second each (find 0.2 s, write 0.5 s, measure 387 walls 1 s, price 0.6 s); the rest is the conversation. By-hand times are estimates for an experienced Archicad user.

## Value to customers

- Hours saved per project on routine checks and early estimates, with fewer missed doors.
- Works on any Archicad 27–30 project with Tapir; no model changes needed and nothing to learn beyond asking.
- The pattern (find → check → preview → confirm → fix) extends to any property audit: acoustic ratings, U-values, classifications.

**Open source:** github.com/vietcad-com/archicad-ai-productivity
