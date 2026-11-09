# How should these findings be presented to the platform vendor?

## Who is receiving this

Agentplace, the company whose platform the agent was built on. The author is applying to them for an AI
Engineer role. The findings go in an application package, not a bug bounty, so the framing has to survive a
reader who is both a hiring manager and the owner of the thing being described.

## What was found

**1. Two builds from the same brief know different amounts.** Same 3,107-character brief, same question
("what's included in the savings club"):
- Build `jojuduewx7ud` answers with the site's wording: yearly cleaning and inspection, waived dispatch
  fees, priority scheduling, 15% off repairs, 5% off new equipment.
- Build `cgiefgaebmgh` says it has no verified information about the benefits and declines.
The brief contains the membership price and no benefits in either case. So the first build states facts it
was not given. Its own build log shows the Builder opening the business's website, which is a likely source
but not established. The cause is unknown: crawl, a workspace knowledge store, a different effective brief,
and model priors are all consistent with what was observed.

**2. Multi-turn behaviour.** 18 three-turn scripts, 54 conversations, 41 pass (76%).
- memory 9/9, recovery 9/9, self-correction 8/9, pushback 7/9, arithmetic 5/9, change-of-mind 3/9.
- Of the 13 failures, 6 are the brief's fault, not the agent's: two scripts ask about the savings club and
  the brief never contained the benefits. Counted separately.
- The genuine failures: the agent does not state opening hours when asked about a specific slot, and does
  not say "no 24/7" when asked about a 2am emergency.

**3. Earlier single-turn work.** 55 scenarios, five instruction arms, 822 recorded conversations. A0 passes
71.1% of trials, A5 87.9%. Three instruction changes were tried; two regressed and were reverted. Nineteen
grader corrections were needed, all found by reading transcripts.

**4. A sealed validation set** authored by a different model with graders written from the spec before any
reply existed, frozen by hash on a public commit, run in progress.

## What I want from you

Answer exactly these, numbered, terse, no preamble:

1. Which of these is worth sending to the vendor, and which should stay in the repository only? Be
   specific about why.
2. For the build-inconsistency finding: what is the strongest honest sentence, and what must not be
   claimed alongside it?
3. Does the fact that this is also a job application change how the findings should be framed? If yes, how,
   and if no, say so.
4. What is the one thing in this package that would make a reader at Agentplace defensive, and how should it
   be presented instead?
5. Should the multi-turn failures be presented as a model finding, an authoring finding, or split? Give the
   split as a sentence.
