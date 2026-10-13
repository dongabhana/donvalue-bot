"""Shared dark editorial graphics for campaign and queue reels (1080 x 1920)."""
from functools import lru_cache
from pathlib import Path
import math
import re
from PIL import Image, ImageDraw, ImageFont
from src import theme as T
from src.render import wrap

W, H = 1080, 1920
BG = '#101E21'
PANEL = '#192D30'
EDGE = '#355052'
WHITE = '#F6F3EA'
MUTED = '#A8BCB9'
LIME = '#DBEF9C'
ORANGE = '#FF805D'
BOUNDS = []
VERSION = 'editorial-v3'


@lru_cache(maxsize=256)
def font(size, weight=700):
    path = Path('C:/Windows/Fonts/NotoSansKR-VF.ttf')
    if path.exists():
        f = ImageFont.truetype(str(path), size)
        f.set_variation_by_axes([weight])
        return f
    # Noto CJK distributions often omit Black; Bold is present in the runner.
    return T.font('Bold' if weight >= 650 else 'Regular', size)


def text(d, value, box, size=60, color=WHITE, weight=750, align='left', minimum=28):
    value = str(value or '')
    if not value:
        return
    x, y, width, height = box
    for n in range(size, min(minimum, size) - 1, -1):
        f = font(n, weight)
        lines = wrap(d, value, f, width)
        step = round(n * 1.32)
        if len(lines) * step <= height and all(d.textlength(s, font=f) <= width for s in lines):
            break
    else:
        raise ValueError(f'Text does not fit: {value!r}')
    for line in lines:
        xx = x + (width - d.textlength(line, font=f)) / 2 if align == 'center' else x
        d.text((xx, y), line, font=f, fill=color, anchor='lt')
        b = d.textbbox((xx, y), line, font=f, anchor='lt')
        if b[0] < 60 or b[2] > 958 or b[1] < 120 or b[3] > 1600:
            raise ValueError(f'Unsafe text bounds: {line} {b}')
        BOUNDS.append({'text': line, 'bounds': b, 'font': n})
        y += step


def card(d, box, fill=PANEL, outline=EDGE, radius=30):
    d.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=2)


@lru_cache(maxsize=1)
def background():
    im = Image.new('RGB', (W, H), BG)
    d = ImageDraw.Draw(im)
    # Quiet illumination, identical across every layout.
    for y in range(H):
        light = max(0, 1 - abs(y - 780) / 1000)
        d.line((0, y, W, y), fill=(16+int(light*3), 30+int(light*5), 33+int(light*5)))
    for x in range(80, W, 64):
        for y in range(250, 1650, 64):
            d.point((x, y), fill='#294043')
    return im


def frame(label, step=0, total=4, brand='돈값하나', handle='@dongabhana'):
    im = background().copy()
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((76, 151, 122, 197), radius=15, fill=LIME)
    d.line((88, 173, 98, 183, 113, 164), fill=BG, width=5)
    text(d, brand.rstrip('?'), (140, 152, 510, 60), 36, weight=850)
    text(d, label, (630, 157, 320, 50), 26, MUTED, 550, 'center', 22)
    text(d, handle, (78, 1530, 400, 50), 26, MUTED, 500)
    for i in range(total):
        x = 715 + i * (235 / total)
        d.rounded_rectangle((x, 1541, x + 235 / total - 9, 1547), radius=3,
                            fill=LIME if i < step else EDGE)
    return im, d


