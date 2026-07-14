# Skill: Brain Setup

**The most important skill in this vault.** This is the interview that turns a blank PlutoBrain into a personal AI second brain that actually knows the user. Run it first, run it thoroughly, and don't rush. The output of this skill is the foundation every other skill builds on. If this skill produces a thin CLAUDE.md, GOALS.md, and patterns.md, every future Claude session in this vault will be generic. If it produces deep, specific, voice-tuned files, the user will have a thinking partner that genuinely understands them.

## When to Use

- User just cloned the PlutoBrain template and needs to set up their vault
- `CLAUDE.md`, `GOALS.md`, or `patterns.md` contain only `{{REPLACE}}` placeholders
- User explicitly asks to set up, initialize, or personalize their brain
- User says some variant of "make this mine" / "set up my brain" / "interview me"

If `CLAUDE.md` already has real content, ask the user whether they want to start fresh, build on what's there, or just fill the gaps (recommend `/deep-context-fill` for the third case).

## The Bar

The output of this skill should be specific enough that a stranger reading the resulting `CLAUDE.md` could:
1. Describe the user's life situation in 2 sentences
2. Predict roughly how the user would react to common decisions
3. Name 2 patterns the user wants flagged
4. Quote the user's prime directive from memory

If the output isn't that specific, the interview wasn't deep enough.

## Tone & Pacing

- **Warm but probing.** This is a conversation about who they are, not a form to fill out.
- **One round at a time.** After each round, summarize what you captured in 2-3 lines so they can correct it before moving on.
- **Ask one question per turn UNLESS the questions naturally cluster** (e.g. "what do you do for work / how long / how does it pay?" — those flow as one).
- **Probe shallow answers ONCE.** If they say "I want to be successful" — ask what success looks like in numbers. If they still say something vague, write what they gave you and move on. Don't interrogate.
- **Mirror their language.** If they say "I build cool shit," write "build cool shit." Don't sanitize. The voice in CLAUDE.md should sound like them, not a LinkedIn bio.
- **Don't fabricate.** If a section gets a thin answer, the section stays thin. Padding is worse than gaps because it gives Claude false confidence.
- **Set expectations up front.** "This will take 30-45 minutes. We're going to go deep — the more honest you are, the better Claude gets at being your thinking partner. Want to do it now?"

## Phase 0: Scan & Confirm

Before any questions:

1. Read the vault structure:
   ```bash
   ls -d */
   ls -d "03 Projects"/*/ 2>&1 || echo "No projects yet"
   ```
   Record which system folders exist and what's already in `03 Projects/`.

2. Read whatever exists of `CLAUDE.md`, `GOALS.md`, and `patterns.md`. If any has real content, ask the user how to proceed (fresh / append / gap-fill).

3. Confirm with the user:
   > "I'm about to interview you across 10 rounds — covers identity, mission, communication preferences, goals at 1/3/10-year horizons, current projects, key relationships, your operating style, strengths, weaknesses, and the rules Claude follows in this vault. Takes 30-45 min. Outputs land in CLAUDE.md, GOALS.md, and patterns.md. Ready?"

If they want a faster version, run a 4-round express interview (Rounds 1, 3, 5, 8 only) and tell them the resulting brain will be shallower until they run a full session later.

## Phase 1: The 10-Round Interview

After each round, summarize what you captured. Move on only after they confirm or correct.

---

### Round 1 — Identity & Life Context

The basics + the situation. This grounds everything else.

- **What do you want to call this vault?** (default: the folder name)
- **Name, age, location.** First name is fine. Location can be city/state or just region.
- **What do you do for work or income?** Job, side hustles, school, military, between things — whatever's true.
- **What's your current life stage?** Single / dating / married / kids / no kids / caretaker / other.
- **Anything important about how your brain works?** ADHD, autism, anxiety, depression, neurodivergence, or just "I think in pictures." This shapes how Claude communicates with you.
- **What's the big thing happening in your life right now?** A move, a launch, a recovery, a transition — something that colors every day.
- **Faith / belief system?** Optional, but if it shapes your decisions Claude should know.
- **What do you drive / where do you live?** Quick lifestyle context. Optional.

**Goal:** A specific, lived-in identity paragraph. Not a profile. A snapshot.

---

### Round 2 — Mission, Purpose, What Energizes You

Why are you alive doing this? Don't let them off the hook with platitudes.

- **What's the one thing you're trying to build or become?** The big-arrow direction. Not the goal — the direction.
- **What do you love doing?** The activities you'd do for free. The things that energize you instead of drain you.
- **What do you refuse to do?** Hard lines. Values. The work you won't take, the people you won't work with, the compromises you won't make.
- **What problem are you obsessed with?** The thing you can't stop thinking about, even when you're supposed to be relaxing.
- **If money wasn't an issue, what would you spend your time on?** This often reveals the real mission underneath the day job.
- **Who do you want to become in 10 years that you aren't yet?** Identity-level, not skill-level.

