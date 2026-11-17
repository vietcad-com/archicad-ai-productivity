# Archicad AI Productivity Tools: install note

An MCP server that lets Claude (or any MCP-capable AI client) work in your open Archicad project through the free **Tapir** add-on.

| Part | What it does | Can it change the model? |
|---|---|---|
| 1. Fire ratings | Finds every door with an empty Fire Rating (count per storey), inspects door types and host walls, proposes a rule, previews old → new, then writes all of them in one batch after you confirm. | Property values only, and only after you confirm. One undo step. Nothing is created, moved or deleted. |
| 2. Wall costs | Measures every wall (length, height, area, volume per wall type), agrees rates and assumptions with you, and writes a low/mid/high cost table to Excel. | No, read-only. |

## Requirements

- Archicad 27–30 (tested on Archicad 30 INT, Windows 11)
- Tapir add-on 2.0 or later
- Python 3.10+ and [uv](https://docs.astral.sh/uv/)
- An MCP client: Claude Desktop or Claude Code

## 1. Install Tapir

Download `TapirAddOn_AC30_Win.apx` (or the build for your Archicad version and platform) from
<https://github.com/ENZYME-APD/tapir-archicad-automation/releases>. Put it in
`C:\Program Files\Graphisoft\Archicad 30\Add-Ons\`, or load it with **Options › Add-On Manager**. Then restart Archicad.

## 2. Get the server

```
git clone <this repo> archicad-ai
cd archicad-ai
uv sync
```

## 3. Connect your AI client

**Claude Code**
```
claude mcp add archicad -- uv --directory C:\path\to\archicad-ai run nemetschek-ai
```

**Claude Desktop** (`%APPDATA%\Claude\claude_desktop_config.json`)
```json
{ "mcpServers": { "archicad": {
    "command": "uv",
    "args": ["--directory", "C:\\path\\to\\archicad-ai", "run", "nemetschek-ai"] } } }
```

Optional environment variables:
- `ARCHICAD_URL`: fixes the Archicad address (default: the server finds it on ports 19723–19744).
- `NEMETSCHEK_AI_OUT`: the folder for the Excel output (default: `Documents\nemetschek-ai`).

## 4. Use it

Open a project in Archicad. The API only runs while a project is open. Then ask, for example:

- *"List the doors with no fire rating, per storey."*
- *"Check their door types and host walls and propose the rating to apply."*
- *"Apply it."* The AI shows a preview table and waits for your OK before anything is written.
- *"I'm a QS. Price the walls: concrete 200 = 45 $/m², brick 110 = 28 $/m². Ask me what you need."*

Try changes on a copy of your project first. Edit › Undo reverts the fire-rating batch in one step.
