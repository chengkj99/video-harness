#!/usr/bin/env python3
"""Optional local runtime launcher; machine paths remain outside the skill."""
import json, os, sys
from pathlib import Path
config_path=Path(os.environ.get('THE_RUNTIME_CONFIG',str(Path(os.environ.get('XDG_CONFIG_HOME',str(Path.home()/'.config')))/'video-harness/runtime.json')))
config=json.loads(config_path.read_text()) if config_path.is_file() else {}
env=os.environ.copy()
for field,var in [('ffmpeg','THE_FFMPEG'),('ffprobe','THE_FFPROBE'),('font','THE_FONT'),('model_dir','THE_MODEL_DIR')]:
    if config.get(field) and not env.get(var):env[var]=config[field]
python=os.environ.get('THE_PYTHON') or config.get('python') or sys.executable
os.execvpe(python,[python,str(Path(__file__).with_name('editor.py')),*sys.argv[1:]],env)
