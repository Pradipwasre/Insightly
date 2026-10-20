# ADR 0007: Evaluation as a release gate

**Status:** accepted

**Decision.** A versioned golden set and red-team set, 30+ metrics (execution accuracy first), and
`insightly eval gate` with thresholds and regression limits. CI runs the offline baseline on every
pull request at zero model cost and the OpenAI evaluation nightly and on labelled PRs; a passing run
on `main` becomes the baseline.

**Consequences.** Changes are justified by numbers; adding a feature includes adding cases. Golden
data must be curated and kept out of training data.
