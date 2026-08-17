# SuperGPQA Benchmark

Choose a problem by exact `uuid` from the shared pool.

Submit with:

```text
{submit_tool}(uuid=..., answer=...)
```

For multiple choice tasks, submit the option letter or exact option text. Call
`spawn_child` before extended additional work so the lineage can continue.
