# No Autodarts cloud / lock-in dependency

Winmau Autodarts Detection is the **quality north star** for Madu’s detection logic (Calibration, settle/Hit commit, tip fusion, Segment assignment, empty-Board clear, operator views). We study and reproduce as much of that behaviour as we can from the live local tool, docs, and observable APIs.

What we refuse is **runtime dependence** on Autodarts: Madu must not require Autodarts’ cloud API, account, or proprietary Detection binary to score or to drive a custom UI. The risk we’re designing against is Autodarts closing or locking the tool so custom interfaces can no longer consume Hits.

Open-source peers fill gaps only where Autodarts internals aren’t observable; they are not preferred over a faithful Autodarts-inspired design.
