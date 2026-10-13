"""Editorial v3: shared dark layouts, calculation cells, compact platform CTA."""
from pathlib import Path
import math, re
from functools import lru_cache
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageOps
from src import theme as T
from src.render import wrap
from codex.campaign27_screen_copy import SCREEN

W,H=1080,1920
BG='#F4F1EB'; INK='#192124'; ORANGE='#EE613F'; MUTED='#69716F'; DARK='#162022'; WHITE='#F6F3EA'; LIME='#D8EAA0'
BOUNDS=[]

@lru_cache(maxsize=256)
def font(size,weight=700):
    p=Path('C:/Windows/Fonts/NotoSansKR-VF.ttf')
    if p.exists():
        f=ImageFont.truetype(str(p),size); f.set_variation_by_axes([weight]); return f
    return T.font('Black' if weight>=800 else 'Bold' if weight>=650 else 'Regular',size)

def txt(d,s,x,y,w,size=64,fill=INK,height=400,weight=700,leading=1.2):
    if not s:return y
    for n in range(size,min(size,26)-1,-2):
        f=font(n,weight);lines=wrap(d,s,f,w);step=round(n*leading)
        if len(lines)*step<=height and max(d.textlength(l,font=f) for l in lines)<=w:break
    else:raise ValueError('Overflow '+s)
    for line in lines:
        d.text((x,y),line,font=f,fill=fill)
        bounds=d.textbbox((x,y),line,font=f)
        if bounds[0]<58 or bounds[2]>972 or bounds[1]<125 or bounds[3]>1600:raise ValueError((line,bounds))
        BOUNDS.append({'text':line,'bounds':bounds,'font':n})
        y+=step
    return y

def frame(e,dark=False):
    im=Image.new('RGB',(W,H),DARK if dark else BG);d=ImageDraw.Draw(im)
    color=WHITE if dark else INK
    d.rounded_rectangle((66,150,112,196),radius=14,fill=ORANGE)
    d.line((78,174,88,183,102,163),fill=WHITE,width=5)
    txt(d,'돈값하나',128,145,600,35,color,65,800)
    txt(d,f'{e["order"]:02d}',879,144,80,34,MUTED,60,500)
    d.line((68,230,952,230),fill='#36403F' if dark else '#D8DBD2',width=2)
    return im,d

def footer(d,index,dark=False,note='설명용 가정 포함 · 상세 조건은 캡션'):
    txt(d,note,68,1436,884,27,'#9AA5A0' if dark else MUTED,80,400)
    for k in range(4):
        d.rounded_rectangle((68+k*224,1545,276+k*224,1551),radius=3,fill=(LIME if dark else ORANGE) if k<=index else ('#35403D' if dark else '#D8DBD2'))

COMPARE={
(2,0):('2년마다 교체','4년 사용','320만원','160만원',320,160),
(2,1):('2년 사용 / 하루','4년 사용 / 하루','2,192원','1,096원',2192,1096),
(4,0):('가솔린 1.6 공인연비','하이브리드 공인연비','15.0km/L','21.1km/L',15.0,21.1),
(4,1):('가솔린 / 1km','하이브리드 / 1km','113원','81원',113,81),
(5,1):('일반 · 평소 시간','일반 · 시차 시간대','20%','50%',20,50),
(10,0):('프리미엄 / 월','프리미엄 라이트 / 월','14,900원','8,500원',14900,8500),
(7,2):('현금성 지출 / 월','감가 / 월','17만원','20만원',17,20),
(13,0):('국내 표시가','해외 표시가','50만원','40만원',50,40)
}

def render_body(e,i):
    from src import editorial_design as D
    c=e['cards'][i]; n=e['order']
    note='가정값 · 시간가치 ≠ 현금 수입' if n in [1,6,8,9,10,14,15,18] else '설명용 가정 포함 · 상세 조건과 출처는 캡션'
    if n==5: note='2026년 12월까지 · 정률 기준 / 이용 조건 확인'
    if n==23: note='지급률은 전체 평균 · 개인 당첨액 보장 아님'
    title='하루 본전 시간' if (n,i)==(6,2) else c['title']
    figure='약 5분 16초' if (n,i)==(6,2) else c['figure']
    im=D.body(title,figure,SCREEN[n][i],i,comparison=COMPARE.get((n,i)),note=note)
    BOUNDS.extend(D.BOUNDS); D.BOUNDS.clear()
    return im


def cover(e,root):
    im=ImageOps.fit(Image.open(root/e['cover_file']).convert('RGB'),(W,H))
    overlay=Image.new('RGBA',(W,H));od=ImageDraw.Draw(overlay)
    for y in range(H):
        a=20+int(224*max(0,min(1,(y-650)/900)))
        od.line((0,y,W,y),fill=(10,18,20,a))
    im=Image.alpha_composite(im.convert('RGBA'),overlay).convert('RGB');d=ImageDraw.Draw(im)
    d.rounded_rectangle((68,152,286,211),radius=29,fill=WHITE)
    txt(d,'돈값하나',97,156,180,32,INK,55,850)
    txt(d,f'{e["order"]:02d}',881,154,75,34,WHITE,55,600)
    d.line((68,985,145,985),fill=ORANGE,width=6)
    lines=e['hook'].split('\n')
    y=1040
    for j,line in enumerate(lines):
        y=txt(d,line,68,y,880,100,WHITE if j==0 else '#F5C39C',210,850,1.15)+12
    txt(d,'생활 속 선택을 숫자로.',68,1410,870,31,'#C2C9C5',65,500)
    txt(d,'AI 연출 이미지 · 계산 조건은 본문',68,1510,870,25,'#9DA8A1',55,400)
    return im

def conclusion(e):
    from src import editorial_design as D
    im=D.conclusion(e['verdict_text'])
    BOUNDS.extend(D.BOUNDS); D.BOUNDS.clear()
    return im


def cta(e,platform):
    from src import editorial_design as D
    im=D.cta(e['question'],platform)
    BOUNDS.extend(D.BOUNDS); D.BOUNDS.clear()
    return im


def render_frames(e,root):
    frames=[('01-cover',cover(e,root),e['narration'][0])]
    frames += [(f'{i+2:02d}-body',render_body(e,i),e['narration'][i+1]) for i in range(4)]
    frames += [('06-conclusion',conclusion(e),e['narration'][-1])]
    frames += [('07-instagram-cta',cta(e,'instagram'),e['cta']['instagram']['narration']),
               ('07-youtube-cta',cta(e,'youtube'),e['cta']['youtube']['narration'])]
    return frames