def icon(d, kind, x, y, color=LIME, scale=1):
    def box(a,b,c,e): return (x+a*scale,y+b*scale,x+c*scale,y+e*scale)
    w=max(2,round(4*scale))
    if kind == 'clock':
        d.ellipse(box(0,0,80,80), outline=color, width=w)
        d.line([(x+40*scale,y+18*scale),(x+40*scale,y+42*scale),(x+58*scale,y+51*scale)], fill=color,width=w)
    elif kind == 'check':
        d.ellipse(box(0,0,80,80), outline=color,width=w)
        d.line([(x+20*scale,y+40*scale),(x+35*scale,y+54*scale),(x+62*scale,y+24*scale)],fill=color,width=w)
    elif kind == 'bookmark':
        d.line([(x,y+70*scale),(x,y),(x+48*scale,y),(x+48*scale,y+70*scale),(x+24*scale,y+52*scale),(x,y+70*scale)],fill=color,width=w)
    elif kind == 'heart':
        pts=[]
        for i in range(100):
            t=2*math.pi*i/99
            pts.append((x+40*scale+2.2*scale*16*math.sin(t)**3,
                        y+35*scale-2.2*scale*(13*math.cos(t)-5*math.cos(2*t)-2*math.cos(3*t)-math.cos(4*t))))
        d.polygon(pts,fill=color)
    else:
        d.rounded_rectangle(box(0,0,80,80),radius=12,outline=color,width=w)
        d.line(box(17,23,63,23),fill=color,width=w)
        for a,b in [(22,43),(55,43),(22,61),(55,61)]:
            d.ellipse(box(a,b,a+6,b+6),fill=color)


def body(title, figure, detail, index=0, total=4, comparison=None,
         note='설명용 가정 포함 · 상세 조건과 출처는 캡션', brand='돈값하나', handle='@dongabhana'):
    labels=['조건 확인','숫자로 비교','핵심 기준','실행 체크']
    im,d=frame(labels[min(index,3)], index+1,total,brand,handle)
    text(d,f'{index+1:02d}',(78,285,140,115),80,LIME,850)
    text(d,title,(78,421,865,220),82,WHITE,850)
    if not str(figure or '').strip() and not comparison:
        icon(d,'calculator',84,726,LIME,.85)
        text(d,detail,(80,897,864,490),70,WHITE,750)
    elif comparison:
        la,lb,a,b,va,vb=comparison
        vmax=max(float(va),float(vb),1)
        for j,(label,value,v) in enumerate([(la,a,va),(lb,b,vb)]):
            yy=711+j*249
            card(d,(78,yy,946,yy+220))
            text(d,label,(110,yy+26,740,50),31,MUTED,550)
            text(d,value,(110,yy+87,740,99),77,ORANGE if j==0 else LIME,850)
            d.rounded_rectangle((110,yy+186,910,yy+195),radius=4,fill=EDGE)
            if float(v)>0:
                d.rounded_rectangle((110,yy+186,110+800*float(v)/vmax,yy+195),radius=4,fill=ORANGE if j==0 else LIME)
        text(d,detail,(82,1285,857,124),43,WHITE,600)
    elif index==2:
        # The answer scene breaks the panel rhythm while retaining the same palette.
        d.arc((143,660,879,1370),200,340,fill=EDGE,width=3)
        d.arc((194,711,828,1321),210,330,fill='#45625E',width=2)
        d.ellipse((493,704,527,738),fill=ORANGE)
        text(d,figure,(80,850,866,275),142,LIME,900,'center')
        d.line((403,1169,620,1169),fill=ORANGE,width=5)
        text(d,detail,(83,1255,857,160),44,WHITE,600,'center')
    elif index==3:
        bits=[s.strip() for s in re.split(r'[·＋+]',str(figure)) if s.strip()]
        if 1<len(bits)<=3:
            for j,s in enumerate(bits):
                yy=705+j*147
                card(d,(78,yy,946,yy+125))
                icon(d,'check',108,yy+36,scale=.6)
                text(d,s,(187,yy+33,725,75),48,WHITE,750)
        else:
            card(d,(78,700,946,1100))
            icon(d,'check',116,737,ORANGE,.7)
            text(d,figure,(115,836,792,217),80,LIME,850)
        text(d,detail,(80,1210,860,200),45,WHITE,600)
    else:
        card(d,(78,699,946,1115))
        is_time=bool(re.search(r'분|초|시간',str(figure)))
        icon(d,'clock' if is_time else 'calculator',119,741,LIME,.7)
        text(d,'돈값을 가르는 숫자',(205,752,680,55),30,MUTED,550)
        text(d,figure,(111,879,801,207),122,LIME,900)
        # Calculation parts get distinct cells without dropping any copy.
        parts=[s.strip() for s in detail.split('+')]
        if 2<=len(parts)<=4 and all(len(s)<=16 for s in parts):
            count=len(parts)
            width=(868-12*(count-1))/count
            for j,s in enumerate(parts):
                xx=78+j*(width+12)
                card(d,(xx,1175,xx+width,1355),fill='#21373A')
                text(d,s,(xx+18,1210,width-36,128),40,WHITE,650,minimum=26)
        else:
            text(d,detail,(81,1200,858,207),47,WHITE,600)
    text(d,note,(80,1450,864,60),25,MUTED,450,minimum=22)
    return im


