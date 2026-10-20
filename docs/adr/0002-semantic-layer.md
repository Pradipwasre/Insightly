# ADR 0002: Certified semantic layer, retrieved per question

**Status:** accepted

**Context.** Business rules ("revenue excludes cancelled and returned items") lived in a prompt
suffix. Definitions drifted and could not be reviewed.

**Decision.** `semantic_layer/` holds tables, joins, certified metrics (id, synonyms, SQL expression)
and verified example queries as YAML in Git, owned by the data team and changed by pull request.
Documents are embedded with `text-embedding-3-small` and retrieved by hybrid search (dense +
BM25/full-text, reciprocal rank fusion). The full compact schema also sits in the static, cached
system prompt; retrieved metrics and examples go in the per-request message.

**Consequences.** Metric fidelity becomes measurable; retrieval scales to hundreds of tables;
the layer version hash triggers re-indexing only when it changes.