**Goal:** Capture the thing that drives them. This goes into "What this brain is for" in CLAUDE.md AND informs the 10-year horizon in GOALS.md.

---

### Round 3 — Communication Preferences & Operating Style

How does Claude actually talk to them. Get this wrong and every future response is off.

Use **AskUserQuestion** for the communication style:

> **How should Claude communicate with you?**
> - **Blunt and direct** — challenge me, don't sugarcoat, call me out when I'm wrong
> - **Supportive but honest** — encourage me, but flag real issues when they matter
> - **Balanced** — match my energy, be direct when it counts, soft when I'm struggling
> - **Other** — describe your preference

Then open-ended:

- **Should Claude push back when you're wrong?** And if so, how hard?
- **What annoys you in AI responses?** (e.g. "10 options when I want one," "hedge words," "pretending it doesn't have an opinion")
- **Should Claude end responses with a suggested next action?** Y/N.
- **When you're stuck, do you want Claude to ask probing questions or just give you the answer?**
- **When you're stressed, what response style do you actually need?** (e.g. "more direct, fewer caveats" vs. "slow it down, ask me what I'm feeling")
- **How should Claude handle creating files?** (e.g. prefix `(C)` on AI-generated files, never edit existing user notes without asking)
- **Anything Claude should NEVER do in this vault?** (e.g. "never write in my voice without asking," "never make health recommendations")

**Goal:** Concrete, actionable rules. "Don't be wishy-washy" → "If I ask for an opinion, give one. Don't say 'it depends.'"

---

### Round 4 — Operating Style & Stress Behavior

How do you actually work and decide? When does it go sideways?

- **When are you sharpest?** Time of day, day of week, after what trigger (workout / coffee / morning / late night).
- **When are you weakest?** When does your judgment degrade?
- **How do you decide when something is hard?** Do you over-research, snap-judge, ask a friend, journal it, sleep on it?
- **What does your stress response look like?** Withdrawal? Lashing out? Doom-scrolling? Over-spending? Working harder to avoid feeling? Be honest — Claude needs to flag this when it's happening.
- **What triggers procrastination for you?** Specific patterns — "tasks that need a phone call," "work I'm scared people will judge."
- **What do you default to when you don't want to do the actual thing?** (e.g. "rebuilding my Notion," "researching tools instead of using them")
- **How do you self-regulate?** Workout? Walk? Talk to someone? Music?

**Goal:** Specific behavioral patterns Claude can name back to you when you're doing them. Generic answers ("I procrastinate") are useless. Specific ones ("I research tools instead of using them when the work feels exposing") are gold.

---

### Round 5 — Strengths

What are you actually great at?

- **What's your unfair advantage?** The thing you do better than 95% of people. Not flattering — accurate.
- **What do people consistently come to you for?** External validation of strength is more reliable than self-perception.
- **What can you do for 4 hours and feel energized, not drained?**
- **What do you pick up faster than others?**
- **What's a skill you've built that's underrated by you?**

**Goal:** Honest strengths Claude can lean into. If you're great at writing but bad at finance, Claude should suggest writing-leveraged paths to financial goals, not generic advice.

---

### Round 6 — Weaknesses, Blind Spots, Recurring Failure Modes

The hardest round. Most users sandbag this. **Push gently for honesty — this section is the difference between a generic AI and a real second brain.**

- **What's the pattern that's bitten you 3+ times?** Specific. Real. Recent.
- **What do you know you should do but consistently don't?**
- **What feedback have you gotten more than once that stings because it's true?**
- **What do you avoid?** Confrontation, finance review, certain people, certain feelings?
- **What's a goal you've set 3+ times and not achieved?** Why?
- **What do you do when you start something new instead of finishing what's open?**
- **What's a shadow trait — something you don't admit but probably do?**

**Goal:** A list of named patterns. Each one becomes an entry in `patterns.md`. The next time the user starts behaving that way, Claude says "this looks like the [name] pattern from `patterns.md` — want to talk about it?"

**Capture as named patterns** like:
- *The Tool Trap* — "When I'm scared of the work I rebuild my system instead of doing the work."
- *The Yes Reflex* — "I say yes to opportunities to feel chosen, then resent them."
- *The Open Loop Pile* — "I start projects to feel momentum but never close any."

---

### Round 7 — 1-Year Goals (Concrete, Measurable, Gated)

Goals at the closest horizon. Push for specifics.

For each life area, ask for a concrete goal:

