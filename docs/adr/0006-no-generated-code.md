# ADR 0006: No execution of generated code

**Status:** accepted

**Context.** The prototype asked an LLM to write Plotly code and ran it with `exec()` inside the
web process: remote code execution risk, extra tokens, frequent failures.

**Decision.** Charts are built deterministically from the result shape (time series → line,
categories → bar, long format → grouped series) as Plotly figure JSON, validated, and rendered by
the client.

**Consequences.** Zero tokens and zero code execution for charts; fewer chart types than an LLM
could produce, which is acceptable for business reporting.
