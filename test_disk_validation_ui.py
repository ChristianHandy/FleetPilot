#!/usr/bin/env python3
"""Non-destructive regression test for Disk Tools validation output."""
from types import SimpleNamespace
from flask import Flask, render_template

import disktool_core

original_run = disktool_core.run
original_subprocess_run = disktool_core.subprocess.run
try:
    disktool_core.run = lambda command: "1048576\n"  # 1 MiB synthetic disk
    disktool_core.subprocess.run = lambda *args, **kwargs: SimpleNamespace(returncode=0)
    blocks, bad_blocks, summary = disktool_core.validate_blocks("sdb", sample_count=8)
    assert len(blocks) == 8
    assert bad_blocks == []
    assert summary["sample_count"] == 8
    assert summary["bad_count"] == 0
finally:
    disktool_core.run = original_run
    disktool_core.subprocess.run = original_subprocess_run

app = Flask(__name__, template_folder="templates")
app.jinja_env.globals['_'] = lambda value: value
app.add_url_rule("/disks", endpoint="disks_index", view_func=lambda: "ok")
app.add_url_rule("/", endpoint="index", view_func=lambda: "ok")
app.add_url_rule("/disks/tasks", endpoint="disk_tasks", view_func=lambda: "ok")
with app.test_request_context("/disks/validate/sdb"):
    html = render_template(
        "disks/validate.html", device="sdb", blocks=blocks,
        bad_blocks=bad_blocks, summary=summary,
    )
assert "No read errors found" in html
assert "Read-only Disk Validation" in html
print("Disk validation UI regression test passed")
