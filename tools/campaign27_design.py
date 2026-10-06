"""Editorial v2: short screen copy, numeric hierarchy, comparison diagrams, branded CTA."""
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
    c=e['cards'][i]; n=e['order']; dark=True
    im,d=frame(e,dark); fg=WHITE if dark else INK; accent=LIME if dark else ORANGE
    txt(d,['조건부터','계산해보면','돈값의 기준','놓치면 안 되는 것'][i],68,285,850,29,accent,60,600)
    heading='하루 본전 시간' if (n,i)==(6,2) else c['title']
    txt(d,heading,68,365,875,80,fg,210,850)
    comparison=COMPARE.get((n,i))
    if comparison:
        la,lb,a,b,va,vb=comparison
        for j,(label,value,v) in enumerate([(la,a,va),(lb,b,vb)]):
            y=660+j*275
            txt(d,label,68,y,850,33,'#A8B6A8',60,500)
            txt(d,value,68,y+50,850,104,fg,135,850)
            d.rounded_rectangle((68,y+198,952,y+217),radius=9,fill='#34443E')
            d.rounded_rectangle((68,y+198,68+int(884*v/max(va,vb)),y+217),radius=9,fill=ORANGE if j==0 else LIME)
        txt(d,SCREEN[n][i],68,1270,880,45,fg,140,500)
    elif i==3 and n!=10:  # 10편 '음악·쇼츠'는 빠지는 항목이라 체크 표시를 쓰지 않는다
        # Advice is a compact, intentional checklist instead of a fake numeric card.
        words=re.split('[·＋+]',c['figure'])
        if len(words)>1:
            for j,word in enumerate(words[:3]):
                yy=675+j*150
                d.ellipse((68,yy+18,111,yy+61),outline=ORANGE,width=3)
                d.line((78,yy+39,87,yy+47,101,yy+29),fill=ORANGE,width=4)
                txt(d,word.strip(),140,yy,810,65,fg,110,750)
        else:
            txt(d,c['figure'],68,685,880,108,fg,290,850)
            d.line((68,1040,220,1040),fill=ORANGE,width=6)
        txt(d,SCREEN[n][i],68,1150,875,51,fg,240,500)
    else:
        # Oversized type replaces the old solid orange rectangle.
        figure='약 5분 16초' if (n,i)==(6,2) else c['figure']
        size=100 if (n,i)==(16,2) else (140 if (n,i)==(6,2) else 158)
        # 숫자가 한 글자('%', '차이')만 다음 줄로 떨어지지 않게, 한 줄에 들어갈 때까지 먼저 줄인다.
        while size>96 and d.textlength(figure,font=font(size,850))>884: size-=4
        txt(d,figure,64,675,888,size,accent,340,850,1.12)
        d.line((68,1110,950,1110),fill='#3C4742' if dark else '#D4D8CD',width=2)
        txt(d,SCREEN[n][i],68,1160,880,48,fg,245,500)
        if dark:
            # Small target mark connects the page to the question "돈값하나?".
            d.ellipse((827,295,942,410),outline='#435347',width=2)
            d.ellipse((853,321,916,384),outline='#6C7D5D',width=2)
            d.ellipse((878,346,891,359),fill=LIME)
    note='가정값 · 시간가치 ≠ 현금 수입' if n in [1,6,8,9,14,15,18] else '설명용 가정 포함 · 상세 조건/출처는 캡션'
    if n==10:note='유튜브 공식 요금(웹·안드로이드) 기준 · 출처는 캡션'
    if n==5:note='2026년 12월까지 · 정률 기준 / 이용 조건 확인'
    if n==23:note='지급률은 전체 평균 · 개인 당첨액 보장 아님'
    footer(d,i,dark,note)
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
    im,d=frame(e,True)
    txt(d,'그래서, 돈값하나?',68,320,870,37,LIME,70,600)
    key=e.get('key') or {}
    if key:  # 핵심 숫자 한 번 더(2026-09-29 소유자 요청: 결론 화면 보강)
        txt(d,key['label'],68,420,870,34,'#A8B6A8',60,500)
        txt(d,key['figure'],64,475,888,110,LIME,150,850,1.1)
        d.line((68,660,220,660),fill=ORANGE,width=6)
        txt(d,e['verdict_text'],68,715,880,86,WHITE,450,850,1.22)
    else:
        txt(d,e['verdict_text'],68,565,880,101,WHITE,520,850,1.22)
    d.line((68,1205,950,1205),fill='#455148',width=2)
    txt(d,'내 숫자로 바꾸면\n선택도 달라집니다.',68,1270,850,48,'#B6C1B7',190,500)
    txt(d,'@dongabhana',68,1510,850,28,'#8F9D93',55,500)
    return im

