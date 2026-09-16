# M3-01 encoder/cache review — 2026-09-16

**State:** implementation fixtures passed; live inference check deferred by the resource gate.

| Area | Review conclusion |
|---|---|
| Model identity | The local snapshot directory name matches the pinned FinBERT SHA and a file-only fingerprint resolved successfully. The loader refuses any other directory name, remote code, or download. |
| Semantics | The class-ID mapping is explicitly checked before scoring. Scores carry token count and truncation metadata; probabilities must be finite, in range and sum to one. |
| Cache/recovery | Cache identity includes text and every encoder setting that can change a score. Synthetic fixtures cover de-duplication, stable caller alignment, interrupted-batch recovery and conflicting write rejection. |
| Resources | Current live doctor evidence has 4.2 billion bytes available RAM, below the 5 GiB sentiment requirement. No model load or inference was attempted in this increment. |
| Scope | No real news text was treated as admitted data and no feature/evaluation output was produced. |

The next M3-01 action is a local cached-loader smoke test only after the sentiment resource gate passes. M3-02 onward remains additionally blocked by news-source admission.
