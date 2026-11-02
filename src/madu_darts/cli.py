"""``madu-darts`` command line: ``serve``, ``record``, ``replay``."""

from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import replace
from pathlib import Path

from madu_darts.cameras import DEFAULT_FPS, DEFAULT_HEIGHT, DEFAULT_LOCATIONS, DEFAULT_WIDTH, CameraConfig, IngestConfig, default_board_slots

DEFAULT_HOST = "0.0.0.0"  # ADR 0003: reachable over the Board's Tailscale IP
DEFAULT_PORT = 3181  # 3180 is Autodarts on the same Board machine
DEFAULT_BOARD_URL = "http://100.118.240.5:3180"


def _parse_override(text: str) -> tuple[str, int]:
    location, _, index = text.partition("=")
    if not location or not index.isdigit():
        raise argparse.ArgumentTypeError(f"expected LOCATION=INDEX, got {text!r}")
    return location, int(index)


def _add_ingest_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--width", type=int, default=DEFAULT_WIDTH)
    parser.add_argument("--height", type=int, default=DEFAULT_HEIGHT)
    parser.add_argument("--fps", type=int, default=DEFAULT_FPS)
    parser.add_argument(
        "--locations",
        default=",".join(DEFAULT_LOCATIONS),
        help="comma-separated USB locations for slots 0,1,2 (default %(default)s)",
    )
    parser.add_argument(
        "--index-override",
        action="append",
        default=[],
        type=_parse_override,
        metavar="LOCATION=INDEX",
        help="bind a USB location to an OpenCV index (Windows dev fallback); repeatable",
    )
    parser.add_argument("--flip", action="append", default=[], type=int, metavar="SLOT", help="rotate a slot 180°; repeatable")
    parser.add_argument(
        "--lock-exposure",
        action="store_true",
        help="settle under auto then lock exposure (off by default; can underexpose on V4L2)",
    )
    parser.add_argument(
        "--lock-white-balance",
        action="store_true",
        help="settle under auto then lock white balance (off by default)",
    )
    parser.add_argument("--no-lock-exposure", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--no-lock-white-balance", action="store_true", help=argparse.SUPPRESS)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="madu-darts", description="Madu Darts local detection tool")
    sub = parser.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", help="run the detection service and Calibration view")
    serve.add_argument("--host", default=DEFAULT_HOST)
    serve.add_argument("--port", type=int, default=DEFAULT_PORT)
    _add_ingest_args(serve)
    serve.add_argument("--stream-fps", type=float, default=10.0, help="MJPEG rate for the Calibration view")
    serve.add_argument("--synthetic", action="store_true", help="use rendered Board views instead of USB cameras (UI dev)")
    serve.add_argument("--log-level", default="info")

    record = sub.add_parser("record", help="record Autodarts visits + cam frames (dev tool)")
    record.add_argument("--board", default=DEFAULT_BOARD_URL, help="Autodarts base URL (default %(default)s)")
    record.add_argument("--out", type=Path, default=Path("recordings"), help="output root for sessions")
    record.add_argument(
        "--frames",
        choices=("none", "local", "madu", "autodarts"),
        default="none",
        help="frame source: none|local USB|madu JPEG|--frames autodarts MJPEG from board /api/streams/live",
    )
    record.add_argument("--madu", default="http://127.0.0.1:3181", help="Madu :3181 base URL when --frames madu")
    record.add_argument(
        "--warp",
        action="store_true",
        help="when --frames autodarts, request warped streams (?warp=true)",
    )
    record.add_argument("--poll-hz", type=float, default=5.0)
    record.add_argument("--sample-fps", type=float, default=10.0)
    record.add_argument("--duration", type=float, default=None, help="stop after N seconds (default: until Ctrl-C)")
    _add_ingest_args(record)
    record.add_argument("--log-level", default="info")

    replay = sub.add_parser("replay", help="shadow-compare a recording through the Madu pipeline")
    replay.add_argument("recording", type=Path, help="path to a session directory (contains visit-*)")
    replay.add_argument(
        "--pipeline",
        choices=("madu", "echo"),
        default="madu",
        help="madu = real motion/tip/fusion chain (default); echo = Autodarts labels (harness check)",
    )
    replay.add_argument(
        "--rotate-offsets",
        default=None,
        help="pin rotate-20 per cam as 'o0,o1,o2' instead of resolving from labels",
    )
    replay.add_argument("--log-level", default="info")
    return parser


def ingest_config_from_args(args: argparse.Namespace) -> IngestConfig:
    locations = tuple(part.strip() for part in args.locations.split(",") if part.strip())
    if len(locations) != 3:
        raise SystemExit("--locations needs exactly three USB locations")
    slots = tuple(
        replace(slot, rotate_180=slot.slot in set(args.flip))
        for slot in default_board_slots(locations)  # type: ignore[arg-type]
    )
    capture = CameraConfig(
        width=args.width,
        height=args.height,
        fps=args.fps,
        lock_exposure=bool(args.lock_exposure) and not args.no_lock_exposure,
        lock_white_balance=bool(args.lock_white_balance) and not args.no_lock_white_balance,
    )
    return IngestConfig(slots=slots, capture=capture, location_index_overrides=dict(args.index_override))


def _frame_source_from_args(args: argparse.Namespace):
    from madu_darts.record.frames import (
        AutodartsStreamFrameSource,
        LocalPumpFrameSource,
        MaduFeedFrameSource,
        NullFrameSource,
    )

    if args.frames == "local":
        return LocalPumpFrameSource(ingest_config_from_args(args), fps=args.sample_fps)
    if args.frames == "madu":
        return MaduFeedFrameSource(args.madu)
    if args.frames == "autodarts":
        return AutodartsStreamFrameSource(args.board, warp=bool(args.warp))
    return NullFrameSource()


def _cmd_record(args: argparse.Namespace) -> int:
    from madu_darts.record.board_client import BoardClient
    from madu_darts.record.recorder import VisitRecorder

    board = BoardClient(args.board)
    recorder = VisitRecorder(
        board,
        args.out,
        frames=_frame_source_from_args(args),
        sample_fps=args.sample_fps,
        poll_hz=args.poll_hz,
    )
    session = recorder.run(duration_s=args.duration)
    logging.getLogger("madu_darts").info("wrote recording session %s", session)
    return 0


def _cmd_replay(args: argparse.Namespace) -> int:
    from madu_darts.replay import EchoAutodartsPipeline, MaduPipeline, format_comparison_table, replay

    if args.pipeline == "echo":
        pipeline = EchoAutodartsPipeline()
    else:
        offsets = None
        if args.rotate_offsets:
            parts = [int(p) for p in str(args.rotate_offsets).split(",") if p.strip()]
            offsets = {slot: parts[slot] for slot in range(len(parts))}
        pipeline = MaduPipeline(rotate_offsets=offsets)
    rows = replay(args.recording, pipeline)
    print(format_comparison_table(rows))
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=args.log_level.upper(), format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    if args.command == "serve":
        import uvicorn

        from madu_darts.server import DetectionService, ServiceConfig, create_app

        config = ServiceConfig(ingest=ingest_config_from_args(args), stream_fps=args.stream_fps)
        ingest_factory = None
        if args.synthetic:
            from madu_darts.server.synthetic_ingest import SyntheticIngest

            ingest_factory = SyntheticIngest
        app = create_app(DetectionService(config, ingest_factory=ingest_factory))
        logging.getLogger("madu_darts").info("Calibration view on http://%s:%d/", args.host, args.port)
        uvicorn.run(app, host=args.host, port=args.port, log_level=args.log_level)
        return 0
    if args.command == "record":
        return _cmd_record(args)
    if args.command == "replay":
        return _cmd_replay(args)
    return 2


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
