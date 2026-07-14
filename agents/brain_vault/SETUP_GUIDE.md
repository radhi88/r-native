# PlutoBrain — Setup Guide

> Build a real AI second brain on your machine. Obsidian + Claude Code + 14 skills + a self-awareness layer. **No coding required.** Follow these steps in order.

---

## What you'll have when you finish

- A working **Obsidian vault** structured for capture, linking, and retrieval
- **Claude Code** running in your terminal, reading and writing to your vault directly
- **14 custom skills** (`/sync`, `/ingest`, `/query`, `/save`, `/refine`, `/lint`, `/canvas`, `/autoresearch`, `/pre-mortem`, `/weekly-update`, `/deep-context-fill`, `/new-project`, `/brain-setup`, `/divergence-check`)
- A **two-Claude workflow** — Strategist Claude in terminal + Executor Editor Claude inside Obsidian
- A **patterns library** that flags your recurring behaviors back at you (the differentiator)
- A daily / weekly cadence that compounds for years

Total setup time: **~30 minutes** for the install. Customization is ongoing.

---

## STEP 0 — What you need

- A computer (Mac, Windows, or Linux)
- A **Claude account** with **Pro plan ($20/mo)** OR API credits at console.anthropic.com
- Obsidian (free) — you'll install this in Step 1
- Node.js (free) — you'll install this in Step 4
- About 30 minutes

---

## STEP 1 — Install Obsidian

1. Go to **obsidian.md**
2. Click Download for your OS
3. Run the installer (defaults are fine)
4. Open Obsidian for the first time

**Don't create a vault yet.** We'll use this template as your vault.

---

## STEP 2 — Drop this template as your vault

1. Move the entire `PlutoBrain` folder into your `Documents/` folder (or wherever you want your second brain to live).
2. Rename it if you want — `my-brain`, `brain`, `kb`, whatever feels right. Lowercase, no spaces.
3. In Obsidian, click **"Open folder as vault"** and point to your renamed folder.
4. **Note the path.** You'll need it later. Probably looks like `~/Documents/my-brain` (Mac/Linux) or `C:\Users\YourName\Documents\my-brain` (Windows).

You're now looking at your vault. Take a tour:
- `00 Notes/` — entity notes (people, places, concepts, etc.) and source material
- `01 Journals/` — your daily journal
- `02 Chess Moves (Long-Term Planning)/` — strategic multi-step plans
- `03 Projects/` — active projects (each with its own `CLAUDE.md`)
- `04 Reviews/` — weekly / monthly / yearly reflections
- `05 Skills/` — 14 custom skills Claude can run
- `inbox/` — universal capture zone for stuff to route later
- `media/` — images, PDFs, audio
- Root files: `CLAUDE.md` (instructions), `GOALS.md`, `patterns.md`, `hot.md`, `index.md`, `_blocklist.md`, `log.md`

---

## STEP 3 — Install Node.js

Claude Code runs on Node.js. We need it before we can install Claude Code.

