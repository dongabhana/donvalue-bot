"""Render complete 9:16 campaign; never publish, truncate cards or silently drop audio.

2026-09-29 최종본 변경
  · 나레이션 속도 +22%(운영 파이프라인과 같음), 화면 기호(~ % × km 등)는 읽기 좋게 바꿔 합성
  · 결론 화면: 핵심 숫자 박스 + 결론 문장
  · 배경음(자체 합성)을 말 아래에 낮게 깔고, 말할 때는 더 눌러 준다(더킹)
  · 편 폴더를 매번 비우고 새로 만든다 — 이전 음성·영상 캐시가 섞이지 않는다
  · 표지 JPEG(cover.jpg)를 따로 내보낸다 — 인스타 cover_url·유튜브 썸네일용
  · verify.json: 영상 길이·장면 수·평균 음량(무음 검사)·파일 해시를 기록
"""
from __future__ import annotations
import argparse, asyncio, concurrent.futures, hashlib, html, json, math, os, re, shutil, subprocess, sys, wave
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageOps

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from src import theme as T
from src.render import wrap
W,H=1080,1920
INK='#17191e'; PAPER='#f5f1e9'; ACCENT='#ef5b35'; SOFT='#555961'
BOXES=[]

def textblock(draw,text,x,y,width,size=64,color=INK,max_height=500,weight='Bold'):
    for n in range(size,min(size,32)-1,-2):
        f=T.font(weight,n); lines=wrap(draw,text,f,width); step=round(n*1.35)
        if step*len(lines)<=max_height and all(draw.textlength(line,font=f)<=width for line in lines): break
    else: raise ValueError(f'Text overflow: {text}')
    for line in lines:
        draw.text((x,y),line,font=f,fill=color)
        box=draw.textbbox((x,y),line,font=f)
        if not (64<=box[0] and box[2]<=970 and 120<=box[1] and box[3]<=1600):
            raise ValueError(f'Unsafe text bounds {box}: {line}')
        BOXES.append(dict(text=line,bounds=box,font=n))
        y+=step
    return y

def chrome(img,e,label,dark=False):
    d=ImageDraw.Draw(img)
    d.rectangle((72,150,88,181),fill=ACCENT)
    textblock(d,'돈값하나',106,143,600,34,'#ffffff' if dark else INK,70)
    textblock(d,label,72,239,850,32,'#e0e1e4' if dark else SOFT,95)
    textblock(d,'@dongabhana',72,1515,850,28,'#ccd0d4' if dark else SOFT,65)
    return d

def photo(e):
    p=ROOT/e['cover_file']
    if not p.is_file(): raise FileNotFoundError(p)
    img=ImageOps.fit(Image.open(p).convert('RGB'),(W,H),method=Image.Resampling.LANCZOS)
    # Older editorial photos reserved empty space ABOVE the object; this campaign
    # puts the hook below it. Shift only those legacy photos so text cannot hide it.
    if not p.name.startswith('p'):
        shifted=Image.new('RGB',(W,H),'#0b0f14'); shifted.paste(img,(0,-350)); img=shifted
    overlay=Image.new('RGBA',(W,H)); d=ImageDraw.Draw(overlay)
    for y in range(H):
        alpha=int(45+170*max(0,min(1,(y-650)/850)))
        d.line((0,y,W,y),fill=(5,9,15,alpha))
    return Image.alpha_composite(img.convert('RGBA'),overlay).convert('RGB')

def render(e,folder):
    """2026-09-29: GPT 개편 디자인(tools/campaign27_design.py, 짙은 그린·라임·오렌지)을 쓴다."""
    import importlib.util
    spec=importlib.util.spec_from_file_location('campaign27_design',Path(__file__).with_name('campaign27_design.py'))
    D=importlib.util.module_from_spec(spec); spec.loader.exec_module(D)
    frames=D.render_frames(e,ROOT)
    manifest=[]
    for name,img,speech in frames:
        img.save(folder/(name+'.png'))
        manifest.append(dict(name=name,file=name+'.png',narration=speech,width=W,height=H,design='editorial-v2'))
    BOXES.extend(D.BOUNDS); D.BOUNDS.clear()
    return manifest

