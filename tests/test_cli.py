"""``madu-darts serve`` argument parsing -> IngestConfig."""

from __future__ import annotations

import pytest

from madu_darts.cli import DEFAULT_HOST, DEFAULT_PORT, build_parser, ingest_config_from_args


def test_defaults_are_autodarts_shaped_and_lan_reachable() -> None:
    args = build_parser().parse_args(["serve"])
    assert (args.host, args.port) == (DEFAULT_HOST, DEFAULT_PORT) == ("0.0.0.0", 3181)
    cfg = ingest_config_from_args(args)
    assert (cfg.capture.width, cfg.capture.height, cfg.capture.fps) == (1280, 720, 30)
    assert [s.location for s in cfg.slots] == ["7.2", "7.3", "7.4"]
    assert not any(s.rotate_180 for s in cfg.slots)
    assert cfg.location_index_overrides == {}
    assert cfg.capture.lock_exposure and cfg.capture.lock_white_balance


def test_overrides_flips_and_locations() -> None:
    args = build_parser().parse_args(
        [
            "serve",
            "--index-override", "7.2=0",
            "--index-override", "7.3=2",
            "--flip", "1",
            "--locations", "1.1,1.2,1.3",
            "--fps", "15",
            "--no-lock-exposure",
        ]
    )
    cfg = ingest_config_from_args(args)
    assert cfg.location_index_overrides == {"7.2": 0, "7.3": 2}
    assert [s.rotate_180 for s in cfg.slots] == [False, True, False]
    assert [s.location for s in cfg.slots] == ["1.1", "1.2", "1.3"]
    assert cfg.capture.fps == 15 and not cfg.capture.lock_exposure


def test_synthetic_flag_parses() -> None:
    assert build_parser().parse_args(["serve", "--synthetic"]).synthetic is True
    assert build_parser().parse_args(["serve"]).synthetic is False


def test_bad_override_and_location_count_are_rejected() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(["serve", "--index-override", "nonsense"])
    args = build_parser().parse_args(["serve", "--locations", "7.2,7.3"])
    with pytest.raises(SystemExit):
        ingest_config_from_args(args)
