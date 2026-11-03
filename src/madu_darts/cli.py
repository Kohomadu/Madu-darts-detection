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
    serve.add_argument(
        "--synthetic-throws",
        action="store_true",
        help="with --synthetic: loop a scripted visit (3 darts, hand, empty) to exercise the Detection view",
    )
    serve.add_argument(
        "--rotate-offsets",
        default=None,
        help="comma-separated rotate-20 offsets for cams 0,1,2 after autofit (default: Board mounts 10,4,16)",
    )
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

    diag = sub.add_parser(
        "calib-diag",
        help="diagnose autofit quality on empty-Board frame(s) (ticket 15)",
    )
    diag.add_argument(
        "path",
        type=Path,
        help="BGR image, a directory of cam{0,1,2}.jpg, or a live capture pack (0.jpg…)",
    )
    diag.add_argument("--slot", type=int, default=None, help="single cam slot when PATH is one image")
    diag.add_argument("--out", type=Path, default=None, help="directory for overlay JPEGs (optional)")
    diag.add_argument("--log-level", default="info")

    kanban = sub.add_parser(
        "kanban",
        help="refresh the markdown kanban from ticket Status / Blocked by lines",
    )
    kanban.add_argument(
        "--effort",
        default="detection-tool",
        help="`.scratch/<effort>/` slug (default: detection-tool)",
    )
    kanban.add_argument(
        "--root",
        type=Path,
        default=None,
        help="repo root (default: cwd)",
    )
    kanban.add_argument("--log-level", default="info")
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
    if isinstance(pipeline, MaduPipeline):
        from madu_darts.replay import format_turn_table

        print()
        print(format_turn_table(pipeline.visit_traces))
    return 0


def _resolve_diag_frames(path: Path, slot: int | None) -> list[tuple[int, Path]]:
    """Return ``(slot, image_path)`` pairs for calib-diag."""
    path = Path(path)
    if path.is_file():
        return [(0 if slot is None else int(slot), path)]
    if not path.is_dir():
        raise SystemExit(f"not a file or directory: {path}")
    found: list[tuple[int, Path]] = []
    for s in (0, 1, 2):
        for name in (f"cam{s}.jpg", f"{s}.jpg"):
            candidate = path / name
            if candidate.is_file():
                found.append((s, candidate))
                break
    if not found:
        raise SystemExit(f"no cam{{0,1,2}}.jpg or {{0,1,2}}.jpg under {path}")
    if slot is not None:
        found = [(s, p) for s, p in found if s == int(slot)]
        if not found:
            raise SystemExit(f"no frame for slot {slot} under {path}")
    return found


def _cmd_calib_diag(args: argparse.Namespace) -> int:
    import cv2

    from madu_darts.calibration import AutoFitError, suggest
    from madu_darts.calibration.overlay import draw_spiderweb, draw_warped_board

    pairs = _resolve_diag_frames(args.path, args.slot)
    out_dir = Path(args.out) if args.out else None
    if out_dir is not None:
        out_dir.mkdir(parents=True, exist_ok=True)
    print(
        f"{'cam':>3}  {'status':<6}  {'rms':>6}  {'inliers':>9}  {'cov':>5}  "
        f"{'dbl':>6}  {'trb':>6}  {'max':>6}  {'far':>6}"
    )
    for slot, image_path in pairs:
        image = cv2.imread(str(image_path))
        if image is None:
            print(f"{slot:3d}  FAIL   could not read {image_path}")
            continue
        try:
            cal = suggest(image, slot=slot)
        except AutoFitError as exc:
            print(f"{slot:3d}  none   {exc.reason}")
            continue
        cov = "" if cal.coverage is None else f"{cal.coverage:5.3f}"
        dbl = "" if cal.rms_double_mm is None else f"{cal.rms_double_mm:6.3f}"
        trb = "" if cal.rms_treble_mm is None else f"{cal.rms_treble_mm:6.3f}"
        inl = "" if cal.n_inliers is None or cal.n_points is None else f"{cal.n_inliers}/{cal.n_points}"
        mx, far = "", ""
        if cal.residuals is not None and cal.homography is not None:
            from madu_darts.calibration.residuals import summarize_residuals

            summary = summarize_residuals(cal.residuals, cal.homography, cal.rotate_offset)
            if summary["maxMm"] is not None:
                mx = f"{summary['maxMm']:6.3f}"
            far_band = summary["farDouble"]
            if far_band is not None and far_band["maxMm"] is not None:
                far = f"{far_band['maxMm']:6.3f}"
        print(
            f"{slot:3d}  {cal.status.value:<6}  {cal.rms_mm:6.3f}  {inl:>9}  {cov:>5}  "
            f"{dbl:>6}  {trb:>6}  {mx:>6}  {far:>6}"
        )
        if out_dir is not None:
            cv2.imwrite(str(out_dir / f"feed{slot}.jpg"), draw_spiderweb(image, cal))
            cv2.imwrite(str(out_dir / f"warped{slot}.jpg"), draw_warped_board(image, cal))
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=args.log_level.upper(), format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    if args.command == "serve":
        import uvicorn

        from madu_darts.server import DetectionService, ServiceConfig, create_app

        rotate_offsets = None
        if args.rotate_offsets:
            parts = [int(p) for p in str(args.rotate_offsets).split(",") if p.strip()]
            rotate_offsets = {slot: parts[slot] for slot in range(len(parts))}
        config = ServiceConfig(
            ingest=ingest_config_from_args(args),
            stream_fps=args.stream_fps,
            rotate_offsets=rotate_offsets,
        )
        ingest_factory = None
        if args.synthetic or args.synthetic_throws:
            from madu_darts.server.synthetic_ingest import SyntheticIngest

            script = bool(args.synthetic_throws)
            ingest_factory = lambda cfg: SyntheticIngest(cfg, script=script)  # noqa: E731
        app = create_app(DetectionService(config, ingest_factory=ingest_factory))
        logging.getLogger("madu_darts").info("Calibration view on http://%s:%d/ · Detection view on /detection", args.host, args.port)
        uvicorn.run(app, host=args.host, port=args.port, log_level=args.log_level)
        return 0
    if args.command == "record":
        return _cmd_record(args)
    if args.command == "replay":
        return _cmd_replay(args)
    if args.command == "calib-diag":
        return _cmd_calib_diag(args)
    if args.command == "kanban":
        return _cmd_kanban(args)
    return 2


def _cmd_kanban(args: argparse.Namespace) -> int:
    from madu_darts.kanban import COLUMN_TITLES, group_by_column, load_tickets, write_board

    root = Path(args.root) if args.root else Path.cwd()
    issues = root / ".scratch" / args.effort / "issues"
    if not issues.is_dir():
        raise SystemExit(f"no issues dir at {issues}")
    out = write_board(issues)
    cards = load_tickets(issues)
    groups = group_by_column(cards)
    print(f"Wrote {out}")
    for col in ("todo", "blocked", "doing", "in-testing", "done"):
        print(f"  {COLUMN_TITLES[col]}: {len(groups[col])}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
