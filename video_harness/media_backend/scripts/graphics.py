"""Configurable Pillow/ASS typography; no footage-specific coordinates."""
import os, re, shutil, subprocess
from pathlib import Path
from functools import lru_cache
from PIL import Image, ImageDraw, ImageFont


def font_path(style):
    configured = os.environ.get('THE_FONT') or style.get('font_file')
    if configured:
        if not Path(configured).is_file(): raise ValueError('Configured font unavailable: ' + configured)
        return configured
    candidates = ['/System/Library/Fonts/STHeiti Medium.ttc', '/System/Library/Fonts/PingFang.ttc', '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc', str(Path(os.environ.get('WINDIR', 'C:/Windows'))/'Fonts/msyh.ttc')]
    for p in candidates:
        if Path(p).is_file(): return p
    if shutil.which('fc-match'):
        p = subprocess.check_output(['fc-match', '-f', '%{file}', ':lang=zh']).decode()
        if p and Path(p).is_file(): return p
    raise ValueError('Chinese font unavailable; set THE_FONT or style.font_file')


def color(value):
    return tuple(bytes.fromhex(value.lstrip('#')))


def ease(t): return 1 - (1-max(0,min(1,t)))**3


class Graphics:
    def __init__(self, plan, captions, style):
        self.plan, self.captions, self.style = plan, captions, style
        self.w, self.h = plan['width'], plan['height']
        self.duration = sum(c['timeline_end']-c['timeline_start'] for c in plan['clips'])
        self.scale = min(self.w/1080, self.h/1440)
        self.fontfile = font_path(style)
        self.colors = {k: color(v) for k,v in style['colors'].items()}
        self.size = max(18, round(style['font_size'] * self.scale))
        self.cx = self.w * .47; self.y = self.h * .735
        self.maxwidth = self.w * .80
        self.font = ImageFont.truetype(self.fontfile, self.size)
        self.protected = style.get('protected_terms', [])
        self.wrapped = {c['id']: self.wrap(c['text']) for c in captions}

    @lru_cache(maxsize=12)
    def sized_font(self, size): return ImageFont.truetype(self.fontfile, size)

    def text(self, d, xy, text, size=None, fill=None, anchor='lt'):
        d.text(xy, text, font=self.sized_font(size or self.size), fill=fill or self.colors['base'], anchor=anchor)

    def wrap(self, text):
        measure = lambda t: self.font.getlength(t)
        if '\n' in text:
            rows = text.splitlines()
        elif measure(text) <= self.maxwidth: rows = [text]
        else:
            choices = []
            for i in range(1,len(text)):
                if max(measure(text[:i]),measure(text[i:])) > self.maxwidth: continue
                if text[i-1].isascii() and text[i].isascii() and text[i-1].isalnum() and text[i].isalnum(): continue
                if any(text[:i].endswith(w[:j]) and text[i:].startswith(w[j:]) for w in self.protected for j in range(1,len(w))): continue
                penalty = abs(measure(text[:i])-measure(text[i:])) + (0 if text[i-1] in '，。！？,.;: ' else self.size*2)
                choices.append((penalty,i))
            if not choices: raise ValueError('Caption cannot fit two lines; split at a verified speech boundary: '+text)
            i = min(choices)[1]; rows = [text[:i],text[i:]]
        if len(rows)>2 or any(measure(r)>self.maxwidth for r in rows): raise ValueError('Caption overflow: '+text)
        return rows

    def check_text(self, text, size, width):
        if self.sized_font(size).getlength(text)>width: raise ValueError('Title/endcard overflow; shorten text or reduce font: '+text)

    def caption(self, d, c):
        rows = self.wrapped[c['id']]; widths = [self.font.getlength(t) for t in rows]
        pad = self.size*.5; line = self.size*1.4; w=max(widths)+2*pad
        d.rounded_rectangle((self.cx-w/2,self.y-pad/2,self.cx+w/2,self.y+len(rows)*line+pad/2), radius=round(self.size*.3),fill=(18,31,42,220))
        keywords = self.style.get('keywords', {})
        pattern = '('+'|'.join(re.escape(x) for x in sorted(keywords,key=len,reverse=True))+')' if keywords else None
        for i,(row,width) in enumerate(zip(rows,widths)):
            x=self.cx-width/2
            for word in re.split(pattern,row) if pattern else [row]:
                self.text(d,(x,self.y+i*line),word,fill=self.colors.get(keywords.get(word),self.colors['base']))
                x+=self.font.getlength(word)

    def layer(self, t, captions=True):
        im=Image.new('RGBA',(self.w,self.h));d=ImageDraw.Draw(im);s=self.scale
        end=self.style.get('endcard', {})
        if t>=self.duration and end.get('enabled',True):
            u=t-self.duration;a=ease(u/.3);d.rectangle((0,0,self.w,self.h),fill=(17,30,40,round(252*a)))
            g=Image.new('RGBA',im.size);q=ImageDraw.Draw(g);off=(1-ease(u/.4))*20*s
            x=self.w*.12
            self.text(q,(x,self.h*.22+off),'本期要点 · 编辑提炼',max(18,round(28*s)),(170,190,200))
            title=end.get('summary','');size=round(60*s);self.check_text(title,size,self.w*.78)
            self.text(q,(x,self.h*.29+off),title,size)
            lines=end.get('points',[])
            for i,line in enumerate(lines):
                size=round(44*s);self.check_text(line,size,self.w*.76)
                self.text(q,(x,self.h*(.40+i*.075)+off),line,size,self.colors['accent'])
            if end.get('cta'):
                size=round(44*s);self.check_text(end['cta'],size,self.w*.8)
                self.text(q,(self.w*.5,self.h*.72+off),end['cta'],size,self.colors['accent'],'mt')
            if end.get('slogan'):
                size=round(38*s);self.check_text(end['slogan'],size,self.w*.8)
                self.text(q,(self.w*.5,self.h*.79+off),end['slogan'],size,anchor='mt')
            g.putalpha(g.getchannel('A').point(lambda v:round(v*a)));im.alpha_composite(g);return im
        intro=self.style.get('intro_seconds',5)
        chapter=next((c for c in reversed(self.plan.get('chapters',[])) if c['start']<=t),None)
        label=self.plan.get('title','') if t<intro else chapter['title'] if chapter else self.plan.get('title','')
        if label:
            start=0 if t<intro else max(intro,chapter['start'] if chapter else intro)
            off=round((1-ease((t-start)/.25))*12*s);size=round((self.style['title_size'] if t<intro else self.style['chapter_size'])*s)
            self.check_text(label,size,self.w*.77)
            top=self.h*.065+off;bottom=top+size*1.8
            d.rounded_rectangle((self.w*.08,top,self.w*.88,bottom),round(18*s),fill=(21,36,48,235))
            self.text(d,(self.w*.48,top+size*.35),label,size,self.colors['accent'] if t<intro else self.colors['base'],'mt')
            progress=ease((t-start)/.5)
            d.rectangle((self.w*.11,bottom-4*s,self.w*.11+self.w*.12*progress,bottom-2*s),fill=self.colors['accent'])
        if captions:
            c=next((c for c in self.captions if c['start']<=t<c['end']),None)
            if c:self.caption(d,c)
        return im

    def ass(self):
        def time(t):
            n=round(t*100);h,n=divmod(n,360000);m,n=divmod(n,6000);sec,n=divmod(n,100);return f'{h}:{m:02}:{sec:02}.{n:02}'
        def rgb(c):return '&H%02X%02X%02X&'%(c[2],c[1],c[0])
        def esc(t):return t.replace('\\','＼').replace('{','｛').replace('}','｝')
        name=self.font.getname()[0]
        header=f'''[Script Info]\nScriptType: v4.00+\nPlayResX: {self.w}\nPlayResY: {self.h}\nWrapStyle: 2\n[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\nStyle: Default,{name},{self.size},&H00ECF5F8,&H00ECF5F8,&H301F1710,&H301F1710,0,0,0,0,100,100,0,0,3,8,0,8,20,20,20,1\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n'''
        rows=[]
        for c in self.captions:
            text='\\N'.join(esc(r) for r in self.wrapped[c['id']])
            for term,col in self.style.get('keywords',{}).items():
                text=text.replace(esc(term),'{\\c'+rgb(self.colors[col])+'}'+esc(term)+'{\\c'+rgb(self.colors['base'])+'}')
            rows.append(f'Dialogue: 0,{time(c["start"])},{time(c["end"])},Default,,0,0,0,,{{\\pos({round(self.cx)},{round(self.y)})}}{text}')
        return header+'\n'.join(rows)+'\n'