def heart(d,x,y,color):
    pts=[]
    for k in range(100):
        t=2*math.pi*k/99
        pts.append((x+1.8*16*math.sin(t)**3,y-1.8*(13*math.cos(t)-5*math.cos(2*t)-2*math.cos(3*t)-math.cos(4*t))))
    d.polygon(pts,fill=color)

def cta_cover(e,root):
    """2026-10-06 소유자 결정(A안): 유튜브 마지막 장면은 표지 위에 '좋아요 + 구독'만 얹는다.

    파트너(YPP)가 아닌 채널은 쇼츠 썸네일을 직접 정할 수 없고, 유튜브가 영상의
    시작·중간·끝 근처에서 뽑은 장면 중 하나를 쓴다. 시작(표지)과 끝을 표지로 맞추면
    3장 중 2장이 표지가 된다. 표지의 사진·훅 글자는 그대로 두고 아래 안내 문구 자리만 덮는다.
    """
    im=cover(e,root); d=ImageDraw.Draw(im)
    d.rectangle((0,1385,W,H),fill='#101A1C')
    d.rounded_rectangle((60,1405,1020,1620),radius=28,fill=ORANGE)
    txt(d,'좋아요 + 구독',100,1428,860,92,WHITE,120,900)
    txt(d,'다음 계산도, 돈값하나와.',100,1548,860,34,WHITE,48,600)
    q=e['question']; f=font(32,500)
    while d.textlength(q,font=f)>880 and f.size>24: f=font(f.size-2,500)
    d.text((96,1660),q,font=f,fill='#D5DBD2')
    return im

def cta(e,platform):
    im,d=frame(e,True)
    # Oversized editorial call to action, with a warm accent and a shared palette.
    txt(d,'쓸 땐 똑똑하게.',68,320,880,78,WHITE,120,850)
    txt(d,'돈값은 확실하게.',68,425,880,78,LIME,120,850)
    d.ellipse((748,593,950,795),fill=ORANGE)
    d.line((805,737,890,652),fill=DARK,width=10)
    d.line((825,652,890,652,890,718),fill=DARK,width=10)
    word='팔로우' if platform=='instagram' else '구독'
    txt(d,'좋아요 +',68,617,650,67,WHITE,115,700)
    txt(d,word,62,750,886,190,LIME,270,900)
    d.line((68,1035,952,1035),fill='#455148',width=2)
    txt(d,'다음 선택도, 돈값하나와.',68,1080,880,42,WHITE,85,600)
    txt(d,'당신의 선택은?',68,1240,880,29,'#A8B6A8',60,500)
    txt(d,e['question'],68,1300,880,46,WHITE,155,650)
    txt(d,'돈값하나  /  @dongabhana',68,1510,880,28,'#A8B6A8',55,500)
    return im


def render_frames(e,root):
    frames=[('01-cover',cover(e,root),e['narration'][0])]
    frames += [(f'{i+2:02d}-body',render_body(e,i),e['narration'][i+1]) for i in range(4)]
    frames += [('06-conclusion',conclusion(e),e['narration'][-1])]
    frames += [('07-instagram-cta',cta(e,'instagram'),e['cta']['instagram']['narration']),
               ('07-youtube-cta',cta_cover(e,root),e['cta']['youtube']['narration'])]
    return frames
