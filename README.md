# Rainbow Pomodoro

A see-through, always-on-top 60-minute timer for Windows, styled like a classic rainbow kids' timer. The rainbow wedge shrinks as time runs out. Each notification plays a different, randomly generated ping.

## Run

Requires Python 3 on Windows (standard library only). Double-click `pomodoro.pyw`, or run:

```
pythonw pomodoro.pyw
```

## Controls

| Action | How |
| --- | --- |
| Set time (0–60 min) | Drag around the dial, or scroll the mouse wheel (±1 min) |
| Start / pause | Click the purple knob, or press Space |
| Move the timer | Drag the purple rim |
| Menu | Right-click: focus/break lengths, check-in pings, auto-start, size, opacity, always on top, test notification |
| Reset / skip / quit | R / N / Ctrl+Q |

## Pomodoro cycle

25 min focus → 5 min break, with a 15 min long break after every 4 focus blocks. All of these can be changed from the menu.
When a block ends, a notification pops up in the bottom-right corner with a random message and one of 9 random ping styles. You can also turn on a quieter check-in ping during focus blocks.

Settings are saved to `pomodoro_settings.json` next to the script.
