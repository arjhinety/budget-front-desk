# How should this result be presented?

## The situation

A sealed validation set: 20 three-turn scenarios, authored by a different model against the same 3,107-character
brief, graders written from the spec before any reply existed, frozen by hash on a public commit, then run on
both arms. This is the test designed to be immune to my own tuning.

## The numbers

| | A0 (baseline) | A5 (tuned) |
|---|---|---|
| all 20 scenarios | 17/20 | 17/20 |
| the 13 not marked ambiguous | 12/13 (92%) | 11/13 (85%) |
| the 7 marked ambiguous | 5/7 | 6/7 |
| mean reply length | 741 chars | 856 chars |

Paired: both arms pass 11 of the 13 scored scenarios, agree on 18 of 20 overall. Exactly one discordant
scored scenario, SD-15, which A0 passes and A5 fails. McNemar exact p = 1.000.

## What this contradicts

The single-turn result is A0 71.1% of trials, A5 87.9%, McNemar p < 0.001, paired bootstrap +0.321
[+0.189, +0.453]. That was 822 conversations across five arms. The improvement was real and large there.

The multi-turn set (different scenarios, 18 scripts) gave A5 41/54 = 76%.

## Candidate explanations

1. **Underpowered.** 13 scored scenarios. One conversation moves the rate 7.7 points. The confidence
   interval on 12/13 spans roughly 66-99%.
2. **The instructions were tuned on single-turn scenarios.** A5's rules are about quoting the right price,
   refusing to invent, and stating constraints. Multi-turn adds memory, correction and pushback, which the
   instructions do not address.
3. **Longer replies, more surface.** A5 writes 856 characters on average against A0's 741, and every extra
   sentence is another chance to state an unsourced number or miss a required one.
4. **The sealed author is a different model,** so its scenarios probe behaviours that neither arm was tuned
   against.

## What I want from you

Answer exactly these, numbered, terse, no preamble:

1. Is "the single-turn gain did not transfer to the sealed multi-turn set" the right headline, or is that
   overreading 13 scenarios?
2. What is the strongest honest sentence for the result, and what must not be claimed?
3. Should this go to Agentplace at all, or stay in the repository? If it goes, where in the document?
4. A reader will ask "so did your work help or not". What is the honest answer in one sentence?
5. Is there anything in the numbers above that I am presenting in a way that flatters me?
