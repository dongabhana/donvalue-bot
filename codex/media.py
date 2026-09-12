"""Render short readable cards and original synthesized audio; no external samples."""
import hashlib
import json
import math
import os
import subprocess
import wave
import tempfile
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont


@lru_cache(maxsize=32)
def font(size):
    candidates = [os.getenv('CODEX_FONT', ''), '/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc']
    for name in candidates:
        if name and Path(name).is_file():
            return ImageFont.truetype(name, size, index=1 if name.endswith('.ttc') else 0)
    raise RuntimeError('A Korean font is required; refusing to render missing glyphs')


def lines(draw, text, size, width):
    result = []
    for paragraph in text.split('\n'):
        current = ''
        for char in paragraph:
            if draw.textlength(current + char, font=font(size)) > width:
                result.append(current)
                current = char
            else:
                current += char
        result.append(current)
    return result


def audio(path, seconds, bpm=88):
    sr = 24000
    n = int(sr * seconds)
    x = np.zeros(n, dtype=np.float64)
    rng = np.random.default_rng(61824)
    beat = 60 / bpm
    notes = [48, 55, 60, 55, 45, 52, 57, 52]
    for i in range(int(seconds / beat)):
        pos = int(i * beat * sr)
        length = min(int(.52 * sr), n-pos)
        t = np.arange(length) / sr
        hz = 440 * 2 ** ((notes[i % len(notes)] - 69) / 12)
        envelope = np.minimum(t/.015, 1) * np.exp(-t*7)
        x[pos:pos+length] += .12 * np.sin(2*math.pi*hz*t)*envelope
        length = min(int(.1*sr), n-pos)
        t = np.arange(length)/sr
        if i % 2 == 0:
            x[pos:pos+length] += .12*np.sin(2*math.pi*(65*t-100*t*t))*np.exp(-35*t)
        else:
            x[pos:pos+length] += .015*rng.normal(size=length)*np.exp(-60*t)
    fade = np.minimum(np.arange(n)/sr, 1)*np.minimum(np.arange(n)[::-1]/sr, 1)
    pcm = (np.clip(x*fade, -.8, .8)*32767).astype('<i2')
    with wave.open(str(path), 'wb') as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr); w.writeframes(pcm.tobytes())


