"""Publishing assets: local files only, no publication side effects."""
import html
import json
from pathlib import Path
import shutil
import subprocess
import sys
import uuid
from .core import HarnessError, approval_valid, current_render, read, save, file_hash, digest, config, event, lock, now


DEFAULT_COVER_SIZES = {'portrait': [1500, 2000], 'landscape': [1600, 1200]}


def cover_variants(copy):
    sizes = copy.get('cover_sizes', DEFAULT_COVER_SIZES)
    if not isinstance(sizes, dict) or set(sizes) != set(DEFAULT_COVER_SIZES):
        raise HarnessError('cover_sizes 需要 portrait 和 landscape 两种封面')
    variants = {}
    for name, ratio in [('portrait', (3, 4)), ('landscape', (4, 3))]:
        size = sizes[name]
        if (not isinstance(size, (list, tuple)) or len(size) != 2
                or any(type(x) is not int or not 200 <= x <= 4000 for x in size)
                or size[0] * ratio[1] != size[1] * ratio[0]):
            raise HarnessError(f'{name} 封面必须为 {ratio[0]}:{ratio[1]}，尺寸 200–4000 像素')
        variants[name] = dict(copy, cover_size=list(size))
    return variants


def cover_svg(copy):
    width, height = copy.get('cover_size', [900, 1200])
    if type(width) is not int or type(height) is not int or not 200 <= min(width, height) <= max(width, height) <= 4000:
        raise HarnessError('封面尺寸必须为 200–4000 像素')
    lines = copy['cover_lines']
    if not isinstance(lines, list) or not 1 <= len(lines) <= 5 or any(not isinstance(x, str) or not x for x in lines):
        raise HarnessError('封面文字需 1–5 行')
    size = min(width * .09, width * .80 / max(len(x) for x in lines))
    blocks = []
    for i, line in enumerate(lines):
        y = height * .38 + i * size * 1.55
        color = '#FFD168' if i == len(lines)-1 else '#F8F5EC'
        blocks.append(f'<text x="{width*.1}" y="{y}" font-size="{size}" fill="{color}">{html.escape(line)}</text>')
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">
<rect width="100%" height="100%" fill="#13232c"/>
<rect x="{width*.1}" y="{height*.25}" width="{width*.12}" height="6" fill="#FFD168"/>
<g font-family="PingFang SC,Microsoft YaHei,sans-serif" font-weight="600">{''.join(blocks)}</g>
<text x="{width*.1}" y="{height*.82}" font-family="sans-serif" font-size="{width*.025}" fill="#7BDCD6">{html.escape(copy.get('cover_footer', ''))}</text>
</svg>'''


def render_png(p, copy, path):
    c = config(p)
    runtime = read(c['runtime']) if c.get('runtime') else {}
    python = runtime.get('python', sys.executable)
    font = runtime.get('font')
    if not font:
        return '未配置中文字体，仅生成 SVG'
    # Run optional Pillow in the configured media environment, not the core runtime.
    code = '''import json,sys
from PIL import Image, ImageDraw, ImageFont
c=json.loads(sys.argv[1]); w,h=c['cover_size']; image=Image.new('RGB',(w,h),'#13232c'); d=ImageDraw.Draw(image)
s=int(min(w*.09,w*.80/max(len(x) for x in c['cover_lines'])))
d.rectangle((w*.1,h*.25,w*.22,h*.25+6),fill='#FFD168')
f=ImageFont.truetype(sys.argv[2],s)
for i,t in enumerate(c['cover_lines']):
 d.text((w*.1,h*.38+i*s*1.55-s),t,font=f,fill='#FFD168' if i==len(c['cover_lines'])-1 else '#F8F5EC')
d.text((w*.1,h*.82-w*.025),c.get('cover_footer',''),font=ImageFont.truetype(sys.argv[2],int(w*.025)),fill='#7BDCD6')
image.save(sys.argv[3])
'''
    result = subprocess.run([python, '-c', code, json.dumps(copy, ensure_ascii=False), font, str(path)], capture_output=True, text=True)
    if result.returncode:
        return 'PNG 未生成：' + result.stderr[-300:]
    return None


def package(p, draft=False):
    p = Path(p)
    with lock(p):
        if not draft and not approval_valid(p, 'film'):
            raise HarnessError('正式发布包需要当前成片确认；可用 --draft 生成待审包')
        render = current_render(p)
        copy = read(p/'copy.json')
        if not copy.get('title') or not copy.get('description') or not isinstance(copy.get('tags'), list):
            raise HarnessError('请先填写 copy.json 的标题、描述和标签')
        svg = cover_svg(copy)
        variants = cover_variants(copy)
        dest = p/'packages'/(( 'draft-' if draft else 'approved-')+uuid.uuid4().hex[:12])
        dest.mkdir(parents=True)
        export = Path(render['export'])
        for name in ['video.mp4', 'subtitles.srt', 'verification.json']:
            shutil.copy2(export/name, dest/name)
        (dest/'cover.svg').write_text(svg, encoding='utf-8')
        warning = render_png(p, dict(copy, cover_size=copy.get('cover_size', [900, 1200])), dest/'cover.png')
        warnings = [warning] if warning else []
        for name, variant in variants.items():
            (dest/f'cover-{name}.svg').write_text(cover_svg(variant), encoding='utf-8')
            warning = render_png(p, variant, dest/f'cover-{name}.png')
            if warning:
                warnings.append(name + ': ' + warning)
        save(dest/'copy.json', copy)
        save(dest/'story.json', read(p/'story.json'))
        (dest/'description.txt').write_text(copy['title']+'\n\n'+copy['description']+'\n\n'+' '.join('#'+x.lstrip('#') for x in copy['tags'])+'\n', encoding='utf-8')
        (dest/'README.md').write_text(('# 待审发布包' if draft else '# 已确认的本地发布包')+'\n\n未发布到任何平台。\n\n双比例文字设计草稿：竖版 3:4、横版 4:3。人物故事化封面需另行制作。封面比例不代表平台规范；发布前检查目标平台裁切。\n\n技术检查不等于全片语义/听审通过。\n'+'\n'.join(warnings), encoding='utf-8')
        files = {x.name: file_hash(x) for x in dest.iterdir() if x.is_file()}
        save(dest/'manifest.json', dict(schema_version=1, created_at=now(), draft=draft, published=False,
             input_hash=render['input_hash'], copy_hash=digest(copy), files=files,
             approvals=read(p/'approvals.json') if not draft else {}, warnings=warnings))
        event(p, 'package', path=str(dest), draft=draft)
        return dict(package=str(dest), draft=draft, published=False, warnings=warnings)
