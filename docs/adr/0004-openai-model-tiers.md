# ADR 0004: OpenAI models in tiers

**Status:** accepted

**Context.** The team holds OpenAI credits and wants paid OpenAI models; Bedrock is not used.

**Decision.** All model calls go through `llm/gateway.py` with named tiers mapped to model ids in
configuration: router and answer on `gpt-5.4-nano`, SQL on `gpt-5.4-mini`, escalation to `gpt-5.4`
after a failed attempt, judge on `gpt-5.4-mini`, embeddings `text-embedding-3-small`. Every call
uses strict JSON-schema structured output and records usage (including cached tokens) to the cost
ledger.

**Consequences.** Model upgrades are configuration plus an evaluation run. Switching provider later
means implementing one gateway class. Requires outbound internet (NAT) from the VPC.
