"""Scripted synthetic ingest (``serve --synthetic-throws``) plays darts → hand → empty."""

from __future__ import annotations

import numpy as np

from madu_darts.cameras import IngestConfig
from madu_darts.server.synthetic_ingest import SCRIPT_DARTS, SCRIPT_HAND, SyntheticIngest


def _changed(a: np.ndarray, b: np.ndarray) -> int:
    return int(np.count_nonzero(np.abs(a.astype(int) - b.astype(int)).max(axis=2) > 16))


def test_script_adds_darts_then_hand_then_empties() -> None:
    ingest = SyntheticIngest(IngestConfig(), script=True)
    ingest.open()
    t0 = ingest._t0
    empty = ingest._scripted(t0 + 0.5)
    one = ingest._scripted(t0 + SCRIPT_DARTS[0][0] + 0.5)
    three = ingest._scripted(t0 + SCRIPT_DARTS[2][0] + 0.5)
    hand = ingest._scripted(t0 + (SCRIPT_HAND[0] + SCRIPT_HAND[1]) / 2)
    after = ingest._scripted(t0 + SCRIPT_HAND[1] + 0.5)
    for slot in (0, 1, 2):
        assert 0 < _changed(empty[slot].image, one[slot].image) < _changed(empty[slot].image, three[slot].image)
        assert _changed(empty[slot].image, hand[slot].image) > 20000
        assert _changed(empty[slot].image, after[slot].image) == 0
    assert set(ingest.read()) == {0, 1, 2}
    ingest.close()