def render(item, root):
    if item.get('visual_style')=='checkout_pop':
        return render_pop(item,root)
    digest = hashlib.sha256(json.dumps(item, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]
    directory = root / 'codex' / 'assets' / item['id'] / digest
    manifest = directory / 'manifest.json'
    if manifest.exists():
        return json.loads(manifest.read_text())
    directory.mkdir(parents=True, exist_ok=True)
    paths=[]
    for i, slide in enumerate(item['slides']):
        img = Image.new('RGB', (1080,1350), '#101820'); d=ImageDraw.Draw(img)
        d.rectangle((0,0,1080*(i+1)/len(item['slides']),10),fill='#7FE4D3')
        d.text((76,70),'돈값하나?',font=font(34),fill='#7FE4D3')
        y=220
        for line in lines(d,slide['title'],88,928):
            d.text((76,y),line,font=font(88),fill='white'); y+=112
        y+=65
        for line in lines(d,slide['body'],43,928):
            d.text((76,y),line,font=font(43),fill='#DAE5EC'); y+=67
        if y>1120: raise ValueError('Card body exceeds safe area')
        yy=1160
        for line in lines(d,slide['note'],26,928):
            d.text((76,yy),line,font=font(26),fill='#9AADB9'); yy+=36
        if yy>1270: raise ValueError('Card note exceeds safe area')
        d.text((76,1280),'@dongabhana',font=font(25),fill='#7FE4D3')
        p=directory/f'{i+1:02}.jpg'; img.save(p,quality=94); paths.append(p)
    result={'cards':[str(p.relative_to(root)) for p in paths], 'music':item['music']}
    if item['format']=='reel':
        duration=5.0; wav=directory/'original.wav'; audio(wav,duration*len(paths))
        video=directory/'reel.mp4'
        subprocess.run(['ffmpeg','-y','-loglevel','error','-framerate','1/5','-i',str(directory/'%02d.jpg'),
            '-i',str(wav),'-vf','scale=1080:1350,pad=1080:1920:0:250:color=0x101820,fps=30',
            '-c:v','libx264','-preset','veryfast','-crf','24','-pix_fmt','yuv420p','-c:a','aac',
            '-b:a','128k','-t',str(duration*len(paths)),'-movflags','+faststart',str(video)],check=True,capture_output=True)
        result['video']=str(video.relative_to(root))
    result['sha256']={p:hashlib.sha256((root/p).read_bytes()).hexdigest() for p in result['cards']+([result['video']] if 'video' in result else [])}
    manifest.write_text(json.dumps(result,ensure_ascii=False,indent=2))
    return result


def pop_card(item,slide,index):
    """Original illustrated shopping scenes, not a screenshot of an actual store."""
    bg='#FFF5E8'; ink='#172025'; coral='#F45B45'; blue='#3449D8'
    accent=blue if item.get('palette')=='blue' else coral
    img=Image.new('RGB',(1080,1350),bg); d=ImageDraw.Draw(img)
    d.rounded_rectangle((60,48,290,106),radius=25,fill=ink)
    d.text((83,53),'돈값하나?',font=font(30),fill=bg)
    d.text((904,60),f'{index+1:02}/{len(item["slides"]):02}',font=font(25),fill=ink)
    y=155
    for line in lines(d,slide['title'],76,960):
        d.text((60,y),line,font=font(76),fill=ink); y+=97
    if y>455: raise ValueError('Shorten scene title to 3 lines')
    y=max(y+20,392)
    for line in lines(d,slide['body'],38,950):
        d.text((64,y),line,font=font(38),fill=ink); y+=58
    if y>590: raise ValueError('Shorten scene body')
    visual=slide.get('visual',{})
    kind=visual.get('kind','question')
    d.rounded_rectangle((66,640,1028,1116),radius=42,fill=ink)
    d.rounded_rectangle((54,628,1016,1104),radius=42,fill=accent)
    if kind in ('cart','total'):
        d.rounded_rectangle((102,674,968,1054),radius=22,fill='white')
        yy=698
        for label,value in visual.get('rows',[]):
            d.text((130,yy),label,font=font(31),fill=ink)
            size=31
            value_width=d.textlength(value,font=font(size))
            d.text((935-value_width,yy),value,font=font(size),fill=ink); yy+=61
        d.line((132,yy+8,936,yy+8),fill='#C8C7C3',width=3)
        total=visual.get('total','')
        d.text((129,yy+28),total,font=font(72),fill=accent)
    elif kind=='versus':
        for i,label in enumerate(visual.get('labels',[])[:2]):
            x=96+i*445
            d.rounded_rectangle((x,730,x+408,1006),radius=24,fill='white')
            yy=774
            for line in label.split('\n'):
                d.text((x+25,yy),line,font=font(42),fill=ink); yy+=76
    elif kind=='timer':
        d.text((158,698),visual.get('label','할인 종료까지'),font=font(35),fill='white')
        d.text((150,774),visual.get('value','00:10'),font=font(154),fill='#FFEF6B')
        d.text((158,989),'예시 화면',font=font(25),fill='white')
    elif kind=='boxes':
        count=visual.get('count',3)
        for i in range(count):
            x=110+(i%3)*285; yy=720+(i//3)*160
            d.rounded_rectangle((x,yy,x+242,yy+131),radius=14,fill='#FFE4B0',outline=ink,width=4)
            d.line((x+118,yy,x+118,yy+130),fill=ink,width=4)
        d.text((114,1015),visual.get('label','물건의 자리만 늘어났다'),font=font(30),fill='white')
    else:
        yy=696
        for label in visual.get('labels',[])[:3]:
            d.rounded_rectangle((100,yy,965,yy+99),radius=23,fill='white')
            d.text((132,yy+18),label,font=font(38),fill=ink); yy+=122
    yy=1152
    for line in lines(d,slide['note'],24,950):
        d.text((64,yy),line,font=font(24),fill='#596367'); yy+=34
    if yy>1260: raise ValueError('Scene note exceeds safe area')
    d.text((64,1280),'@dongabhana',font=font(25),fill=ink)
    d.rectangle((0,1337,1080*(index+1)/len(item['slides']),1349),fill=accent)
    return img


def render_pop(item,root):
    renderer='checkout-pop-v1'
    digest=hashlib.sha256(json.dumps({'item':item,'renderer':renderer},sort_keys=True,ensure_ascii=False).encode()).hexdigest()[:16]
    directory=root/'codex/assets'/item['id']/digest
    manifest=directory/'manifest.json'
    if manifest.exists(): return json.loads(manifest.read_text())
    directory.mkdir(parents=True,exist_ok=True)
    paths=[]
    for i,slide in enumerate(item['slides']):
        p=directory/f'{i+1:02}.jpg'; pop_card(item,slide,i).save(p,quality=94); paths.append(p)
    result={'renderer':renderer,'cards':[str(p.relative_to(root)) for p in paths],'music':item['music']}
    if item['format']=='reel':
        seconds=[float(s.get('seconds',3.5)) for s in item['slides']]
        if not all(2<=s<=6 for s in seconds): raise ValueError('Scene length must be 2 to 6 seconds')
        wav=directory/'original.wav'; audio(wav,sum(seconds),bpm=112)
        video=directory/'reel.mp4'
        with tempfile.TemporaryDirectory(prefix='donvalue-reel-') as temp:
            clips=[]
            for i,(p,duration) in enumerate(zip(paths,seconds)):
                clip=Path(temp)/f'{i:02}.mp4'; clips.append(clip)
                frames=round(duration*30)
                vf=f"zoompan=z='1+0.025*on/{frames}':x='iw/2-iw/zoom/2':y='ih/2-ih/zoom/2':d={frames}:s=1080x1350:fps=30,pad=1080:1920:0:250:color=0xFFF5E8"
                subprocess.run(['ffmpeg','-y','-loglevel','error','-i',str(p),'-vf',vf,'-frames:v',str(frames),'-c:v','libx264','-preset','veryfast','-crf','23','-pix_fmt','yuv420p','-an',str(clip)],check=True,capture_output=True)
            listing=Path(temp)/'clips.txt'; listing.write_text(''.join("file '"+str(c)+"'\n" for c in clips))
            subprocess.run(['ffmpeg','-y','-loglevel','error','-f','concat','-safe','0','-i',str(listing),'-i',str(wav),'-map','0:v','-map','1:a','-c:v','copy','-c:a','aac','-b:a','128k','-t',str(sum(seconds)),'-movflags','+faststart',str(video)],check=True,capture_output=True)
        result['video']=str(video.relative_to(root))
        result['duration_seconds']=sum(seconds)
    result['sha256']={p:hashlib.sha256((root/p).read_bytes()).hexdigest() for p in result['cards']+([result['video']] if 'video' in result else [])}
    manifest.write_text(json.dumps(result,ensure_ascii=False,indent=2))
    return result
