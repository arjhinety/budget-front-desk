# Out-of-distribution probe, not yet run

- **why**: A generic customer-support dataset has no county, no price menu and no coverage rule, so it cannot supply ground truth for any sealed scenario (18 of 20 mention a county, 5 mention a number). What it CAN test is whether the agent stays on task and invents nothing when a real customer says something outside its domain.
- **dataset**: bitext/Bitext-customer-support-llm-chatbot-training-dataset
- **license**: cdla-sharing-1.0
- **size**: 26,872 rows, single-turn instruction/response pairs
- **what_it_would_test**:
  - integrity only: no invented price, no invented policy, no unfilled placeholder
  - on-task routing: does it refuse or redirect a question about a different industry
  - not quality: there is no correct answer to compare against
- **status**: not run; recorded as an option, not a result

This is the only use a public dataset has here. It is not the sealed set and must not be
reported as one.
