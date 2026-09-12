"""Render short readable cards and original synthesized audio; no external samples."""
import hashlib
import json
import math
import os
import subprocess
import wave
import tempfile
import re
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
        for token in re.findall(r'\S+\s*', paragraph):
            if current and draw.textlength(current + token.rstrip(), font=font(size)) > width:
                result.append(current.rstrip())
                current = ''
            if draw.textlength(token.rstrip(), font=font(size)) > width:
                for char in token:
                    if current and draw.textlength(current + char, font=font(size)) > width:
                        result.append(current.rstrip()); current = ''
                    current += char
            else:
                current += token
        result.append(current.rstrip())
    return result


def audio(path, seconds, bpm=88, punch=False):
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
    fade = np.minimum(np.arange(n)[::-1]/sr, 1)
    if not punch: fade *= np.minimum(np.arange(n)/sr, 1)
    pcm = (np.clip(x*fade, -.8, .8)*32767).astype('<i2')
    with wave.open(str(path), 'wb') as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr); w.writeframes(pcm.tobytes())


def render(item, root):
    if item.get('visual_style') == 'money_editorial_v2':
        return render_editorial(item, root)
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


def fitted_font(draw, text, max_size, width, minimum=24):
    size = max_size
    while size > minimum and draw.textlength(text, font=font(size)) > width:
        size -= 2
    if draw.textlength(text, font=font(size)) > width:
        raise ValueError('Text exceeds its reserved visual area')
    return font(size)


def pictogram(d, category, x, y, size, ink):
    """Repo-native vector pictograms, not product or manufacturer imagery."""
    s=size/120
    def box(a,b,c,e,r=8,fill=None):
        d.rounded_rectangle((x+a*s,y+b*s,x+c*s,y+e*s),radius=r*s,
                            fill=fill,outline=ink,width=max(2,round(5*s)))
    def line(points):
        d.line([(x+a*s,y+b*s) for a,b in points],fill=ink,width=max(2,round(5*s)))
    if category=='IT':
        box(8,10,110,80); line([(8,96),(110,96),(120,108),(0,108),(8,96)])
        line([(41,49),(55,64),(79,30)])
    elif category=='결제':
        box(22,0,98,116); line([(36,28),(84,28)]); line([(36,49),(74,49)])
        line([(36,78),(82,78)]); line([(60,72),(60,104)])
    elif category=='구독':
        box(8,16,110,110); line([(8,42),(110,42)]); line([(33,0),(33,31)])
        line([(84,0),(84,31)]); line([(39,75),(53,89),(82,57)])
    elif category=='생활용품':
        box(35,28,89,112,r=12); box(40,2,83,30,r=4); line([(49,57),(75,57)])
        line([(49,77),(75,77)])
    elif category=='가전':
        box(9,6,109,114); box(26,25,92,90,r=32); line([(77,9),(95,9)])
    elif category=='외식':
        box(21,15,105,101,r=48); box(43,37,83,78,r=30)
        line([(2,11),(2,110)]); line([(114,10),(114,110)])
    elif category=='이동':
        box(9,8,109,106,r=16); box(22,21,96,65,r=5)
        line([(28,84),(35,84)]); line([(85,84),(92,84)])
        line([(27,110),(27,120)]); line([(91,110),(91,120)])
    else:
        box(9,16,109,110); line([(9,48),(109,48)]); line([(59,16),(59,110)])
        line([(35,5),(59,19),(81,5)])


