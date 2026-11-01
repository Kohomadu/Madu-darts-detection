# LAN-reachable detection UI

The detection tool’s UI may bind beyond loopback so it can be reached via the Board machine’s Tailscale IP (same pattern as the Autodarts box). Remote operator access while developing beats locking to `127.0.0.1`; trust the private overlay network rather than exposing a public port.