1. Go to **nodejs.org**
2. Download the **LTS** version
3. Run the installer (defaults are fine — UNCHECK any "Install build tools" box; we don't need it)
4. Open a fresh terminal (Mac: Terminal app. Windows: Windows Terminal or PowerShell.)
5. Verify by typing:
 ```
 node --version
 npm --version
 ```
 Both should print version numbers.

If they don't: close the terminal, open a fresh one, try again. Most "command not found" errors are because the terminal session was opened before Node was installed.

---

## STEP 4 — Install Claude Code

In your terminal, type:

```
npm install -g @anthropic-ai/claude-code
```

`-g` means install globally so you can run it from anywhere.

Verify:
```
claude --version
```

If you see a version number, you're good.

---

## STEP 5 — First run: point Claude Code at your vault

In your terminal:

```
cd ~/Documents/my-brain (or whatever you named your vault)
claude
```

First time, it'll prompt you to log in. Choose your Claude Pro account. Browser opens, you click allow, come back to the terminal.

Now you're in Claude Code. Try:

```
What folders do I have in this vault, and roughly what's in each?
```

Claude reads your entire vault and gives you a tour. **You're now running an AI on your second brain.** Welcome.

To exit Claude Code: type `/exit` or press Ctrl+C twice.

---

## STEP 6 — Run the brain-setup skill (the most important step)

The vault's three foundation files — `CLAUDE.md`, `GOALS.md`, and `patterns.md` — are what Claude reads at the start of every session. They tell Claude who you are, what you're working toward, how you communicate, your strengths and weaknesses, the patterns you want flagged, and your one-sentence prime directive.

**You don't fill these in manually.** You run a skill that interviews you, then writes them in your voice.

### Run the interview

In Claude Code:
```
run the brain-setup skill in 05 Skills
```

This is a **10-round, 30-45 minute interview**. It covers:

1. Identity & life context — who you are, where you are, what's happening right now
2. Mission, purpose, what energizes you — the big-arrow direction
3. Communication preferences — how you want Claude to talk to you (blunt, balanced, supportive)
4. Operating style & stress behavior — when you're sharp, what you do under pressure
5. Strengths — your unfair advantages
6. Failure modes — captured as named patterns Claude can flag back at you ("The Tool Trap," "The Yes Reflex")
7. 1-year goals — wealth, career, health, relationships, skills, with real numbers
8. 3-year & 10-year vision — the identity you're building toward
9. Gating conditions & key relationships — what has to be true before X, the people who shape your decisions
10. Active projects, daily rhythm, prime directive — what you're working on, when you work, the ONE thing this brain must do well

After all 10 rounds, Claude generates `CLAUDE.md`, `GOALS.md`, and `patterns.md` — shows them to you for review — and only writes them after you confirm.

**Quick version:** if you don't have 30-45 minutes, run `run the brain-setup skill express`. It does Rounds 1, 3, 5, 8, 10 only (~10-15 min). Resulting brain will be shallower until you run a full session later.

### Why this matters

The depth of this interview determines the quality of every future Claude session in this vault. A shallow setup produces generic AI responses. A deep, honest setup produces a thinking partner that actually knows you.

After this, restart Claude Code (`/exit`, then `claude`) so it picks up your new files.

---

## STEP 7 — Start your daily note habit

In Claude Code (with vault open):

```
create today's daily note from the template
```

You now have a daily note at `01 Journals/daily/YYYY-MM-DD.md`. Spend 2 minutes filling in:
- Today's primary intent
- Top 3 priorities

At end of day, fill in the reflection section.

**Do this for 30 days before deciding if it works.** The compound returns kick in after week 3.

---

## STEP 8 — Start using the skills

Pick one demo to try right now:

### Easiest: `/save`
After any meaningful Claude conversation:
```
/save
```
Claude saves the conversation as a structured wiki note in `00 Notes/saved-chats/` with frontmatter, links, and a TL;DR. You can reference it later.

### Highest impact: `/sync`
Drop something into `inbox/` (a screenshot, a note from your phone, an exported chat). Then:
```
/sync
```
Claude routes the inbox item, extracts entities (people, places, concepts), creates wikilinks to existing notes, makes stub notes for new ones. **This is the killer feature.**

### Most mind-blowing: `/query`
Ask a question about your own notes:
```
/query what have I been thinking about regarding [topic]?
```
Claude searches the vault, synthesizes a cited answer, and FILES the answer back as a note in `00 Notes/saved-chats/`. Your explorations compound — every query becomes a permanent reference.

---

## STEP 9 — Your first project

In Claude Code:
```
run the new-project skill in 05 Skills
```
Claude walks you through creating your first project under `03 Projects/`. You'll get a project folder with its own CLAUDE.md, an inputs/process/outputs structure, and the project added to your vault root CLAUDE.md.

---

## STEP 10 — Weekly cadence

Every Sunday (or whenever your week ends), in Claude Code:

```
/weekly-update
```

Claude refreshes `hot.md`, scans for stale references in `CLAUDE.md` and project CLAUDE.md files, surfaces patterns from your daily notes, and flags open loops.

This is the keystone habit. **5 minutes a week to keep the system alive.**

---

## STEP 11 — Add your own patterns

After 2-4 weeks of daily notes, run:

```
/refine patterns.md
```

Claude walks through your notes and proposes patterns it's observing — recurring behaviors, repeated frustrations, building-vs-finishing tendencies, etc. You approve which ones land. Once added, future Claude sessions will surface them by name when relevant.

**This is what turns the vault from a filing cabinet into a thinking partner.**

---

## STEP 12 — Customize and own it

PlutoBrain is a starting point. The power compounds when you customize:

- **Write your own skills** in `05 Skills/`. Claude can help — `help me write a skill that does X`.
- **Add Obsidian plugins** that help your workflow.
- **Create project templates** specific to your work.
- **Adjust CLAUDE.md communication preferences** until Claude responds the way you want.
- **Track your own patterns** in `patterns.md`.

The vault becomes more yours every week. After 3-6 months it's irreplaceable.

---

## Bonus — Mobile capture (Claude Dispatch)

1. Install **Claude Desktop App** (claude.ai/download)
2. Install **Claude phone app** (App Store / Play Store)
3. In desktop, open **Dispatch**, connect from phone
4. From phone, talk to Claude: *"I want you to use the folder at ~/Documents/my-brain as your permanent workspace."*
5. Now ask Claude anything from your phone — it works in your vault remotely.

Tip: turn on Claude phone notifications. Voice-memo your captures into `inbox/` while driving.

---

## Bonus — Multi-device sync (Obsidian Sync or git)

Two options:

### Option A — Obsidian Sync ($8/mo)
- obsidian.md/sync
- Settings → Core Plugins → Sync → ON
- Easiest. Encrypted. Just works.

### Option B — Git (free, technical)
- Initialize the vault as a git repo
- Push to private GitHub
- Pull on each device
- Free forever. Requires you to actually `git pull` and `git push`.

---

## You're done with setup

Now use it. Daily notes daily. `/sync` weekly. `/weekly-update` weekly. Build out projects. Add patterns. The system rewards consistency more than perfection.

If something breaks or you have questions, the README has troubleshooting + community links.
