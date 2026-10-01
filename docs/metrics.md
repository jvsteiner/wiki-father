# Ingest scaling metrics

Run `make metrics` to see batch history. For a spreadsheet or plot, run
`python3 scripts/metrics.py --csv > /path/to/metrics.csv`. Each row is one model
invocation, which may compile several documents. A row reports wiki source/page
count *before* the batch, number requested and completed, source bytes, wall
time, turns, input and output tokens, model, and USD cost. Future rows are
recorded in `.state/ingest-metrics.jsonl`; earlier rows are recovered from
`.state/ingest.log` with the fields that were available then.

Input tokens include uncached input plus cache reads and writes on every turn.
They measure cumulative context processed, not unique text, and cache reads
often dominate. The CSV separates the three categories for new runs. Batch
cost is the harness-reported estimate; compare runs using the same model and
harness. The report is batch-level, so divide time or tokens by completed
sources only when batches contain documents of similar size. `source_bytes`
helps distinguish a larger document from a larger wiki.

To test whether the wiki itself is causing slowdown, compare batches at
increasing `wiki_sources` while holding model, batch size and source size as
steady as practical. Rising input tokens per turn or elapsed minutes per
completed source would be stronger evidence than a single slow batch. A stalled
batch (`compiled=0`) still consumes time and tokens and remains in the data.
