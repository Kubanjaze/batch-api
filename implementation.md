# Phase 59 — Batch API: Async Compound Classification at 50% Cost

**Version:** 1.2 | **Tier:** Standard | **Date:** 2026-03-26

## Goal
Demonstrate the Anthropic Batch API to process all 45 compounds asynchronously at 50% cost reduction.
Two-command pattern: `submit` fires the batch, `retrieve` collects results when ready.

CLI:
```
python main.py submit --input data/compounds.csv
python main.py retrieve --input data/compounds.csv
```

Outputs: batch_state.json, batch_results.csv, batch_report.txt

## Logic
- `submit`: Build one request per compound → `client.beta.messages.batches.create(requests=[...])`
  - Save batch_id to `output/batch_state.json` for later retrieval
- `retrieve`: Load batch_id → `client.beta.messages.batches.retrieve()` to check status
  - When ended: iterate `client.beta.messages.batches.results(batch_id)` for results
  - Parse JSON, validate against ground truth CSV, report accuracy and cost comparison

## Key Concepts
- `client.beta.messages.batches.create(requests=[...])` submits a batch
- Each request: `{"custom_id": str, "params": {"model": ..., "max_tokens": ..., "messages": [...]}}`
- Batch processes asynchronously (up to 24h); small batches typically minutes
- `client.beta.messages.batches.retrieve(batch_id)` → check `processing_status`
- `client.beta.messages.batches.results(batch_id)` → iterate results when `ended`
- Result types: `succeeded`, `errored`, `canceled`, `expired`
- Cost: 50% of standard API pricing

## Deviations from Plan
- Redesigned from inline polling to two-command submit/retrieve pattern
- Batch API queue times unpredictable (45 requests still in_progress after 8+ min)
- Pattern is correct and production-ready; results pending server-side processing

## Results
| Metric | Value |
|--------|-------|
| Batch submitted | msgbatch_012CWzGS3jUZ1RdP6E9xyCRV |
| Compounds | 45 |
| Submit confirmed | ✅ |
| Retrieve pattern | ✅ (tested, returns "not yet complete" while processing) |
| Results | Pending server-side batch completion |

Note: Batch API is designed for async workloads. The submit/retrieve decoupling is the correct production pattern — inline polling is fragile.
