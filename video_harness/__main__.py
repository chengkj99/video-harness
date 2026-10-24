import argparse
import json
from pathlib import Path
import sys
from . import core


def main():
    if len(sys.argv)>1 and sys.argv[1]=="media":
        import subprocess
        sys.exit(subprocess.call([sys.executable,str(core.backend_path()),*sys.argv[2:]]))
    parser = argparse.ArgumentParser(description='Video Harness — 本地审稿、剪辑和发布包')
    sub = parser.add_subparsers(dest='command', required=True)
    setup = sub.add_parser('configure', help='检查当前环境并写入本机配置，不覆盖已有配置')
    setup.add_argument('--output')
    sub.add_parser('media', help='内置媒体工具：media --help')
    imp = sub.add_parser('import-editor', help='导入已有源锚点工程，不继承审批')
    imp.add_argument('--project', required=True)
    imp.add_argument('--from-project', required=True)
    imp.add_argument('--backend', help='可选：覆盖内置媒体后端')
    imp.add_argument('--runtime')
    imp.add_argument('--source-map', help='JSON source ID to relocated path; fingerprint must match')
    for command in ['status', 'resume', 'review', 'compile', 'render', 'package', 'approve', 'edit', 'serve']:
        cmd = sub.add_parser(command)
        cmd.add_argument('--project', required=True)
        if command in ['render', 'package']:
            cmd.add_argument('--draft', action='store_true')
        if command == 'approve':
            cmd.add_argument('gate', choices=['topic', 'script', 'film'])
            cmd.add_argument('--expected', required=True)
            cmd.add_argument('--evidence', required=True)
            cmd.add_argument('--chat-confirmed', action='store_true', required=True)
        if command == 'edit':
            cmd.add_argument('--changes', required=True, help='JSON changes array file')
            cmd.add_argument('--expected', required=True)
        if command == 'serve':
            cmd.add_argument('--port', type=int, default=8765)
    args = parser.parse_args()
    if args.command == 'configure':
        from .setup import configure
        try:
            print(json.dumps(configure(args.output),ensure_ascii=False,indent=2))
        except (ValueError,OSError) as e:
            print(str(e),file=sys.stderr);sys.exit(1)
        return
    p = Path(args.project).resolve()
    try:
        if args.command == 'import-editor':
            result = core.import_editor(p, args.from_project, args.backend, args.runtime, core.read(args.source_map) if args.source_map else None)
        elif args.command in ['status', 'resume']:
            result = core.status(p)
        elif args.command == 'review':
            result = {'review': core.review_markdown(p), **core.status(p)}
        elif args.command == 'approve':
            result = core.approve(p, args.gate, args.expected, args.evidence)
        elif args.command == 'edit':
            result = core.edit(p, core.read(args.changes), args.expected)
        elif args.command == 'compile':
            with core.lock(p):
                result = core.compile_project(p)
        elif args.command == 'render':
            result = core.render(p, args.draft)
        elif args.command == 'package':
            from .package import package
            result = package(p, args.draft)
        elif args.command == 'serve':
            from .review import serve
            serve(p, args.port)
            return
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (core.HarnessError, OSError, KeyError, TypeError) as e:
        print(json.dumps(dict(error=str(e)), ensure_ascii=False), file=sys.stderr)
        sys.exit(1)

if __name__ == '__main__':
    main()
