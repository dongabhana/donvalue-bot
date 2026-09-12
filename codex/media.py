"""Render short readable cards and original synthesized audio; no external samples."""
import hashlib
import json
import math
import os
import subprocess
import wave
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont


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


def audio(path, seconds):
    sr, bpm = 24000, 88
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
