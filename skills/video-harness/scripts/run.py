#!/usr/bin/env python3
"""Locate the bundled core relative to the installed plugin, not a user path."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from video_harness.__main__ import main
main()
