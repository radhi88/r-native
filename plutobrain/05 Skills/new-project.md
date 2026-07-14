# Skill: New Project

Create a new project inside `03 Projects/` by interviewing the user, then scaffolding the folder structure, CLAUDE.md, and COMMANDS.md.

## How It Works

1. Duplicate `03 Projects/(PROJECT TEMPLATE)/` into a new folder (this preserves `.obsidian` config and plugins)
2. Interview the user one question at a time (6 questions max)
3. Based on answers, create the folder structure and files
4. If the user doesn't have an answer yet, that's fine — use sensible defaults and leave TODOs in the CLAUDE.md for them to fill in later

## Interview Questions (Ask One at a Time)

Ask these questions conversationally using AskUserQuestion. Each answer can shape the next question. If someone says "I'm not sure yet" or gives a partial answer, don't push — just work with what you have.

### 1. What's the project called?
Used for the folder name under `03 Projects/`.

### 2. What is this project?
One paragraph. What are we building / doing / creating? Who is it for?

### 3. What does "shipped" look like?
What's the goal? What does success look like for this project? This becomes the prime directive in the CLAUDE.md — the thing Claude nudges toward.

### 4. Who else is involved?
Key people and their roles. Could be "just me" — that's fine.

### 5. What's the process from start to finish?
Walk me through how something goes from idea to done in this project. This is the big one — it creates the numbered project folders (inputs → process → outputs).

**If they're not sure:** Create a simple default structure:
- `00 Ideas/` (input)
- `01 In Progress/` (process)
- `02 Done/` (output)

Tell them they can restructure later as the process becomes clearer.

### 6. Any rules or conventions Claude should follow?
Things Claude should always or never do in this project. Specific formats, naming conventions, etc. Optional — skip if they don't have any yet.

## After the Interview

### Step 1: Duplicate the template
```bash
cp -R "03 Projects/(PROJECT TEMPLATE)" "03 Projects/[Project Name]"
```

### Step 2: Clean up the template artifacts
- Remove the `00 Duplicate/` folder (it was only for manual duplication)
- Remove the placeholder `CLAUDE.md` (we're writing a real one)
- Remove the placeholder `COMMANDS.md` (we're writing a real one)

### Step 3: Create project-specific folders
Based on the process answer, create numbered folders that follow the input → process → output flow. Then add the standard utility folders at the end with the next available numbers:

- `XX System/` — scripts, config, reusable processes
- `XX Skills/` — skill markdown files (NOT Claude Code skills)
- `XX Attachments/` — images, screenshots, PDFs
- `XX Iteration Logs/` — notes on what to improve

**Note:** The template already creates `04 System/`, `05 Skills/`, and `06 Attachments/` — but the numbers may need to shift depending on how many project-specific folders are created. Remove the template defaults and recreate with correct numbering.

### Step 4: Write CLAUDE.md
Use this structure. Fill in what you learned from the interview. For anything the user wasn't sure about, add a `<!-- TODO: fill this in -->` comment so they can find and complete it later.

```markdown
# [Project Name]

[One paragraph: what this project is, from question 2]

## Claude's Role

[What Claude does in this project. Be specific — not "help me ship" but the actual job based on what the project needs.]

[Prime directive based on question 3. Follow this format:]
If a session is drifting without moving toward [shipped output], nudge me back: "[contextual nudge message]"

## Process

[Step-by-step process from question 5. Numbered steps showing how work flows from start to finish. If they weren't sure, write a simple default and add a TODO.]

## Key People

[From question 4. Name — role/what they do. Skip section if solo project.]

## Folder Structure

[List every folder with a short description of what goes in it]

## Rules & Conventions

- **`(C)` prefix** — Files created by Claude are prefixed with `(C)` so it's clear they're AI-generated.
- **Editing rule** — Before editing any file without the `(C)` prefix, ask for permission first.
- **Skills** — All reusable scripts/automations are saved as markdown files in the Skills folder, NOT as Claude Code skills.
[Add any project-specific rules from question 6]

## Current Status

> **Last updated:** [today's date]
> **Status:** Just created — getting started.

<!-- TODO: Update this as the project progresses -->
```

### Step 5: Write COMMANDS.md
List every skill and command available in this project. Start with the defaults:

```markdown
# Commands & Skills

Quick reference for all available skills and commands in this project.

## Skills (in XX Skills/)
_No project-specific skills yet._

## Commands
_No project-specific commands yet._
```

### Step 6: Update the root CLAUDE.md
The PlutoBrain root `CLAUDE.md` has two sections that need to stay in sync with active projects:

1. **Folder Structure** — Add the new project folder under the `03 Projects/` tree with a short description.
2. **My Current Projects & Overviews** — Add a new subsection for the project using this format:

```markdown
### [Project Name] — `03 Projects/[Project Name]/`
**Status:** Just created
[One-line description from question 2]
```

This keeps the operating system's top-level context aware of every active project so Claude always knows what's in play.

### Step 7: Confirm to the user
Show them:
- The folder structure that was created
- A summary of the CLAUDE.md
- Remind them they can update the CLAUDE.md and folder structure anytime as the project evolves
- If any sections have TODOs, point those out so they know what to fill in later
