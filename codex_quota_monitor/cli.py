import argparse
import logging
import os
from http.server import ThreadingHTTPServer

from .runtime import CPAMonitor, MonitorRequestHandler


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Serve a e-ink-friendly CLIProxyAPI pool monitor.")
    parser.add_argument("--host", default=os.environ.get("CODEX_MONITOR_HOST", "0.0.0.0"))
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("CODEX_MONITOR_PORT", "4515")),
    )
    parser.add_argument(
        "--refresh-seconds",
        type=int,
        default=int(os.environ.get("CODEX_MONITOR_REFRESH_SECONDS", "15")),
    )
    parser.add_argument(
        "--logs-refresh-seconds",
        type=int,
        default=int(os.environ.get("CODEX_MONITOR_LOGS_REFRESH_SECONDS", "0")),
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=float(os.environ.get("CODEX_MONITOR_TIMEOUT_SECONDS", "5")),
    )
    parser.add_argument(
        "--management-base-url",
        default=os.environ.get("CODEX_MONITOR_MANAGEMENT_BASE_URL", "http://127.0.0.1:8318"),
    )
    parser.add_argument(
        "--gateway-health-url",
        default=os.environ.get("CODEX_MONITOR_GATEWAY_HEALTH_URL", "http://127.0.0.1:8317/healthz"),
    )
    parser.add_argument(
        "--log-level",
        default=os.environ.get("CODEX_MONITOR_LOG_LEVEL", "INFO"),
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    monitor = CPAMonitor(
        management_base_url=args.management_base_url,
        gateway_health_url=args.gateway_health_url,
        refresh_seconds=args.refresh_seconds,
        logs_refresh_seconds=args.logs_refresh_seconds,
        timeout_seconds=args.timeout_seconds,
    )

    MonitorRequestHandler.monitor = monitor
    server = ThreadingHTTPServer((args.host, args.port), MonitorRequestHandler)
    logging.getLogger("codex-quota-monitor").info(
        "listening on http://%s:%s using management_base_url=%s gateway_health_url=%s",
        args.host,
        args.port,
        args.management_base_url,
        args.gateway_health_url,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logging.getLogger("codex-quota-monitor").info("shutting down on keyboard interrupt")
    finally:
        server.server_close()
