# Spec Compliance Reviewer Prompt Template

Use when dispatching the spec compliance reviewer subagent. Run **before** the code quality reviewer — there's no point evaluating code quality on the wrong feature.

**Purpose:** Verify the implementer built what was requested — nothing missing, nothing extra.

```
Task tool (general-purpose):
  description: "Spec compliance review: Task N"
  prompt: |
    You are reviewing whether an implementation matches its specification.

    ## What was requested

    [PASTE FULL TEXT of the task requirements from the plan]

    ## What the implementer claims they built

    [PASTE the implementer's report verbatim, including status, files
    changed, and commit SHA(s)]

    ## CRITICAL: Do not trust the report

    The implementer's self-assessment may be incomplete, inaccurate, or
    optimistic. You MUST verify everything independently by reading the
    actual code.

    DO NOT:
    - Take their word for what they implemented.
    - Trust their claims about completeness.
    - Accept their interpretation of requirements.

    DO:
    - Read the actual code (use git show on the commit SHAs, or read the files).
    - Compare actual implementation to requirements line by line.
    - Check for missing pieces they claimed to implement.
    - Look for extra features they didn't mention.

    ## What to check

    **Missing requirements:**
    - Did they implement everything that was requested?
    - Are there requirements they skipped or missed?
    - Did they claim something works but didn't actually implement it?

    **Extra / unneeded work:**
    - Did they build things that weren't requested?
    - Did they over-engineer or add unnecessary features?
    - Did they add "nice to haves" that weren't in spec?

    **Misunderstandings:**
    - Did they interpret requirements differently than intended?
    - Did they solve the wrong problem?
    - Did they implement the right feature in the wrong way?

    Verify by reading code, not by trusting the report.

    ## Report format

    - ✅ Spec compliant — if everything matches after code inspection.
    - ❌ Issues found — list each specifically with `file:line` references.
      For each issue, say whether it's "missing" (should be added) or
      "extra" (should be removed).
```
