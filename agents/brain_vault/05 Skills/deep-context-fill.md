---
name: deep-context-fill
description: Gap-targeted interview that adds depth to the meta CLAUDE.md without overwriting existing content. Run once after initial vault setup.
---

# Deep Context Fill

## Purpose
The meta CLAUDE.md was filled directly without an interview. This skill adds depth on dimensions that pre-drafting could not capture, by asking targeted questions about gaps rather than re-covering covered ground.

## Process
1. Read the current `CLAUDE.md` at the vault root.
2. Tell you: "I'm going to ask 7 questions to fill gaps in your CLAUDE.md. Each one targets something we couldn't pre-draft. Answer in whatever depth you want — short answers are fine if that's what's true."
3. Ask the following questions, one at a time, waiting for each answer before proceeding:

 1. **Daily energy and focus rhythms.** When in your 24-hour cycle (with night shift Tue–Sat 11:30pm–7:30am) are you sharpest? When are you reliably blunted? When does creative work happen versus admin work?
 2. **Risk relationship shift.** How has your relationship with risk changed in the past two years? What kinds of risk feel different now than they did before [major life events you've had]?
 3. **Impulsive-project triggers.** What specific conditions or feelings precede the moments when you start a new project you shouldn't? Time of day, emotional state, what you were doing right before, what you saw or read?
 4. **IC career fork — current view.** Where does the intelligence community career path actually sit in your priorities right now? Honestly. Is it active pursuit, default-yes inertia, default-maybe, hedge, or something you're already privately stepping away from?
 5. **Non-negotiable commitments.** What in your life — relationships, health practices, family obligations, faith — are non-negotiable and should be protected by the system from being overrun by ambition or new projects?
 6. **One-year "won" scene.** Imagine April 2027. The year went well. Describe the scene — where you are, who you're with, what you're doing on a typical day — in 3–4 sentences. Concrete details, not metrics.
 7. **Low-energy vs high-energy days.** How do you want me to interact with you differently on days when you're depleted, sleep-deprived, or struggling, versus days when you're firing? What helps versus what makes it worse?

4. After all 7 are answered, append a new section to `CLAUDE.md` titled `## Deep context (deep-context-fill output, [DATE])` containing you's answers in a clean structured format. Do NOT overwrite or modify any existing section of CLAUDE.md.
5. Confirm the addition with you and offer to revise any answer.

## When to run
Once, after initial vault setup. Re-run optionally every 6–12 months to capture how you has shifted.
