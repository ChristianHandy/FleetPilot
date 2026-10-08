"""
FleetPilot — Gunicorn Production Configuration
Optimised for a typical home-lab / small-enterprise server.
"""
import multiprocessing, os

# ── Binding ───────────────────────────────────────────────────────────────────
# Respect the SERVER_IP env var set in /opt/fleetpilot/.env. Without it, listen on
# loopback only; put Nginx/HAProxy in front or set SERVER_IP to expose FleetPilot.
_server_ip = os.environ.get("SERVER_IP", "127.0.0.1")
_app_port  = os.environ.get("APP_PORT", "5000")
bind        = os.environ.get("GUNICORN_BIND", f"{_server_ip}:{_app_port}")
backlog     = 2048

# ── Workers ───────────────────────────────────────────────────────────────────
# FleetPilot starts polling and scheduling threads during application startup.
# A single worker avoids duplicate pollers and SQLite writers. Threads keep
# request handling responsive on the Raspberry Pi.
workers     = 1                # see note above; more workers would duplicate every poller
worker_class = "gthread"
threads     = int(os.environ.get("GUNICORN_THREADS", "4"))
worker_connections = 1000

# ── Timeouts ──────────────────────────────────────────────────────────────────
timeout         = 120          # SSH commands can take a while
keepalive       = 5            # seconds to keep idle connections open
graceful_timeout = 30

# ── Logging ───────────────────────────────────────────────────────────────────
# Use "-" to log to stdout/stderr (captured by systemd journal)
accesslog   = "-"
errorlog    = "-"
loglevel    = "warning"        # reduce log noise in production
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s %(D)sµs'

# ── Process naming ────────────────────────────────────────────────────────────
proc_name   = "fleetpilot"
default_proc_name = "fleetpilot"

# ── Performance tweaks ────────────────────────────────────────────────────────
preload_app  = False           # do not fork after scheduler/polling threads initialise
# Never recycle the worker: FleetPilot runs one worker whose background threads
# (pollers, Disk Tools wipes/formats, auto mode, backups) must not be killed
# mid-task, and login throttling lives in memory.
max_requests = 0
sendfile     = True            # use OS sendfile() for static files

# ── Request limits ────────────────────────────────────────────────────────────
limit_request_line   = 8190
limit_request_fields = 100
limit_request_field_size = 8190
