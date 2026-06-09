#!/usr/bin/env python3
"""GitHub Actions helper: override zone_state to a specific zone."""
import json, os, sys
from pathlib import Path

zone  = os.environ.get("INPUT_ZONE","").strip()
path  = Path("zone_state.json")

if not zone or not path.exists():
    sys.exit(0)

state = json.loads(path.read_text())
zones = state.get("zones",[])
if zone in zones:
    state["current_index"] = zones.index(zone)
    path.write_text(json.dumps(state, indent=2))
    print(f"Zone overridden to: {zone}")
else:
    print(f"Zone '{zone}' not found, ignoring")