- **Wealth / income** — a number and a date. "Hit $X net worth by Q3 from $Y primary + $Z side."
- **Career / work** — output goal. "Ship 3 products with revenue" / "Land first 10 clients" / "Get promoted to Senior."
- **Health** — measurable. "Run 5K under 25:00 by August" / "Maintain 175 lb / sleep 7+ hrs avg."
- **Relationships** — process goal. "Date with intent" / "Call parents weekly" / "Reconnect with 1 old friend per month."
- **Skills / learning** — concrete. "Conversational Spanish" / "Ship 1 OSS project" / "Read 12 books."

**Push gently against vagueness:**
- "Make more money" → "How much, by when, from where?"
- "Get healthier" → "What does that look like? A number, a habit, a milestone?"
- "Be a better partner" → "What's the behavior change you'd actually do?"

If they refuse to specify, write what they gave you. Note it as `[loose]` so Claude can revisit later.

**Also ask:** for each goal, "where are you today?" — current state with real numbers. The gap between today and goal is what Claude will reason about.

---

### Round 8 — 3-Year Vision & 10-Year North Star

Less precision, more identity.

**3-year:**
- **What does the version of you 3 years from now look like?** Income level, lifestyle, location, who you're with, what you do all day, what shape you're in, what you're known for.
- **What chess moves does today-you need to make to become that person?** Even rough ones — these become entries in `02 Chess Moves (Long-Term Planning)/`.

**10-year:**
- **What's the life you're building toward?** Bigger picture. Career arc, financial state, family, location, identity.
- **What would have to be true for you to consider those 10 years a success?**
- **What would feel like failure?**

**Goal:** Two paragraphs. They go in GOALS.md under their respective horizons. The 3-year shapes Chess Moves. The 10-year shapes the prime directive.

---

### Round 9 — Gating Conditions & Key Relationships

Things that have to be true before X. People who shape decisions.

**Gating conditions:**
- **What's a goal you should NOT pursue until certain conditions are met?** (e.g. "no expensive car until monthly income is 5x expenses," "no quitting day job until 6 months expenses saved + 50% income from side work for 3 months")
- **What are you currently chasing whose conditions probably aren't met?** Honest answer.

**Relationships:**
- **Who are the 3-5 people who shape your decisions?** Names + relationship + why they matter.
- **Who do you go to for what?** (e.g. "I go to [name] for tough-love business advice; to [name] for emotional reality checks")
- **Anyone Claude should know about for context?** (e.g. business partner, therapist, mentor, parent, ex, kid)

**Goal:** Gating conditions go in GOALS.md under "Gating conditions." Key relationships go in CLAUDE.md and stub notes get created for each in `00 Notes/people/`.

---

### Round 10 — Active Projects, Daily Rhythm, Prime Directive

Wrap up: what you're working on, when you work, and the ONE thing this brain must do well.

**Active projects:**
- **What are you actively working on?** Each gets a project folder under `03 Projects/`.
- For each: one-sentence description, current status (planning / building / launching / maintaining / on-hold), the next obvious move.
- **Reference projects:** any external codebases or businesses you want documented in the vault for context, even if the actual work happens elsewhere.

**Daily / weekly rhythm:**
- **When do you usually work?** Mornings / late nights / scattered / on a clock.
- **When do you reflect?** Daily journal / weekly review / quarterly only / never.
- **What's your weekly cadence?** When does the week start for you? When do you review?
- **What should the start of every Claude session look like?** (e.g. "tell me what's hot, what I'm avoiding, and what I should ship today")

**Prime directive (most important question of the interview):**
- **If Claude could only do ONE thing well in this vault, what should it be?**

Examples:
- "Tell me when I'm running away from the work."
- "Make sure I'm spending my hours on the highest-leverage thing."
- "Catch me when I'm starting a new project before I finish the old one."
- "Help me ship without overthinking."
- "Be my external accountability for the goals I keep setting and missing."

**Goal:** A single sentence that becomes the opening of CLAUDE.md. Every future session, Claude reads this first.

---

## Phase 2: Generate the Three Foundation Files

After all 10 rounds, generate THREE files (not just CLAUDE.md). Show them to the user one at a time, get approval, then write.

### File 1 — `CLAUDE.md`

Use the template structure already in the vault root. Write each section in the user's voice. Keep the existing scaffolding (capture & routing, immutable layers, skills available, two-Claude workflow, etc.) — it's vault infrastructure that doesn't need personalization. Replace ONLY the personalization sections:

- One-sentence vault description (top)
- "Who I am" (Round 1, Round 4 stress behavior summary)
- "What this brain is for" (Round 2 mission)
- "Communication preferences" (Round 3)
- "Strengths / weaknesses" (Rounds 5 & 6 brief)
- "Active projects" (Round 10)
- "Reference projects" (Round 10)
- **NEW SECTION** at the top: "Prime directive" (Round 10) — single sentence, bolded
- **NEW SECTION**: "Key relationships" (Round 9) — short list with stub note links
- **NEW SECTION**: "Daily rhythm" (Round 10) — when they work, when they reflect, what session-start should look like
- **NEW SECTION**: "Hard rules" (Round 3 NEVERs) — bulleted list of things Claude must not do

