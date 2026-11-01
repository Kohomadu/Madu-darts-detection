"""LAN-reachable detection service: Calibration view + local API (ADR 0003)."""

from madu_darts.server.app import create_app
from madu_darts.server.service import DetectionService, FramePump, ServiceConfig

__all__ = ["DetectionService", "FramePump", "ServiceConfig", "create_app"]
