"""``madu-darts`` command line: ``serve`` runs the detection service + Calibration view."""

from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import replace

from madu_darts.cameras import DEFAULT_FPS, DEFAULT_HEIGHT, DEFAULT_LOCATIONS, DEFAULT_WIDTH, CameraConfig, IngestConfig, default_board_slots

DEFAULT_HOST = "0.0.0.0"  # ADR 0003: reachable over the Board's Tailscale IP
DEFAULT_PORT = 3181  # 3180 is Autodarts on the same Board machine


def _parse_override(text: str) -> tuple[str, int]:
    location, _, index = text.partition("=")
    if not location or not index.isdigit():
        raise argparse.ArgumentTypeError(f"expected LOCATION=INDEX, got {text!r}")
    return location, int(index)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="madu-darts", description="Madu Darts local detection tool")
    sub = parser.add_subparsers(dest="command", required=True)

    serve = sub.add_parser("serve", help="run the detection service and Calibration view")
    serve.add_argument("--host", default=DEFAULT_HOST)
    serve.add_argument("--port", type=int, default=DEFAULT_PORT)
    serve.add_argument("--width", type=int, default=DEFAULT_WIDTH)
    serve.add_argument("--height", type=int, default=DEFAULT_HEIGHT)
    serve.add_argument("--fps", type=int, default=DEFAULT_FPS)
    serve.add_argument(
        "--locations",
        default=",".join(DEFAULT_LOCATIONS),
        help="comma-separated USB locations for slots 0,1,2 (default %(default)s)",
    )
    serve.add_argument(
        "--index-override",
        action="append",
        default=[],
        type=_parse_override,
        metavar="LOCATION=INDEX",
        help="bind a USB location to an OpenCV index (Windows dev fallback); repeatable",
    )
    serve.add_argument("--flip", action="append", default=[], type=int, metavar="SLOT", help="rotate a slot 180°; repeatable")
    serve.add_argument("--no-lock-exposure", action="store_true")
    serve.add_argument("--no-lock-white-balance", action="store_true")
    serve.add_argument("--stream-fps", type=float, default=10.0, help="MJPEG rate for the Calibration view")
    serve.add_argument("--synthetic", action="store_true", help="use rendered Board views instead of USB cameras (UI dev)")
    serve.add_argument("--log-level", default="info")
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
        lock_exposure=not args.no_lock_exposure,
        lock_white_balance=not args.no_lock_white_balance,
    )
    return IngestConfig(slots=slots, capture=capture, location_index_overrides=dict(args.index_override))


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
    return 2


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
