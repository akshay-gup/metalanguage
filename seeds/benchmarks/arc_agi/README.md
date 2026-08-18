# ARC-AGI Human-Task Interface

The shared ARC pool contains interactive environments keyed by official
`game_id`.

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
ordered frames, official state, and available actions. Official `WIN` state is
the completion signal used for scoring and retirement from future pools.
