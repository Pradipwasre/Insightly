# ADR 0003: Athena over Iceberg tables on S3

**Status:** accepted

**Decision.** Curated data is stored as Apache Iceberg tables (created by Athena CTAS) registered in
the Glue Data Catalog and queried by an Athena engine v3 workgroup with enforced settings and a 1 GB
per-query scan cutoff. Locally the same Trino SQL runs on DuckDB through sqlglot transpilation.

**Alternatives.** Redshift Serverless (higher floor cost, better for heavy concurrency), Aurora
(operational DB, not analytics), Amazon S3 Tables (managed Iceberg; adopt when Lake Formation
integration is set up).

**Consequences.** Zero idle cost, pay per scan, governance through Glue/Lake Formation. Athena
latency (1–3 s per query) is acceptable for this use case.
