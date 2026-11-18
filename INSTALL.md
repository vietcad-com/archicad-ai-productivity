# Archicad AI Productivity Tools: installation guide

This software connection, called an MCP server, lets Claude (or any AI client that supports MCP) work in your open Archicad project through the free **Tapir** add-on.

| Part | What it does | Can it change the model? |
|---|---|---|
| 1. Fire ratings | Finds every door with an empty Fire Rating and counts them by storey. Checks door types and the walls that contain them. Proposes a rule and previews old → new values. Applies all changes at once after you confirm. | Only property values, and only after you confirm. You can reverse the changes in one undo step. Nothing is created, moved or deleted. |
| 2. Wall costs | Measures every wall's length, height, area and volume by wall type. Agrees rates and assumptions with you, then exports a low/mid/high cost table to Excel. | No. It only reads the model. |

## Requirements

- Archicad 27–30 (tested on Archicad 30 INT, Windows 11)
- Tapir add-on 2.0 or later
- Python 3.10+ and [uv](https://docs.astral.sh/uv/)
- An MCP client: Claude Desktop or Claude Code

## 1. Install Tapir

Download `TapirAddOn_AC30_Win.apx` (or the version for your Archicad version and operating system) from
<https://github.com/ENZYME-APD/tapir-archicad-automation/releases>. Put it in
`C:\Program Files\Graphisoft\Archicad 30\Add-Ons\`, or load it with **Options › Add-On Manager**. Then restart Archicad.

## 2. Download and install the server

```
git clone https://github.com/vietcad-com/archicad-ai-productivity archicad-ai
cd archicad-ai
uv sync
```

## 3. Connect Claude Code or Claude Desktop

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

Optional settings, supplied as environment variables:

- `ARCHICAD_URL`: sets a specific Archicad address (by default, the server finds it on ports 19723–19744).
- `NEMETSCHEK_AI_OUT`: sets the folder for Excel files (default: `Documents\nemetschek-ai`).

## 4. Use it

Open a project in Archicad. The connection uses the API, which only runs while a project is open. You can then ask:

- *"List the doors with no fire rating, per storey."*
- *"Check their door types and host walls and propose the rating to apply."*
- *"Apply it."* The AI shows a preview table and waits for your approval before applying any changes.
- *"I'm a QS. Price the walls: concrete 200 = 45 $/m², brick 110 = 28 $/m². Ask me what you need."*

Try changes on a copy of your project first. Edit › Undo reverses all fire-rating changes in the batch in one step.
