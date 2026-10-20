# ADR 0008: ECS Fargate for the service

**Status:** accepted

**Decision.** The FastAPI + LangGraph container runs on ECS Fargate (ARM64/Graviton) behind an ALB,
1–3 tasks with CPU target tracking, deployment circuit breaker with rollback.

**Alternatives.** Lambda (15-minute limit is fine, but streaming and connection pooling to Aurora are
harder), App Runner (simpler, fewer networking controls), Amazon Bedrock AgentCore Runtime
(framework-agnostic agent hosting; a good option if the company standardises on it).

**Consequences.** Standard container operations, portable image, predictable cost (one task is
always on).
