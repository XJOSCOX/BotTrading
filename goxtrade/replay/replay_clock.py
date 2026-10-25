"""Presentation clock; simulated timestamps never depend on playback speed."""
import math

SPEEDS = (1,5,10,30,60,"maximum")


def speed(value):
    if isinstance(value,bool) or value not in SPEEDS:
        raise ValueError("Select 1, 5, 10, 30, 60 or maximum replay speed")
    return value


def due(elapsed, value, seconds_per_event=60):
    speed(value)
    if not math.isfinite(elapsed) or elapsed < 0:
        raise ValueError("Invalid playback elapsed time")
    return 25 if value == "maximum" else min(25,int(elapsed*value/seconds_per_event))