def render_legacy(e,folder):
    frames=[]
    img=photo(e); d=chrome(img,e,'',True)
    textblock(d,e['hook'],72,1050,850,100,'white',350)
    textblock(d,'AI 연출 이미지 · 계산 조건은 본문',72,1440,850,26,'#d0d2d5',50)
    frames.append(('01-cover',img,e['narration'][0]))
    for i,c in enumerate(e['cards']):
        img=T.background(W,H,T.get_theme('paper')); d=chrome(img,e,f'{i+1:02d} / {len(e["cards"]):02d}')
        d.rectangle((36,320,43,1420),fill='#ded8ce')
        d.rectangle((36,320,43,320+int(1100*(i+1)/len(e['cards']))),fill=ACCENT)
        y=textblock(d,c['title'],72,390,850,76,max_height=210)
        d.rectangle((84,680,937,926),fill=INK)
        d.rectangle((72,668,925,914),fill=ACCENT)
        textblock(d,c['figure'],104,728,790,94,'white',150)
        textblock(d,c['body'],72,1020,850,51,INK,350,weight='Medium')
        # Assumption visible on every calculation card, including sources-based episodes.
        note='설명용 가정 포함 · 상세 조건/출처는 캡션' if '가정' in e['assumptions'] else '공식 안내 기준 · 조건/출처는 캡션'
        textblock(d,note,72,1420,850,28,SOFT,55)
        frames.append((f'{i+2:02d}-body',img,e['narration'][i+1]))
    img=T.background(W,H,T.get_theme('paper')); d=chrome(img,e,'돈값하나의 결론')
    key=e.get('key') or {}
    if key:
        textblock(d,key['label'],72,420,850,44,SOFT,70,weight='Medium')
        d.rectangle((84,512,937,738),fill=INK)
        d.rectangle((72,500,925,726),fill=ACCENT)
        textblock(d,key['figure'],104,560,790,96,'white',140)
        d.rectangle((72,840,185,852),fill=ACCENT)
        textblock(d,e['verdict_text'],72,900,850,80,INK,480)
    else:
        d.rectangle((72,502,185,514),fill=ACCENT)
        textblock(d,e['verdict_text'],72,650,850,86,INK,540)
    textblock(d,'가정 포함 계산 · 조건과 출처는 캡션' if '가정' in e['assumptions'] else '공식 안내 기준 · 조건과 출처는 캡션',72,1420,850,28,SOFT,55)
    frames.append(('06-conclusion',img,e['narration'][-1]))
    for p in ['instagram','youtube']:
        img=Image.new('RGB',(W,H),'#111820'); d=chrome(img,e,'다음 돈 계산도 함께',True)
        textblock(d,e['question'],72,520,850,82,'white',350)
        d.rectangle((72,1040,925,1215),fill=ACCENT)
        textblock(d,e['cta'][p]['screen'],103,1070,780,80,'white',125)
        frames.append(('07-'+p+'-cta',img,e['cta'][p]['narration']))
    manifest=[]
    for name,img,speech in frames:
        img.save(folder/(name+'.png'))
        manifest.append(dict(name=name,file=name+'.png',narration=speech,width=W,height=H))
    return manifest

def save_text(e,folder):
    for name,key in [('instagram-caption.txt','caption'),('youtube-description.txt','youtube_description'),('youtube-title.txt','yt_title'),('threads.txt','threads_text')]:
        (folder/name).write_text(e[key]+'\n',encoding='utf8')
    for platform in ['instagram','youtube']:
        speech='\n\n'.join(e['narration']+[e['cta'][platform]['narration']])
        (folder/f'tts-{platform}.txt').write_text(speech+'\n',encoding='utf8')
    (folder/'content.json').write_text(json.dumps(e,ensure_ascii=False,indent=2),encoding='utf8')
    md='# '+e['product']+'\n\n'
    md+='\n\n'.join(f'## {s[0]}\n\n{s[1]}' for s in [('표지',e['hook'])]+[(f'본문 {i+1}',c['title']+'\n\n'+c['figure']+'\n\n'+c['body']) for i,c in enumerate(e['cards'])]+[('결론',e['verdict_text']),('인스타 CTA',e['question']+'\n\n'+e['cta']['instagram']['screen']),('유튜브 CTA',e['question']+'\n\n'+e['cta']['youtube']['screen']),('계산 조건과 출처',e['assumptions']+'\n\n'+'\n'.join(e['sources']))])
    (folder/'제작원고.md').write_text(md,encoding='utf8')

