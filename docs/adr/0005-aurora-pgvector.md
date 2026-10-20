# ADR 0005: Aurora PostgreSQL (pgvector) for vectors and agent state

**Status:** accepted

**Decision.** One Aurora PostgreSQL Serverless v2 cluster (0–2 ACU, auto-pause) stores the semantic
layer vectors (HNSW index + full-text index for hybrid search) and LangGraph checkpoints.

**Alternatives.** OpenSearch Serverless (higher floor cost), Amazon S3 Vectors (cheapest for large
corpora, but no full-text side for hybrid search and a second store for checkpoints), DynamoDB
checkpointer (extra component).

**Consequences.** One database to secure and back up; scales to zero; the corpus is small (tens to
hundreds of documents) so pgvector performance is not a concern.
