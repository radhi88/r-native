---
name: canvas
description: Generate or modify Obsidian Canvas (.canvas) files for visual maps of vault content. Supports adding notes, images, PDFs, text cards, and labeled zones. Mirrors claude-obsidian's /canvas command.
---

# /canvas

## Purpose
Obsidian's Canvas is a freeform visual workspace — nodes are notes, images, PDFs, or text cards; edges are connections; zones group related nodes. `/canvas` lets you generate or extend canvases programmatically without manually placing every node.

## When to invoke
- `/canvas` — open or create the default vault map canvas
- `/canvas new <name>` — create a new canvas
- `/canvas add note <wikilink>` — add a vault note as a card
- `/canvas add text "<content>"` — add a text card
- `/canvas add image <path-or-url>` — add an image node
- `/canvas add pdf <path>` — add a PDF preview node
- `/canvas zone <name>` — add a labeled zone (group)
- `/canvas connect <node-a> <node-b>` — draw an edge between two nodes
- `/canvas from <topic>` — auto-build a canvas of all notes related to topic (uses index.md + wikilinks)

## Storage
Canvases live at `00 Notes/canvases/<name>.canvas` by default. The default vault map is at `00 Notes/canvases/Wiki Map.canvas` (pre-seeded; see step 0 below).

## Canvas JSON spec (Obsidian format)

```json
{
 "nodes": [
 {
 "id": "<unique-id>",
 "type": "text" | "file" | "link" | "group",
 "x": <number>,
 "y": <number>,
 "width": <number>,
 "height": <number>,
 "color": "1" | "2" | "3" | "4" | "5" | "6", // 1=red 2=orange 3=yellow 4=green 5=cyan 6=purple
 // For text: "text": "<markdown>"
 // For file: "file": "path/to/note.md"
 // For link: "url": "https://..."
 // For group: "label": "<zone label>"
 }
 ],
 "edges": [
 {
 "id": "<unique-id>",
 "fromNode": "<node-id>",
 "fromSide": "right",
 "toNode": "<node-id>",
 "toSide": "left"
 }
 ]
}
```

## Behavior

### Step 0 — On first ever invocation: seed the vault map canvas
If `00 Notes/canvases/Wiki Map.canvas` does not exist, create a starter canvas:
- Center node: "You Mind" (text card)
- Surrounding nodes (file links): `CLAUDE.md`, `GOALS.md`, `patterns.md`, `hot.md`, `index.md`
- Outer ring: project folder representations ([your-content-project], etc.)
- Color code: meta files = purple, projects = green, journals = cyan, reviews = orange

### Step 1 — Parse subcommand
Determine which sub-action you is invoking and load the target canvas if it exists.

### Step 2 — Compute auto-layout when adding nodes
Don't pile new nodes on top of existing ones. Default placement strategy:
- New text/note cards: scan the canvas, place at the next free 350×200 cell, starting from (x=100, y=100), expanding rightward then downward.
- Connected nodes (with `connect`): place the new node 400px right of the source node.
- Zone labels: place above the cluster of nodes they group; auto-resize to encompass the cluster.

### Step 3 — Write or update the canvas JSON
Generate UUIDs for new nodes/edges. Preserve existing nodes/edges when modifying. Write atomically (write to a temp file then rename to avoid Obsidian seeing a half-written file).

### Step 4 — Update index.md
Add an entry under `## 00 Notes/canvases/` with the canvas name.

### Step 5 — Confirm
Print to you:
- Canvas path
- Number of nodes added / total nodes
- Layout summary (zones, clusters)
- Tip: open the canvas in Obsidian to view (`Cmd/Ctrl+Click` to navigate to file nodes)

## Color coding convention (locked across canvases)
| Color | Number | Usage |
|---|---|---|
| Purple | 6 | Meta files (CLAUDE.md, GOALS.md, hot.md, etc.) |
| Green | 4 | Active projects |
| Cyan | 5 | Notes, journals, daily entries |
| Orange | 2 | Reviews, retrospectives |
| Yellow | 3 | Ideas, in-flight work |
| Red | 1 | Pattern flags, warnings, blockers |

## Permissions
- ✅ Create new canvases under `00 Notes/canvases/`
- ✅ Modify canvases you explicitly invokes
- ✅ Update `index.md` with canvas entries
- ❌ Don't auto-modify existing canvases unless the command explicitly targets them

## Notes
- Obsidian Canvas is a built-in Obsidian feature (no community plugin required)
- Canvases work with the file: link node type — clicking a node in Obsidian opens the linked file
- For very large canvases (50+ nodes), generate in zones to avoid visual clutter
