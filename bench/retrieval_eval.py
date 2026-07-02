"""Retrieval-only eval: recall@5, recall@10, MRR against the mined dataset.

No agent involved. For each dataset query, run cortex retrieval (issue title + body, truncated to
1,000 chars) and score file-level hits against gold_files, per channel (dense / bm25 / fused).

Filled in Phase 3.
"""
