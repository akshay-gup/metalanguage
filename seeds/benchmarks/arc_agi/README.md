# ARC-AGI-3 General Capability Practice

The human task is the single long-horizon objective of improving general
ARC-AGI-3 capability for eventual hidden evaluation. The shared catalog contains
reusable public practice/evaluation environments keyed by official `game_id`.
They remain eligible after a `WIN`; choose them for useful practice, evaluation,
comparison, or continuation rather than treating each public environment as a
human task that is consumed when won.

## Official interaction

`RESET` starts or resets an environment instance:

```text
mcp__arc_agi__RESET(game_id=...)
```

The official action interface consists of the commands whose integer IDs appear
in the latest `available_actions`:

```text
mcp__arc_agi__ACTION1()
mcp__arc_agi__ACTION2()
mcp__arc_agi__ACTION3()
mcp__arc_agi__ACTION4()
mcp__arc_agi__ACTION5()
mcp__arc_agi__ACTION6(x=..., y=...)
mcp__arc_agi__ACTION7()
```

`ACTION6` has integer `x` and `y` coordinates in `0..63`. Responses contain
ordered frames, official state, level progress, and available actions. Use only
the action IDs listed in the latest `available_actions`.

## Diagnostics and scoring

An official `WIN` means the selected environment run completed. Level progress
and `WIN` history are useful diagnostics, but neither means that the overall
general-capability objective is complete.

Each rollout is scored by the official ARC-AGI-3 Relative Human Action
Efficiency (RHAE) score from its full `EnvironmentScorecard`. The value is a
percentage on a 0–100 scale. For each completed level, the official toolkit uses
the squared human-baseline-actions to AI-actions ratio, caps the level result at
115%, weights levels by their 1-indexed position, applies the completion cap,
and averages environment scores for a full suite. The harness reads this score
from the official scorecard rather than reimplementing the formula. If the
official score is unavailable, the rollout is reported as unscored; `WIN` is not
substituted as a binary reward.

Aggregates over self-selected or repeated public environments are labeled as
public-practice rollout RHAE summaries. They are not the official hidden score
and are not a full-suite ARC-AGI-3 score. Public practice can overfit known
environments, so durable improvements should aim for transferable interaction,
reasoning, and learning strategies that can generalize to hidden evaluation.
