# ADR-001: Documentation as Markdown in the repository

| Status | Accepted |
|---|---|
| Date | 2026-09-21 |

## Context
Specifications must stay in sync with models and RTL, and support maths and diagrams.

## Options considered
1. **Markdown in `docs/`, versioned with git**: diffable, lives next to code, renders maths (`$...$`) and Mermaid on GitHub; can be converted to Word/PDF with Pandoc.
2. **Online documents**: easy commenting for the guide, but drift away from the code.

## Decision
Option 1. Documents for the guide or college are exported from Markdown when needed.

## Consequences
Spec changes are reviewed as diffs. Keep a change log in [05](../05-algorithm-spec.md).
