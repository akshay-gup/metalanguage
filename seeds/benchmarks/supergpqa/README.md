# SuperGPQA Benchmark

Choose a problem by exact `uuid` from the shared pool.

Submit with:

```text
{submit_tool}(uuid=..., answer=...)
```

For multiple choice tasks, submit the option letter or exact option text. A
correct first submission may add solve-credit budget. Preserve enough budget to
call `spawn_child` before extended additional work.