def editorial_card(item, slide, index, reel=False):
    ink='#151819'; paper='#F6F6F0'; gray='#686C67'
    accent=item.get('accent','#E6F34A'); cover=index==0
    bg=ink if cover else paper
    fg=paper if cover else ink
    img=Image.new('RGB',(1080,1350),bg); d=ImageDraw.Draw(img)
    d.text((62,56),'돈값하나?',font=font(31),fill=fg)
    tag=item['category']+' · '+item['series']
    tagfont=fitted_font(d,tag,25,610)
    tagw=d.textlength(tag,font=tagfont)+38
    d.rounded_rectangle((1018-tagw,51,1018,101),radius=23,fill=accent)
    d.text((1037-tagw,58),tag,font=tagfont,fill=ink)
    d.text((64,124),f'EP. {int(item["id"][2:5])-3:02}   ·   {index+1:02} / {len(item["slides"]):02}',
           font=font(23),fill='#ABB0A4' if cover else gray)
    title_size=110 if cover else 76
    explicit=slide['title'].split('\n')
    while title_size>54 and any(d.textlength(t,font=font(title_size))>936 for t in explicit):
        title_size-=2
    title_lines=lines(d,slide['title'],title_size,936)
    if len(title_lines)>3: raise ValueError('Headline exceeds three lines')
    y=187
    for i,line in enumerate(title_lines):
        color=accent if cover and i==len(title_lines)-1 else fg
        d.text((62,y),line,font=font(title_size),fill=color); y+=title_size*1.2
    if y>545: raise ValueError('Headline exceeds its safe area')
    y=y+44 if not cover else y+24
    body_size=48 if not cover else 32
    while body_size>34 and y+len(lines(d,slide['body'],body_size,926))*body_size*1.4>690:
        body_size-=2
    for line in lines(d,slide['body'],body_size,926):
        d.text((66,y),line,font=font(body_size),fill=fg); y+=body_size*1.4
    if y>690: raise ValueError('Body exceeds its safe area')
    top=628 if cover else max(660,y+36)
    d.rounded_rectangle((76,top+14,1026,1116),radius=36,fill='#303632' if cover else '#D9DBD1')
    d.rounded_rectangle((62,top,1012,1102),radius=36,fill=accent if cover else ink)
    panelink=ink if cover else paper
    visual=slide['visual']
    label=visual.get('label','')
    d.text((104,top+39),label,font=fitted_font(d,label,27,662),fill=panelink)
    if not visual.get('rows'):
        pictogram(d,item['category'],806,top+39,128,panelink)
    value=visual.get('value','')
    if visual.get('rows'):
        yy=top+108
        for label,amount in visual['rows']:
            d.text((104,yy),label,font=font(30),fill=panelink)
            af=fitted_font(d,amount,39,380)
            d.text((934-d.textlength(amount,font=af),yy-5),amount,font=af,fill=accent if not cover else panelink)
            yy+=64
    else:
        vf=fitted_font(d,value,122 if cover else 100,834,minimum=44)
        d.text((99,top+168 if cover else top+137),value,font=vf,fill=panelink if cover else accent)
    if cover:
        d.line((105,top+335,927,top+335),fill=ink,width=3)
        d.text((105,top+361),'가격표 → 실제 합계 → 내 선택',font=font(28),fill=ink)
    yy=1165
    for line in lines(d,slide['note'],24,936):
        d.text((66,yy),line,font=font(24),fill='#ABB0A4' if cover else gray); yy+=36
    if yy>1270: raise ValueError('Footnote exceeds its safe area')
    d.text((66,1281),'@dongabhana',font=font(23),fill=fg)
    d.text((846,1281),'직접 따져봄',font=font(21),fill=fg)
    d.rectangle((0,1339,1080*(index+1)/len(item['slides']),1349),fill=accent)
    if reel:
        canvas=Image.new('RGB',(1080,1920),bg)
        canvas.paste(img,(0,180))
        rd=ImageDraw.Draw(canvas)
        rd.text((66,1640),item['series'],font=font(27),fill=fg)
        note='요금 기준: 서울 중형 · 귀가 총액은 가상 예시' if item.get('verification',{}).get('kind')=='official_tariff_and_illustrative_comparison' else '가상 예시 · 조건에 따라 결과는 달라집니다'
        rd.text((66,1700),note,font=font(22),fill='#ABB0A4' if cover else gray)
        return canvas
    return img


def render_editorial(item, root):
    renderer='money-editorial-v2.4'
    digest=hashlib.sha256(json.dumps({'item':item,'renderer':renderer},sort_keys=True,ensure_ascii=False).encode()).hexdigest()[:16]
    directory=root/'codex/assets'/item['id']/digest
    manifest=directory/'manifest.json'
    if manifest.exists(): return json.loads(manifest.read_text())
    directory.mkdir(parents=True,exist_ok=True)
    paths=[]
    for i,slide in enumerate(item['slides']):
        p=directory/f'{i+1:02}.jpg'
        editorial_card(item,slide,i).save(p,quality=94); paths.append(p)
    result={'renderer':renderer,'cards':[str(p.relative_to(root)) for p in paths], 'music':item['music']}
    if item['format']=='reel':
        seconds=[float(s['seconds']) for s in item['slides']]
        if not 1<=seconds[0]<=2 or not all(2<=s<=6 for s in seconds[1:]):
            raise ValueError('Invalid reel timing')
        wav=directory/'original.wav'; audio(wav,sum(seconds),bpm=112,punch=True)
        video=directory/'reel.mp4'
        with tempfile.TemporaryDirectory(prefix='donvalue-editorial-') as temp:
            clips=[]
            for i,(slide,duration) in enumerate(zip(item['slides'],seconds)):
                frame=Path(temp)/f'{i:02}.jpg'; editorial_card(item,slide,i,reel=True).save(frame,quality=95)
                clip=Path(temp)/f'{i:02}.mp4'; clips.append(clip)
                frames=round(duration*30)
                motion=f"zoompan=z='1+0.035*(1-on/{frames})':x='iw/2-iw/zoom/2':y='ih/2-ih/zoom/2':d={frames}:s=1080x1920:fps=30"
                subprocess.run(['ffmpeg','-y','-loglevel','error','-i',str(frame),'-vf',motion,
                    '-frames:v',str(frames),'-c:v','libx264','-preset','veryfast','-crf','23','-pix_fmt','yuv420p','-an',str(clip)],
                    check=True,capture_output=True)
            listing=Path(temp)/'clips.txt'; listing.write_text(''.join("file '"+str(c)+"'\n" for c in clips))
            subprocess.run(['ffmpeg','-y','-loglevel','error','-f','concat','-safe','0','-i',str(listing),'-i',str(wav),
                '-map','0:v','-map','1:a','-c:v','copy','-c:a','aac','-b:a','128k','-t',str(sum(seconds)),
                '-movflags','+faststart',str(video)],check=True,capture_output=True)
        result['video']=str(video.relative_to(root)); result['duration_seconds']=sum(seconds)
        result['opening_seconds']=seconds[0]
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
