# References, and what each one is used for

Every paper below was looked up through the Papers With Code CLI on 2026-11-08
and 2026-11-09. Bibliographic fields are copied from the API response, not typed
from memory. Where a claim in this repository rests on a paper, the claim says so
and this file says which part of the paper it came from.

No paper text is reproduced. Nothing here is a citation for decoration: each entry
names the specific thing taken from it, and if that thing turns out to be a
misreading, the entry is wrong and should be corrected rather than removed.

---

## Statistics of evaluation

**Miller, E. (2024).** *Adding Error Bars to Evals: A Statistical Approach to
Language Model Evaluations.* arXiv:2411.00640.
<https://arxiv.org/abs/2411.00640>

Used for: treating the scenario set as a sample from a super-population, and for
the paired-difference framing. `evals/stats.py` implements the paired bootstrap
over scenarios because of this paper, and `RESULTS.md` reports the bootstrap
alongside McNemar rather than instead of it.

**Bowyer, S., Aitchison, L., Ivanova, D. R. (2025).** *Position: Don't use the CLT
in LLM evals with fewer than a few hundred datapoints.* arXiv:2503.01747.
<https://arxiv.org/abs/2503.01747>

Used for: why the intervals in this repository are bootstrap and Wilson rather
than normal-approximation. At 53 scenarios the CLT does not apply, and this paper
is the reason the write-up does not pretend otherwise.

**Madaan, L., Singh, A. K., Schaeffer, R., Poulton, A., Koyejo, S., Stenetorp,
P., Narang, S., Hupkes, D. (2024).** *Quantifying Variance in Evaluation
Benchmarks.* arXiv:2406.10229.
<https://arxiv.org/abs/2406.10229>

Used for: the decision to run three trials per scenario rather than one, and to
report stability bins (how many scenarios passed 0/3, 1/3, 2/3, 3/3) instead of a
single pass rate.

**Bjarnason, B. H., Silva, A., Monperrus, M. (2026).** *On Randomness in Agentic
Evals.* arXiv:2602.07150.
<https://arxiv.org/abs/2602.07150>

Used for: the negative-control design — the same input sent twice must produce the
same verdict, or the harness is noisy and the bar for an improvement rises.

---

## Conversational agent evaluation

**Yao, S., Shinn, N., Razavi, P., Narasimhan, K. (2024).** *τ-bench: A Benchmark
for Tool-Agent-User Interaction in Real-World Domains.* arXiv:2406.12045.
<https://arxiv.org/abs/2406.12045>

Used for: the pass^k metric. The `strict pass³` figure throughout this repository
is that metric at k = 3, chosen because a customer-facing agent has to be right
every time rather than once.

**Barres, V., Dong, H., Ray, S., Si, X., Narasimhan, K. R. (2025).** *τ²-Bench:
Evaluating Conversational Agents in a Dual-Control Environment.* arXiv:2506.07982.
ICML 2026. <https://arxiv.org/abs/2506.07982>

Used for: the framing of a conversation as a setting where both sides act and the
state changes, which is what the multi-turn design in `evals/METHOD.md` is aiming
at. Not yet implemented — the current set is single-turn.

**Li, M., Weston, J., Roller, S. (2019).** *ACUTE-Eval: Improved Dialogue
Evaluation with Optimized Questions and Multi-turn Comparisons.*
arXiv:1909.03087. <https://arxiv.org/abs/1909.03087>

Used for: the argument that a multi-turn conversation has to be compared as a
whole rather than turn by turn, and that the comparison question has to be written
before the conversations are read.

**Zhang, C., D'Haro, L. F., Zhang, Q., Friedrichs, T., Li, H. (2022).**
*FineD-Eval: Fine-grained Automatic Dialogue-Level Evaluation.*
arXiv:2210.13832. <https://arxiv.org/abs/2210.13832>

Used for: the turn-tagged grading design — checks attached to a specific turn
rather than to the whole transcript — which is how the multi-turn harness grades a
conversation without losing where it failed.

---

## Graders and judges

**Calderon, N., Reichart, R., Dror, R. (2025).** *The Alternative Annotator Test
for LLM-as-a-Judge: How to Statistically Justify Replacing Human Annotators with
LLMs.* arXiv:2501.10970. <https://arxiv.org/abs/2501.10970>

Used for: the position that a model judge cannot be assumed to stand in for a
human reader without a statistical test, which is why the kappa study in
`RESULTS.md` is reported as a calibration and not as validation.

**Fan, S., Deng, B., Xu, M., Xie, X., Li, C., Zhang, H. (2026).**
*Difference-in-Differences on a Censored Rating Scale Can Manufacture an Effect:
Evidence from a Pre-Registered LLM-Judge Audit.* arXiv:2608.27309.
<https://arxiv.org/abs/2608.27309>

Used for: the caution that a judge's scale can produce an effect that is not
there. This is the reason `RESULTS.md` reports raw agreement next to kappa
(0.828 agreement against kappa 0.314 on the same set) rather than kappa alone.

**Zhu, Y., Jin, T., Pruksachatkun, Y., Zhang, A., Liu, S., Cui, S., Kapoor, S.,
Longpre, S., Meng, K., Weiss, R., Barez, F., Gupta, R., Dhamala, J., Merizian, J.,
Giulianelli, M., Coppock, H., Ududec, C., Sekhon, J., Steinhardt, J., Kellerman,
A., Schwettmann, S., Zaharia, M., Stoica, I., Liang, P., Kang, D. (2025).**
*Establishing Best Practices for Building Rigorous Agentic Benchmarks.*
arXiv:2507.02825. <https://arxiv.org/abs/2507.02825>

Used for: the checklist the harness is measured against — task validity,
environment stability, and reporting the denominator with the score.

---

## Not a paper

**Anthropic (2026, January 9).** *Demystifying evals for AI agents.*
<https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents>

Used for: the capability-versus-regression split, the "read the transcripts"
discipline, and the practice of grading what the agent produced rather than the
path it took. This is an engineering blog post, not peer-reviewed, and is cited as
such.
