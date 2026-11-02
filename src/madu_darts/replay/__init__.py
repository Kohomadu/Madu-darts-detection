"""Offline replay / shadow-compare against Autodarts-labelled recordings."""

from madu_darts.replay.compare import AccuracySummary, DartComparison, format_comparison_table, replay, summarize
from madu_darts.replay.coords import autodarts_coords_to_mm, mm_error
from madu_darts.replay.madu_pipeline import MaduPipeline, bind_recording_cameras, resolve_rotate_offsets
from madu_darts.replay.pipeline import EchoAutodartsPipeline, HitHypothesis, Pipeline

__all__ = [
    "AccuracySummary",
    "DartComparison",
    "EchoAutodartsPipeline",
    "HitHypothesis",
    "MaduPipeline",
    "Pipeline",
    "autodarts_coords_to_mm",
    "bind_recording_cameras",
    "format_comparison_table",
    "mm_error",
    "replay",
    "resolve_rotate_offsets",
    "summarize",
]
