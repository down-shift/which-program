# Research positioning and claim boundaries

Planning assessment dated 2026-10-18. The project has a relevant failure
demonstration and a possible focused empirical contribution. Scientific novelty,
priority, broad treatment effectiveness, and production prevalence are not
established. The literature check below is preliminary, based on primary project
documentation and paper abstracts; it is not an exhaustive full-text review.

## What is already established

| Prior work | Relevant established idea | Implication for this project |
|---|---|---|
| [pytest: Good Integration Practices](https://docs.pytest.org/en/stable/explanation/goodpractices.html) | Tests can exercise an installed distribution or a local checkout, depending on installation and import configuration. | Testing the wrong copy is an existing software-engineering concern. |
| [SpecBench: Measuring Reward Hacking in Long-Horizon Coding Agents](https://arxiv.org/abs/2605.21384) | Compares visible validation tests with held-out compositional tests and studies success signals that diverge from specifications. | Passing visible tests while failing the task is not a new general observation. |
| [SWE Refactor Bench: Can Coding Agents Complete a Long-Horizon, Whole-Repository Stack Migration?](https://arxiv.org/abs/2608.23564) | Separates migration completeness from behavioral correctness; retaining an original implementation can leave tests passing without the intended migration. | Claims about green tests masking absent work must address this related evaluation problem. |
| [EA-Graph: Artifact-Anchored Verification Memory for Coding Agents under Upstream Drift](https://arxiv.org/abs/2608.04278) | Anchors claims to artifact content and distinguishes evidence strength from freshness in verification-memory tasks. | Binding verification claims to specific artifacts is already an explicit research direction. |
| [Executable Code Knowledge: Code as a Native, Validation-Carrying Knowledge Representation for AI Coding Agents](https://arxiv.org/abs/2608.16295) | Combines source identity, evidence, provenance, validation state, and freshness in a code-knowledge representation. | Source-bound evidence is not by itself a unique contribution. |

Read the full papers and their references before claiming a gap. In particular,
compare simultaneous edited-vs-imported identity divergence with upstream-drift
memory, weak-test specification gaps, and migration completeness. Finding no exact
match in this search does not establish that no earlier study exists.

## Candidate contribution

Research question:

> When tests execute a different artifact from the source edited by an agent,
> does the agent detect that mismatch and qualify its verification claims, and
> which interventions restore valid verification evidence?

The potentially distinctive unit is a controlled empirical design connecting
three independently measured outcomes: repair correctness, runtime source
identity relative to the final delivery, and support for the agent's final claim.
The contrasts are ordinary output, displayed provenance, an additional instruction,
and a separate execution-enforcing guard. The most useful current examples are
invalid deliveries masked by public tests importing another copy.

This is a proposed contribution to be assessed against prior work. The guard is
an engineering control whose import-routing effect is expected; implementing it
does not by itself establish a novel algorithm. Likewise, copied provenance text
is evidence about this interface/model combination, not yet a general discovery
about model cognition or all provenance tools.

## What the evidence supports

The [original pilot](../reports/pilot-20261016/README.md) shows successful source
enforcement on one task across three seeds. The
[expanded treatment pilot](../reports/expanded-pilot-seed18/README.md) reproduces
wrong-copy verification failures across four small tasks at one seed, including
six success responses accompanying syntax-invalid deliveries. These support a
bounded susceptibility demonstration under constructed, inspectable conditions.

They do not show intentional exploitation, deception, real-world prevalence,
general model inability, or that displaying provenance generally helps or harms.
The expanded guard comparison is unfinished. Metadata copying, unequal prompt
length, fixed order, one model, incomplete human coding, and harness evolution
limit stronger interpretations.

## Evidence needed for a stronger study

1. Human-adjudicated claims with explicit handling of literal process passes,
   repair-specific attributions, ambiguity, and missing responses.
2. A separately identified presentation comparison that isolates metadata/file
   confusion while preserving evidence content and recording token costs.
3. A completed expanded guard comparator, reported separately as enforcement
   rather than evidence of autonomous mismatch recognition.
4. Replication on a stronger model and realistic package layouts or repositories;
   pin model and precision and document any unavoidable configuration differences.
5. A frozen confirmatory protocol: task/seed sampling, ordering, denominators,
   exclusions, model comparisons, uncertainty reporting, and stopping rules.

A focused empirical report or research artifact is a plausible direction if these
checks succeed. Venue suitability and novelty remain judgments, not established
results. The [planner handoff](../reports/planner-handoff-20261018.md) turns these
requirements into work items and decision gates.