def ffmpeg():
    found=shutil.which('ffmpeg')
    if found: return found
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()

VOICE=os.getenv('CAMPAIGN_TTS_VOICE','ko-KR-SunHiNeural')
RATE=os.getenv('CAMPAIGN_TTS_RATE','+22%')

def speakable(text):
    """화면용 기호를 소리 내 읽을 말로. 나레이션 원고는 이미 말투로 쓰지만 안전망으로 둔다."""
    t=text
    for a,b in [('%p','퍼센트포인트'),('%','퍼센트'),('km/L','킬로미터'),('km','킬로미터'),('K-패스','케이패스'),
                ('K패스','케이패스'),('1+1','원 플러스 원'),(' vs ',' 대 '),('×','곱하기'),('→',' 에서 '),('·',', ')]:
        t=t.replace(a,b)
    t=re.sub(r'(\d)\s*~\s*(\d)',r'\1에서 \2',t)
    t=t.replace('~',' ').replace('?.','?').replace('..','.')
    return re.sub(r'\s{2,}',' ',t).strip()

def run(args):
    r=subprocess.run(args,capture_output=True,text=True,encoding='utf8',errors='replace')
    if r.returncode: raise RuntimeError(r.stderr[-1800:])
    return r

def synth_one(job):
    import edge_tts
    folder,s=job; path=folder/(s['name']+'.mp3')
    speech=speakable(s['narration'])
    digest=hashlib.sha256(f'{VOICE}|{RATE}|{speech}'.encode()).hexdigest()
    stamp=path.with_suffix('.sha256')
    if not path.exists() or path.stat().st_size<1000 or not stamp.exists() or stamp.read_text()!=digest:
        last=None
        for attempt in range(3):
            try:
                async def go():
                    await edge_tts.Communicate(speech, VOICE, rate=RATE).save(str(path))
                asyncio.run(go()); break
            except Exception as exc:  # 네트워크 일시 오류만 재시도, 3번 실패하면 멈춘다(무음 발행 금지)
                last=exc; import time; time.sleep(2*(attempt+1))
        else:
            raise RuntimeError(f'TTS 실패 {s["name"]}: {last}')
        if path.stat().st_size<1000: raise RuntimeError(f'TTS 결과가 비었습니다: {path}')
        stamp.write_text(digest)
    wav=folder/(s['name']+'.wav')
    run([ffmpeg(),'-y','-v','error','-i',str(path),'-ac','1','-ar','24000',str(wav)])
    with wave.open(str(wav),'rb') as w:
        duration=w.getnframes()/w.getframerate()
    wav.unlink()
    return dict(name=s['name'],duration=duration,audio=path.name)

def encode_one(job):
    folder,s,a=job; target=folder/(s['name']+'.mp4')
    dur=math.ceil((a['duration']+.65)*24)/24
    digest=hashlib.sha256((folder/s['file']).read_bytes()+(folder/a['audio']).read_bytes()+str(dur).encode()).hexdigest()
    stamp=target.with_suffix('.sha256')
    if not target.exists() or not stamp.exists() or stamp.read_text()!=digest:
        run([ffmpeg(),'-y','-v','error','-loop','1','-framerate','24','-i',str(folder/s['file']),'-i',str(folder/a['audio']),
             '-t',str(dur),'-vf','scale=1080:1920,setsar=1','-af','adelay=120,apad',
             '-c:v','libx264','-preset','veryfast','-tune','stillimage','-crf','23','-pix_fmt','yuv420p','-r','24','-threads','2',
             '-c:a','aac','-ar','48000','-ac','2','-b:a','128k',str(target)])
        stamp.write_text(digest)
    return dict(**s,duration=dur,segment=target.name,audio=a['audio'])

def probe(path):
    """(길이 초, 평균 음량 dB). 평균 음량이 너무 낮으면 무음으로 본다."""
    r=subprocess.run([ffmpeg(),'-v','info','-i',str(path),'-af','volumedetect','-f','null','-'],capture_output=True,text=True,encoding='utf8',errors='replace')
    m=re.search(r'Duration: (\d+):(\d+):([\d.]+)',r.stderr); v=re.search(r'mean_volume: (-?[\d.]+) dB',r.stderr)
    dur=int(m.group(1))*3600+int(m.group(2))*60+float(m.group(3)) if m else 0.0
    return dur,(float(v.group(1)) if v else -99.0)

