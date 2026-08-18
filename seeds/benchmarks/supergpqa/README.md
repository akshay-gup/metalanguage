# SuperGPQA Human-Task Interface

The shared problem pool contains multiple-choice human tasks keyed by exact
`uuid`.

The official submission interface is:

```text
{submit_tool}(uuid=..., answer=...)
```

The `answer` value accepts an option letter or exact option text. Calls through
this interface produce the benchmark's official scoring record.
