"""Input and output guardrails (cheap, deterministic, run on every request)."""

from __future__ import annotations

import re

MAX_QUESTION_CHARS = 1500

INJECTION = re.compile(
    r"(ignore (all |any |the )?(previous|prior|above) (instructions|rules)|system prompt|"
    r"you are now|developer mode|jailbreak|reveal (your|the) (prompt|instructions)|"
    r"\bdrop\s+table\b|\bdelete\s+from\b|\btruncate\b|\binsert\s+into\b|\bupdate\s+\w+\s+set\b|"
    r";\s*--|\bgrant\s+all\b)",
    re.I,
)
PII_REQUEST = re.compile(
    r"\b(e-?mails?|phone numbers?|home address(es)?|street address(es)?|ip address(es)?|"
    r"(first|last|full) names?|names of (the )?(customers|users))\b",
    re.I,
)
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
PHONE = re.compile(r"\+?\d[\d\s().-]{8,}\d")


def check_input(question: str) -> str | None:
    """Return a refusal reason, or None when the question may proceed."""
    if not question.strip():
        return "The question is empty."
    if len(question) > MAX_QUESTION_CHARS:
        return f"Questions are limited to {MAX_QUESTION_CHARS} characters."
    if INJECTION.search(question):
        return "This request looks like an attempt to change my instructions or the data."
    if PII_REQUEST.search(question):
        return (
            "Customer personal data (names, emails, addresses) is restricted. "
            "I can answer with aggregated numbers instead."
        )
    return None


def scan_output(text: str, rows: list[list]) -> list[str]:
    """Return PII findings in the answer text or result rows."""
    findings = []
    if EMAIL.search(text):
        findings.append("email in answer")
    for r in rows[:200]:
        for v in r:
            if isinstance(v, str) and EMAIL.search(v):
                findings.append("email in rows")
                return findings
    return findings