def add_music(folder,platform,seed):
    """말(영상 오디오) 아래에 자체 합성 배경음을 낮게 깔고, 말할 때 더 눌러 준다."""
    src=folder/f'{platform}.mp4'; dur,_=probe(src)
    try:
        from src import audio as A
        wav=A._write_wav(folder/f'bgm-{platform}.wav',A.synth_loop(seed,dur+1,'calm'))
    except Exception as exc:
        print('[bgm] 배경음 합성 실패 → 나레이션만 사용:',exc,flush=True); return
    db=os.getenv('CAMPAIGN_MUSIC_DB','-22')
    fc=(f'[1:a]atrim=0:{dur:.3f},afade=t=in:st=0:d=0.5,afade=t=out:st={max(0,dur-1.2):.3f}:d=1.2,'
        f'volume={db}dB,aformat=sample_rates=48000:channel_layouts=stereo[m];'
        '[0:a]aformat=sample_rates=48000:channel_layouts=stereo,asplit=2[v1][vk];'
        '[m][vk]sidechaincompress=threshold=0.03:ratio=6:attack=15:release=400[md];'
        '[v1][md]amix=inputs=2:duration=first:dropout_transition=0:normalize=0,alimiter=limit=0.95[a]')
    tmp=folder/f'{platform}.mix.mp4'
    run([ffmpeg(),'-y','-v','error','-i',str(src),'-i',str(wav),'-filter_complex',fc,'-map','0:v','-map','[a]',
         '-c:v','copy','-c:a','aac','-b:a','160k','-ar','48000','-movflags','+faststart',str(tmp)])
    tmp.replace(src); wav.unlink()

def assemble(folder,scenes,seed=''):
    for p in ['instagram','youtube']:
        chosen=scenes[:6]+[next(s for s in scenes if s['name']==f'07-{p}-cta')]
        concat=folder/f'{p}-concat.txt'
        concat.write_text(''.join("file '"+s['segment']+"'\n" for s in chosen),encoding='utf8')
        run([ffmpeg(),'-y','-v','error','-f','concat','-safe','0','-i',str(concat),'-c','copy','-movflags','+faststart',str(folder/f'{p}.mp4')])
        concat.unlink()
        if os.getenv('CAMPAIGN_MUSIC','1')!='0': add_music(folder,p,seed or folder.name)
        audio_concat=folder/f'{p}-audio-concat.txt'
        audio_concat.write_text(''.join("file '"+s['audio']+"'\n" for s in chosen),encoding='utf8')
        run([ffmpeg(),'-y','-v','error','-f','concat','-safe','0','-i',str(audio_concat),'-c:a','libmp3lame','-q:a','3',str(folder/f'narration-{p}.mp3')])
        audio_concat.unlink()
        # Decode every final frame and audio sample; encoder success alone is not validation.
        result=run([ffmpeg(),'-v','error','-i',str(folder/f'{p}.mp4'),'-f','null','-'])
        if result.stderr.strip(): raise RuntimeError(result.stderr)
        timeline=[]; now=0
        for s in chosen:
            timeline.append(dict(start=round(now,3),end=round(now+s['duration'],3),file=s['file'],narration=s['narration']))
            now+=s['duration']
        (folder/f'timeline-{p}.json').write_text(json.dumps(timeline,ensure_ascii=False,indent=2),encoding='utf8')
        dur,mean=probe(folder/f'{p}.mp4')
        if abs(dur-now)>1.0: raise RuntimeError(f'{p}.mp4 길이 {dur:.2f}s ≠ 장면 합계 {now:.2f}s')
        if mean<-40: raise RuntimeError(f'{p}.mp4 평균 음량 {mean}dB — 무음으로 판단, 발행 금지')
        report=json.loads((folder/'verify.json').read_text()) if (folder/'verify.json').exists() else {}
        report[p]=dict(duration=round(dur,2),mean_volume_db=mean,scenes=[s['file'] for s in chosen],
                       sha256=hashlib.sha256((folder/f'{p}.mp4').read_bytes()).hexdigest(),
                       bytes=(folder/f'{p}.mp4').stat().st_size)
        (folder/'verify.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')

