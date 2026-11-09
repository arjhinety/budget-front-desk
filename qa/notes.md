# Notes that did not become reports

Observations that did not meet the bar for a numbered report in `qa/`. Kept
because a deleted observation is one nobody can check later.

## About the builder

- **The default builder model is a paid tier.** A new project opens on GPT-6
  Astra; Luna has to be selected explicitly. A user who does not notice is
  spending credits they did not choose to spend.
- **The builder reports its own process in the first person.** Its summaries say
  things like "I did not capture a browser screenshot, so the visual presentation
  remains unverified" and "I made build and Preview calls despite the summary's
  instruction to stop". Useful, and unusual enough to be worth noting.
- **It asks for confirmation with a two-option prompt** ("Looks good" / "Needs
  changes") that sends immediately on click. There is no preview of what the
  choice will do.
- **It can take several minutes per instruction** and gives no progress estimate
  beyond a running timer.

## About the published agent

- **The quota message persists as a banner after the quota clears.** The agent
  answers normally underneath it, so a screenshot taken at the wrong moment looks
  like an outage that is not happening.
- **The page keeps a collapsed preview of each message** above the full copy. A
  price can be cut mid-digit in the preview, which is how `$99` was once read as
  `$9` by a grader.
- **The "Next step" heading can render with nothing under it.** Seen once, on a
  Sunday-evening probe.

## About the harness

- **`clearCookies()` and `clearStorage()` with no argument wipe the whole browser
  profile**, including the builder session. Both are now scoped to the agent's own
  origin, and the parent-domain cookie case still logs the builder out if the
  filter is wrong.
- **`settle()` has to wait out the "Working…" marker.** Text length stabilises
  while a reply is still being generated, which captures the previous turn.
