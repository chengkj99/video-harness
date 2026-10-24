"""Loopback-only review UI, explicit allowlist, range requests and versioned writes."""
import json
import mimetypes
from pathlib import Path
import re
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse
from . import core

PAGE = '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Video Harness · 剪辑稿审阅</title>
<style>
*{box-sizing:border-box}body{margin:0;background:#f4f3ee;color:#21323a;font:16px/1.6 system-ui,sans-serif}header{padding:25px 5%;background:#13232c;color:#fff}h1{font-size:26px;margin:0}main{max-width:1320px;margin:auto;padding:24px;display:grid;grid-template-columns:1fr 1.1fr;gap:28px}.viewer{position:sticky;top:20px;align-self:start}video{width:100%;background:#000;border-radius:10px}button{padding:10px 16px;border:0;border-radius:6px;background:#174c5b;color:white;cursor:pointer;margin:5px 5px 5px 0}button:disabled{opacity:.45;cursor:not-allowed}.row{background:white;border:1px solid #ddd;border-radius:10px;padding:15px;margin-bottom:12px}.deleted{opacity:.55;background:#ece7e4}.meta{display:flex;gap:10px;align-items:center;font-size:13px;color:#52636b}textarea{width:100%;font:17px/1.6 system-ui;border:1px solid #ddd;border-radius:6px;margin-top:8px;padding:8px;resize:vertical}input[type=text]{width:100px;padding:5px}small{color:#53646b}#notice{white-space:pre-wrap;padding:12px;background:#fff1d5;border-radius:8px}#actions{margin:14px 0}.badge{background:#e4edeb;padding:5px 9px;border-radius:5px}details{margin-top:10px;font-size:13px}pre{white-space:pre-wrap}a{color:#13596d}@media(max-width:800px){main{display:block}.viewer{position:static;margin-bottom:20px}}
</style>
<header><small style="color:#7bdcd6">VIDEO HARNESS · 本地工作流</small><h1 id="title">载入项目…</h1><div id="stage"></div></header>
<main><section class="viewer"><video id="video" controls preload="metadata"></video><p id="playing">点一句的时间，回听对应原片。</p><div id="notice">所有内容仅在本机；纠错不会改声音，删除会剪掉对应音视频。</div><div id="actions"><button id="save">保存文字与删留</button><button id="preview">播放当前成片</button><button id="refresh">刷新状态</button></div><div id="gates"></div><details><summary>选题、边界与保留要求</summary><pre id="topic"></pre></details><details><summary>发布文案草稿</summary><pre id="copy"></pre></details><p><small>保存改稿会使旧确认失效。此页不自动剪辑或上传；保存后让 Codex 继续。原始转写疑点需要回听。</small></p></section><section><p id="count"></p><div id="rows"></div></section></main>
<script>
const token=location.hash.slice(1)||sessionStorage.getItem('vh-token')||'';if(token)sessionStorage.setItem('vh-token',token);history.replaceState(null,'',location.pathname);let data;let dirty=false;
const $=x=>document.getElementById(x);
async function api(path,body){const r=await fetch(path,{method:body?'POST':'GET',headers:{'X-Review-Token':token,'Content-Type':'application/json'},body:body?JSON.stringify(body):undefined});const d=await r.json();if(!r.ok)throw Error(d.error||'请求失败');return d;}
function text(tag,value){const el=document.createElement(tag);el.textContent=value;return el;}
function notice(t){$('notice').textContent=t;}
function play(url,start=0){$('video').src=url+'?token='+encodeURIComponent(token);$('video').onloadedmetadata=()=>{$('video').currentTime=start;$('video').play().catch(()=>{});};}
async function refresh(){data=await api('/api');dirty=false;$('title').textContent=data.topic.title;$('topic').textContent=JSON.stringify(data.topic,null,2);$('copy').textContent=JSON.stringify(data.copy,null,2);$('stage').textContent='下一步：'+({topic:'确认选题',script:'确认剪辑稿',film:'复核成片',package:'生成正式发布包'}[data.status.next]);$('count').textContent='保留 '+data.status.kept+' 句；'+data.status.needs_review.length+' 句沿用待回听标记';$('rows').replaceChildren();
for(const r of data.story.units){const box=text('div','');box.className='row'+(r.keep?'':' deleted');box.dataset.id=r.id;const meta=text('div','');meta.className='meta';const keep=document.createElement('input');keep.type='checkbox';keep.checked=r.keep;keep.className='keep';keep.onchange=()=>{dirty=true;box.classList.toggle('deleted',!keep.checked);};meta.append(keep,text('span',r.id));const speaker=document.createElement('input');speaker.type='text';speaker.value=r.speaker;speaker.className='speaker';speaker.oninput=()=>dirty=true;meta.append(speaker);const b=text('button',r.source.start.toFixed(2)+'s ↗');b.onclick=()=>{play('/source/'+encodeURIComponent(r.source.source_id),r.source.start);$('playing').textContent='原片 · '+r.id+' · '+r.source.start.toFixed(2)+'–'+r.source.end.toFixed(2)+' 秒';};meta.append(b);const t=document.createElement('textarea');t.value=r.text;t.rows=2;t.oninput=()=>dirty=true;box.append(meta,t);const details=text('details','');details.append(text('summary','原话 / 识别状态'),text('p',r.original_text+' · '+r.review_status));box.append(details);$('rows').append(box);}
$('gates').replaceChildren();for(const gate of ['topic','script','film']){const g=data.status.gates[gate];const label={topic:'选题',script:'剪辑稿',film:'成片'}[gate];const b=text('button',(g.approved?'已确认 · ':'确认当前')+label);b.disabled=g.approved||!g.hash||(gate==='script'&&!data.status.gates.topic.approved)||(gate==='film'&&!data.status.gates.script.approved);b.onclick=async()=>{if(dirty)return notice('请先保存修改，再确认新版本。');if(!confirm('我已审阅当前'+label+'，确认按此版本继续。'))return;try{await api('/approve',{gate,expected:g.hash,evidence:'用户在本地审阅页确认当前'+label});await refresh();notice(label+'已确认。');}catch(e){notice(e.message);}};$('gates').append(b);}}
$('save').onclick=async()=>{const changes=[...document.querySelectorAll('.row')].map(b=>({id:b.dataset.id,text:b.querySelector('textarea').value,speaker:b.querySelector('.speaker').value,keep:b.querySelector('.keep').checked}));try{await api('/edit',{changes,expected:data.status.gates.script.hash});await refresh();notice('已保存。旧确认如已失效，需确认新版本。让 Codex 继续即可生成预览。');}catch(e){notice(e.message);}};
$('preview').onclick=()=>{if(!data.status.gates.film.hash)return notice('没有与当前稿件一致的成片，请让 Codex 生成预览。');play('/film');$('playing').textContent='当前版本成片 · 待审阅';};
$('refresh').onclick=()=>{if(dirty&&!confirm('有未保存的文字，刷新会丢弃这些修改。继续？'))return;refresh().then(()=>notice('状态已刷新')).catch(e=>notice(e.message));};
refresh().catch(e=>notice(e.message));
</script></html>'''


def serve(project, port=8765):
    p = Path(project)
    token = secrets.token_urlsafe(32)
    core.origin(p)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass  # Do not log tokens or local media paths.

        def json_response(self, value, status=200):
            payload=json.dumps(value, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header('Content-Type','application/json; charset=utf-8')
            self.send_header('Content-Length',str(len(payload)))
            self.send_header('Cache-Control','no-store')
            self.end_headers()
            self.wfile.write(payload)

        def authorized(self):
            parsed=urlparse(self.path)
            supplied=self.headers.get('X-Review-Token') or parse_qs(parsed.query).get('token',[''])[0]
            host=self.headers.get('Host','')
            expected=f'127.0.0.1:{self.server.server_port}'
            if host != expected or not secrets.compare_digest(supplied,token):
                self.json_response({'error':'无效会话'},403)
                return False
            request_origin=self.headers.get('Origin')
            if request_origin and request_origin != 'http://'+expected:
                self.json_response({'error':'禁止跨域请求'},403)
                return False
            return True

        def do_GET(self):
            path=urlparse(self.path).path
            if path=='/':
                payload=PAGE.encode()
                self.send_response(200)
                self.send_header('Content-Type','text/html; charset=utf-8')
                self.send_header('Content-Length',str(len(payload)))
                self.send_header('Referrer-Policy','no-referrer')
                self.end_headers();self.wfile.write(payload);return
            if not self.authorized():return
            try:
                if path=='/api':
                    self.json_response(dict(status=core.status(p),topic=core.read(p/'topic.json'),story=core.read(p/'story.json'),copy=core.read(p/'copy.json')))
                elif path.startswith('/source/'):
                    sources={s['id']:s['path'] for s in core.origin(p)['project.json']['sources']}
                    if path[8:] not in sources:raise core.HarnessError('未知素材')
                    self.media(Path(sources[path[8:]]))
                elif path=='/film':
                    self.media(Path(core.current_render(p)['export'])/'video.mp4')
                else:self.json_response({'error':'不存在'},404)
            except (OSError,ValueError,KeyError) as e:
                self.json_response({'error':str(e)},409)

        def do_POST(self):
            if not self.authorized():return
            try:
                n=int(self.headers.get('Content-Length','0'))
                if not 0<n<1024*1024:raise core.HarnessError('请求大小无效')
                data=json.loads(self.rfile.read(n))
                path=urlparse(self.path).path
                if path=='/edit':result=core.edit(p,data['changes'],data['expected'])
                elif path=='/approve':result=core.approve(p,data['gate'],data['expected'],data['evidence'],channel='local-review-ui')
                else:raise core.HarnessError('未知操作')
                self.json_response(result)
            except (OSError,ValueError,KeyError,TypeError) as e:
                self.json_response({'error':str(e)},409)

        def media(self,path):
            size=path.stat().st_size
            start,end=0,size-1
            ranged=self.headers.get('Range')
            if ranged:
                m=re.fullmatch(r'bytes=(\d+)-(\d*)',ranged)
                if not m:
                    self.json_response({'error':'不支持的 Range'},416);return
                start=int(m[1]);end=min(int(m[2]) if m[2] else end,end)
                if start>end:
                    self.json_response({'error':'Range 越界'},416);return
            self.send_response(206 if ranged else 200)
            self.send_header('Content-Type',mimetypes.guess_type(path)[0] or 'application/octet-stream')
            self.send_header('Accept-Ranges','bytes')
            self.send_header('Content-Length',str(end-start+1))
            if ranged:self.send_header('Content-Range',f'bytes {start}-{end}/{size}')
            self.end_headers()
            try:
                with path.open('rb') as f:
                    f.seek(start);remaining=end-start+1
                    while remaining:
                        chunk=f.read(min(1024*1024,remaining))
                        if not chunk:break
                        self.wfile.write(chunk);remaining-=len(chunk)
            except (BrokenPipeError,ConnectionResetError):pass

    server=ThreadingHTTPServer(('127.0.0.1',port),Handler)
    print(json.dumps({'review_url':f'http://127.0.0.1:{server.server_port}/#{token}'},ensure_ascii=False),flush=True)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close()
