# 12: Decide the tip only after the spider is honest

**What to build:** Decide whether the classical tip is enough once Scoring uses the 21 faces and Accept uses the 35 gate. A learned tip is in scope only for misses that sit more than a wire-width away from every wire. Misses on the wire are not a reason to train one.

**Blocked by:** 26, 35

**Status:** ready-for-agent

Type: task
Model: premium

- [ ] The answer uses the 26 scorecard, split into ring miss, neighbour, and far-from-wire
- [ ] Misses within the wire thickness do not justify a learned tip
- [ ] Either the classical tip stays, with that written here, or 27 is the next step and the miss list is in the answer