### File 2 — `GOALS.md`

Replace ALL placeholder sections with real content from Rounds 7, 8, 9.

- 1-year horizon (Round 7) — Wealth, Career, Health, Relationships, Skills sections, each with concrete numbered goals + "where I am today"
- 3-year horizon (Round 8) — vision paragraph
- 10-year horizon (Round 8) — vision paragraph
- Gating conditions (Round 9) — bulleted list
- ARCHIVE — empty for now

### File 3 — `patterns.md`

Replace placeholder content with the named patterns from Round 6. Each pattern gets:

- A short, memorable name (3-5 words)
- The behavioral signature (what it actually looks like)
- The trigger (when does it happen)
- What Claude should do when it sees it

Example entry:

```markdown
## The Tool Trap
**Signature:** When work feels exposing or scary, I rebuild my system instead of doing the work — new template, new tool, new structure.
**Trigger:** Anything where someone might judge the output. Often hits before I publish or send.
**Claude's job:** When you see me in tool-rebuild mode and there's open ship-able work, name this pattern explicitly and ask: "Are you avoiding the actual work?"
```

Also fold in: stress-default behaviors from Round 4, recurring failure modes from Round 6.

### Optional File 4 — `hot.md` initial seed

If they have an active priority right now, write a short opening note in `hot.md`:

```markdown
# Hot Cache

> Session cache. Auto-maintained by `/sync` and `/weekly-update`.

## Last updated
[today's date] — Initial setup. Active focus: [top 1-2 things from Round 10].

## Currently on
- [project 1]
- [project 2]
```

## Phase 3: Review, Confirm, Write

Show the user each file in turn. Ask:

> "Here's `CLAUDE.md` based on our interview. Read it through — anything that sounds wrong, off-voice, or thin?"

Make targeted edits. Don't regenerate the whole file unless they want a major direction change. Loop until they confirm.

Repeat for `GOALS.md` and `patterns.md`.

Only WRITE the files after explicit confirmation on each.

## Phase 4: Suggest Next Steps

After writing, tell the user:

1. **Your brain is live.** Claude reads these three files at the start of every session in this vault. Specifically: `CLAUDE.md` first, then `hot.md`, then `GOALS.md`, then `patterns.md`. The prime directive grounds every response.

2. **Set up your first project.** Run `/new-project` to create your first active project under `03 Projects/`. Each project gets its own `CLAUDE.md` so Claude has project-level context.

3. **Start your daily note tonight.** Run "create today's daily note" to spin up `01 Journals/daily/YYYY-MM-DD.md`. 2 minutes morning + 2 minutes night. Do this for 30 days minimum before deciding if it works.

4. **In a week, run `/deep-context-fill`.** That skill scans the notes you've actually written and fills any gaps in `CLAUDE.md` based on real evidence (not just the interview).

5. **In a month, run `/refine patterns.md`.** That walks your daily notes and proposes additional patterns based on what you've actually been writing about.

6. **Run `/weekly-update` every Sunday.** 5 minutes. Refreshes `hot.md`, surfaces patterns, flags stale references, asks about open loops. This is the keystone habit.

## Edge Cases

- **User asks for express version.** Run Rounds 1, 3, 5, 8, 10 only. Mark `CLAUDE.md` with a note that a full setup is recommended within a week.
- **User goes off-topic mid-interview.** Capture what's relevant to the round, gently bring them back. Off-topic content can become a separate inbox item.
- **User answers a future round's question early.** Capture it, then continue with the planned order — flow matters.
- **User says they don't know.** Probe once. If they still don't, write `[unknown]` for the field. Better than fake content. Claude will flag it on session start so the user can fill it later.
- **User wants to skip a round entirely.** Fine — capture the rounds they did, mark the skipped section with `[not yet]` so Claude knows to ask about it later.

## What Good Looks Like

A successful brain-setup produces files where:
- The `CLAUDE.md` "Who I am" section reads like a friend describing the user, not like a bio.
- The `Communication preferences` are specific enough that you could predict how Claude would respond to "should I do this?"
- The `Hard rules` are non-trivial — they reflect actual scars, not generic AI safety boilerplate.
- The `Prime directive` is one sentence, opinionated, and would not be the same for any other user.
- The `GOALS.md` numbers are real and the gating conditions show the user has thought about sequencing.
- The `patterns.md` has 3-5 named patterns the user actually recognizes in themselves.
- A future Claude session, reading these three files cold, could write a paragraph of advice that sounds like it was written for THIS user — not a generic productivity nerd.

If the output isn't there, the interview wasn't deep enough. Run `/deep-context-fill` to add more.