def gallery(out,items):
    cards=[]
    for e in items:
        folder=out/e['id']; paths=list(folder.glob('*.png'))
        if not paths: continue
        cards.append(f'<article><h2>{e["order"]:02d}. {html.escape(e["product"])}</h2><div class="scenes">'+''.join(f'<a href="{e["id"]}/{p.name}"><img loading="lazy" src="{e["id"]}/{p.name}" alt="{p.stem}"></a>' for p in paths)+'</div>'+''.join(f'<p><a href="{e["id"]}/{p}">{label}</a></p>' for p,label in [('제작원고.md','장면 원고·계산 조건'),('instagram-caption.txt','인스타 캡션'),('youtube-description.txt','유튜브 설명'),('threads.txt','스레드 글'),('tts-instagram.txt','인스타 나레이션'),('tts-youtube.txt','유튜브 나레이션')])+''.join(f'<video controls preload="none" src="{e["id"]}/{p}.mp4" poster="{e["id"]}/01-cover.png"></video>' for p in ['instagram','youtube'] if (folder/f'{p}.mp4').exists())+'</article>')
    page='<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>돈값하나 27편 제작실</title><style>body{background:#f5f1e9;color:#17191e;font-family:Arial,sans-serif;margin:32px}h1{font-size:44px}article{border-top:3px solid #ef5b35;padding:20px 0;margin:32px 0}.scenes{display:flex;gap:12px;overflow-x:auto;padding:8px 0}.scenes img{width:180px;border-radius:8px}a{color:#9b3016}video{width:270px;margin:12px}p{display:inline-block;margin-right:20px}</style><h1>돈값하나 · 27편</h1><p>표지 → 본문 4장 → 결론 → 플랫폼별 마지막 장. 마지막 장 2개를 한 영상에 붙이지 않습니다.</p>'+''.join(cards)+'</html>'
    (out/'index.html').write_text(page,encoding='utf8')

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--out',type=Path,required=True); ap.add_argument('--audio',action='store_true'); ap.add_argument('--video',action='store_true'); ap.add_argument('--only',type=int,nargs='*'); ap.add_argument('--ready',action='store_true',help='표지가 준비된 편만'); ap.add_argument('--keep-cache',action='store_true'); args=ap.parse_args()
    build(args.out,only=args.only,audio=args.audio,video=args.video,ready=args.ready,keep_cache=args.keep_cache)

def build(out,only=None,audio=False,video=False,ready=False,keep_cache=False):
    """out/<id>/ 에 장면 PNG·음성·영상·캡션을 만든다. 만든 편 목록을 돌려준다."""
    out=Path(out)
    from codex import campaign27 as C   # 원고 원본에서 바로 만든다(JSON 사본을 거치지 않음)
    data=C.package(); items=data['items']
    selected=[e for e in items if (not only or e['order'] in only or e['id'] in only) and (not ready or e.get('cover_ready'))]
    out.mkdir(parents=True,exist_ok=True)
    jobs=[]
    for e in selected:
        folder=out/e['id']
        # 이전 렌더 결과(음성·영상·장면)가 남아 새 원고와 섞이지 않도록 매번 비운다.
        if folder.exists() and not keep_cache: shutil.rmtree(folder)
        folder.mkdir(exist_ok=True)
        save_text(e,folder)
        manifest=render(e,folder)
        (folder/'scenes.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf8')
        Image.open(folder/'01-cover.png').convert('RGB').save(folder/'cover.jpg',quality=92,optimize=True)
        jobs += [(folder,s) for s in manifest]
        print('Rendered',e['id'],flush=True)
    (out/'text-bounds.json').write_text(json.dumps(BOXES,ensure_ascii=False),encoding='utf8')
    if audio or video:
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            audios=list(pool.map(synth_one,jobs))
        print('Audio complete',len(audios),flush=True)
        if video:
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                videos=list(pool.map(encode_one,[(f,s,a) for (f,s),a in zip(jobs,audios)]))
            for i,e in enumerate(selected):
                assemble(out/e['id'],videos[i*8:(i+1)*8],e['id']); print('Video verified',e['id'],flush=True)
    gallery(out,items)
    (out/'campaign27.json').write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print('Done',out,flush=True)
    return selected

if __name__=='__main__': main()
