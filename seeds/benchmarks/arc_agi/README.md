# ARC-AGI Benchmark

Choose an official `game_id` from the shared ARC pool.

Start or reset the selected game with:

```text
mcp__arc_agi__RESET(game_id=...)
```

Then use only official ARC commands whose integer IDs appear in the latest
`available_actions`:

```text
mcp__arc_agi__ACTION1()
mcp__arc_agi__ACTION2()
mcp__arc_agi__ACTION3()
mcp__arc_agi__ACTION4()
mcp__arc_agi__ACTION5()
mcp__arc_agi__ACTION6(x=..., y=...)
mcp__arc_agi__ACTION7()
```

`ACTION6` requires integer `x` and `y` coordinates in `0..63`. Use the returned
ordered frames, official state, and available actions. The first official `WIN`
for this rollout may add solve-credit budget.
