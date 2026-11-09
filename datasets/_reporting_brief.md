# How should this be reported, and to whom?

## The situation

An AI agent was built on a third-party platform (Agentplace) for a real home-services business, from a
brief generated out of a 24-field facts ledger. The agent is evaluated with 55 single-turn scenarios and 18
three-turn scripts.

Multi-turn results: 32 of 44 conversations pass. Several failures looked like a model behaviour worth
reporting to the platform: asked what the savings club membership includes, the agent replied "I don't
have the membership's included benefits or terms in the approved information, so I don't want to guess."
Asked what a member pays for a visit, it declined to confirm the dispatch fee is waived.

## The correction I just made

The business's site publishes: "Annual membership includes a yearly cleaning and inspection, waived
dispatch fees, priority scheduling, 15% off repairs, and 5% off new equipment."

**My brief does not contain any of that.** It lists "Budget Savings Club Membership $250 per year" as a
price line and nothing more. My facts ledger has no field for membership benefits.

So the agent's "I don't have verified information" is **correct behaviour given what it was told**. The
failure is a gap in my brief, not something the model did wrong. Reporting it as a model failure would be
wrong and would be caught by anyone who read the brief.

## What I want from you

Answer exactly these, numbered, terse, no preamble:

1. Is there anything in this situation that is genuinely a platform finding rather than an authoring
   mistake? If yes, name it precisely. If no, say so.
2. If I report the authoring mistake to the platform, what is the right framing and what must I not claim?
3. What is the correct way to write up "the agent refused to answer something the business publishes,
   because the brief did not include it" so that it reads as a data-completeness finding and not as an
   excuse?
4. What does this episode say about how the evaluation should have been built, in one sentence I can put in
   the write-up?
