# M4-01 linear quantile review — 2026-09-16

**State:** synthetic adapter passed; no experiment has run.

The adapter locks feature names before transformation, uses only training rows to learn median/variance/scale state, removes post-imputation constants, persists that state atomically, and enforces decimal outputs after percentage-point fitting. Fixtures cover constant removal, persisted output, schema drift and all-constant failure. `scikit-learn==1.6.1` is pinned in the optional `modeling` dependency group.

No news source, feature table, development score, penalty choice or final-period result was used. M4-02 requires source-backed eligible rows before actual chronological runs, but its fixed schedule manifest can be implemented independently.