def stake(value,brand='돈값하나',handle='@dongabhana'):
    im,d=frame('오늘의 기준',0,4,brand,handle)
    icon(d,'calculator',80,355,LIME,1.15)
    text(d,'이것만 보면 됩니다.',(80,520,860,100),52,MUTED,650)
    text(d,value,(80,697,865,590),95,WHITE,850)
    return im


def conclusion(value,brand='돈값하나',handle='@dongabhana',key=None):
    im,d=frame('돈값하나의 결론',4,4,brand,handle)
    key=key or {}
    if key.get('figure'):
        # 2026-09-29 소유자 요청: 결론 화면에 핵심 숫자를 한 번 더 보여준다.
        text(d,'그래서, 돈값하나?',(80,300,866,90),56,LIME,800)
        text(d,key.get('label',''),(80,420,866,60),36,MUTED,600)
        text(d,key['figure'],(80,490,866,170),104,ORANGE,900)
        card(d,(78,700,947,1265),fill='#21373A')
        d.rounded_rectangle((78,729,86,1236),radius=4,fill=LIME)
        text(d,value,(114,757,794,452),76,WHITE,850)
    else:
        icon(d,'check',80,315,LIME,1.15)
        text(d,'그래서, 돈값하나?',(80,465,866,110),61,LIME,800)
        card(d,(78,646,947,1265),fill='#21373A')
        d.rounded_rectangle((78,675,86,1236),radius=4,fill=LIME)
        text(d,value,(114,703,794,506),85,WHITE,850)
    icon(d,'bookmark',84,1343,ORANGE,.55)
    text(d,'내 조건으로 한 번 더 확인',(135,1347,804,80),39,MUTED,550)
    return im


def cta(question,platform='both',brand='돈값하나',handle='@dongabhana'):
    if platform not in ('instagram','youtube','both'):
        raise ValueError(f'Unknown platform: {platform}')
    im,d=frame('다음 돈값도 함께',4,4,brand,handle)
    text(d,'알면 달라지는',(78,323,862,112),79,WHITE,850)
    text(d,'내 돈의 기준.',(73,448,874,154),110,LIME,900)
    text(d,'매일 하나씩, 생활 속 돈 계산',(80,637,861,85),40,MUTED,550)
    card(d,(78,808,947,1076),fill='#233A3C',radius=36)
    d.rounded_rectangle((110,846,201,937),radius=27,fill=LIME)
    d.line((130,890,149,910,184,865),fill=BG,width=9)
    text(d,brand.rstrip('?'),(227,845,663,70),45,WHITE,850)
    text(d,handle,(227,912,662,58),31,MUTED,500)
    text(d,'다음 선택도, 숫자로 확인하세요.',(111,1000,792,60),31,WHITE,600)
    action='구독' if platform=='youtube' else '팔로우'
    d.rounded_rectangle((78,1110,946,1238),radius=32,fill=ORANGE)
    icon(d,'heart',110,1152,BG,.48)
    text(d,'좋아요  +  '+action,(192,1145,670,80),49,BG,850,'center')
    if platform=='both':
        text(d,'유튜브에서는 구독으로 함께해요',(82,1260,860,55),28,MUTED,500)
    text(d,'댓글로 알려주세요',(80,1335,860,55),28,LIME,650)
    text(d,question,(80,1390,860,114),41,WHITE,750)
    return im
