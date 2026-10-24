"""Validate the active media environment and save an explicit local runtime."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from .core import backend_path, default_runtime


def configure(output=None):
    path = Path(output).expanduser().resolve() if output else default_runtime()
    if path.exists():
        raise ValueError(f"配置已存在，不覆盖：{path}；请检查它或指定 --output 新路径")
    env = os.environ.copy()
    # Probe the active interpreter, not a previous runtime selected by the launcher.
    result = subprocess.run([sys.executable, str(backend_path().with_name('editor.py')), 'doctor'],
                            env=env, capture_output=True, text=True)
    if result.returncode:
        raise ValueError('环境检查失败；先安装媒体依赖、FFmpeg 和中文字体：\n'+result.stdout+result.stderr)
    report = json.loads(result.stdout)
    runtime = dict(python=sys.executable,
                   ffmpeg=os.environ.get('THE_FFMPEG') or shutil.which('ffmpeg'),
                   ffprobe=os.environ.get('THE_FFPROBE') or shutil.which('ffprobe'),
                   font=report['font'],
                   model_dir=os.environ.get('THE_MODEL_DIR',str(Path.home()/'.cache/video-harness/models')))
    for key in ('python','ffmpeg','ffprobe','font'):
        runtime[key] = str(Path(runtime[key]).absolute())
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x',encoding='utf-8') as f:
        json.dump(runtime,f,ensure_ascii=False,indent=2)
        f.write('\n')
    return dict(runtime=str(path),ready=True,model_ready='not_checked')
