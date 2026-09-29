"""Render complete 9:16 campaign; never publish, truncate cards or silently drop audio."""
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
    from campaign27_design import render_frames, BOUNDS
    frames=render_frames(e,ROOT)
    manifest=[]
    for name,img,speech in frames:
        img.save(folder/(name+'.png'))
        manifest.append(dict(name=name,file=name+'.png',narration=speech,width=W,height=H,design='editorial-v2'))
    BOXES.extend(BOUNDS); BOUNDS.clear()
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
        note='설명용 가정 포함 · 상세 조건/출처는 캡션'
        textblock(d,note,72,1420,850,28,SOFT,55)
        frames.append((f'{i+2:02d}-body',img,e['narration'][i+1]))
    img=T.background(W,H,T.get_theme('paper')); d=chrome(img,e,'돈값하나의 결론')
    d.rectangle((72,502,185,514),fill=ACCENT)
    textblock(d,e['verdict_text'],72,650,850,86,INK,540)
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
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()

def run(args):
    r=subprocess.run(args,capture_output=True,text=True,encoding='utf8',errors='replace')
    if r.returncode: raise RuntimeError(r.stderr[-1800:])
    return r

def synth_one(job):
    import edge_tts
    folder,s=job; path=folder/(s['name']+'.mp3')
    digest=hashlib.sha256(('ko-KR-SunHiNeural|+15%|'+s['narration']).encode()).hexdigest()
    stamp=path.with_suffix('.sha256')
    if not path.exists() or path.stat().st_size<1000 or not stamp.exists() or stamp.read_text()!=digest:
        async def go():
            await edge_tts.Communicate(s['narration'], 'ko-KR-SunHiNeural', rate='+15%').save(str(path))
        asyncio.run(go())
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
             '-c:v','libx264','-preset','ultrafast','-tune','stillimage','-crf','22','-pix_fmt','yuv420p','-r','24','-threads','2',
             '-c:a','aac','-ar','48000','-ac','2','-b:a','128k',str(target)])
        stamp.write_text(digest)
    return dict(**s,duration=dur,segment=target.name,audio=a['audio'])

def assemble(folder,scenes):
    for p in ['instagram','youtube']:
        chosen=scenes[:6]+[next(s for s in scenes if s['name']==f'07-{p}-cta')]
        concat=folder/f'{p}-concat.txt'
        concat.write_text(''.join("file '"+s['segment']+"'\n" for s in chosen),encoding='utf8')
        run([ffmpeg(),'-y','-v','error','-f','concat','-safe','0','-i',str(concat),'-c','copy','-movflags','+faststart',str(folder/f'{p}.mp4')])
        concat.unlink()
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

def gallery(out,items):
    cards=[]
    for e in items:
        folder=out/e['id']; paths=list(folder.glob('*.png'))
        if not paths: continue
        cards.append(f'<article><h2>{e["order"]:02d}. {html.escape(e["product"])}</h2><div class="scenes">'+''.join(f'<a href="{e["id"]}/{p.name}"><img loading="lazy" src="{e["id"]}/{p.name}" alt="{p.stem}"></a>' for p in paths)+'</div>'+''.join(f'<p><a href="{e["id"]}/{p}">{label}</a></p>' for p,label in [('제작원고.md','장면 원고·계산 조건'),('instagram-caption.txt','인스타 캡션'),('youtube-description.txt','유튜브 설명'),('threads.txt','스레드 글'),('tts-instagram.txt','인스타 나레이션'),('tts-youtube.txt','유튜브 나레이션')])+''.join(f'<video controls preload="none" src="{e["id"]}/{p}.mp4" poster="{e["id"]}/01-cover.png"></video>' for p in ['instagram','youtube'] if (folder/f'{p}.mp4').exists())+'</article>')
    page='<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>돈값하나 27편 제작실</title><style>body{background:#f5f1e9;color:#17191e;font-family:Arial,sans-serif;margin:32px}h1{font-size:44px}article{border-top:3px solid #ef5b35;padding:20px 0;margin:32px 0}.scenes{display:flex;gap:12px;overflow-x:auto;padding:8px 0}.scenes img{width:180px;border-radius:8px}a{color:#9b3016}video{width:270px;margin:12px}p{display:inline-block;margin-right:20px}</style><h1>돈값하나 · 27편</h1><p>표지 → 본문 4장 → 결론 → 플랫폼별 마지막 장. 마지막 장 2개를 한 영상에 붙이지 않습니다.</p>'+''.join(cards)+'</html>'
    (out/'index.html').write_text(page,encoding='utf8')

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--out',type=Path,required=True); ap.add_argument('--audio',action='store_true'); ap.add_argument('--video',action='store_true'); ap.add_argument('--only',type=int,nargs='*'); args=ap.parse_args()
    data=json.loads((ROOT/'content/campaign27.json').read_text(encoding='utf8')); items=data['items']
    selected=[e for e in items if not args.only or e['order'] in args.only]
    args.out.mkdir(parents=True,exist_ok=True)
    jobs=[]
    for e in selected:
        folder=args.out/e['id']; folder.mkdir(exist_ok=True)
        save_text(e,folder)
        manifest=render(e,folder)
        (folder/'scenes.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf8')
        jobs += [(folder,s) for s in manifest]
        print('Rendered',e['id'],flush=True)
    (args.out/'text-bounds.json').write_text(json.dumps(BOXES,ensure_ascii=False),encoding='utf8')
    if args.audio or args.video:
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            audios=list(pool.map(synth_one,jobs))
        print('Audio complete',len(audios),flush=True)
        if args.video:
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                videos=list(pool.map(encode_one,[(f,s,a) for (f,s),a in zip(jobs,audios)]))
            for i,e in enumerate(selected):
                assemble(args.out/e['id'],videos[i*8:(i+1)*8]); print('Video verified',e['id'],flush=True)
    gallery(args.out,items)
    shutil.copy2(ROOT/'content/campaign27.json',args.out/'campaign27.json')
    print('Done',args.out,flush=True)

if __name__=='__main__': main()
