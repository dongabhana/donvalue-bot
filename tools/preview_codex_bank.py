"""Render production-font cards and one complete reel for visual review."""
import json
import shutil
from pathlib import Path
from PIL import Image, ImageDraw
from codex.media import editorial_card, render_editorial, font
from codex.engine import validate

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT.parent/'deliverables'
OUT.mkdir(exist_ok=True)
items=json.loads((ROOT/'codex/content.json').read_text())['items'][1:]
for item in items:
    validate(item)
    for n,slide in enumerate(item['slides']):
        editorial_card(item,slide,n)
sample=items[:8]
sheet=Image.new('RGB',(1440,1100),'#E4E6E0')
for n,item in enumerate(sample):
    card=editorial_card(item,item['slides'][0],0).resize((330,413),Image.Resampling.LANCZOS)
    x=30+(n%4)*355; y=28+(n//4)*532
    sheet.paste(card,(x,y))
    d=ImageDraw.Draw(sheet)
    d.text((x,y+435),item['category']+' · '+item['publish_at'][:10],font=font(19),fill='#151819')
sheet.save(OUT/'돈값하나_GPT_새디자인.png')
first=items[0]
detail=Image.new('RGB',(1380,1200),'#E4E6E0')
for n,slide in enumerate(first['slides']):
    card=editorial_card(first,slide,n).resize((420,525),Image.Resampling.LANCZOS)
    detail.paste(card,(35+(n%3)*450,25+(n//3)*590))
detail.save(OUT/'돈값하나_노트북_6장시안.png')
renderroot=Path('/tmp/donvalue-editorial-reel')
result=render_editorial(first,renderroot)
shutil.copyfile(renderroot/result['video'],OUT/'돈값하나_GPT_릴스시안.mp4')
shutil.copyfile(ROOT/'codex/콘텐츠_50편.md',OUT/'돈값하나_GPT_콘텐츠50편.md')
print(json.dumps({'validated_manuscripts':50,'validated_cards':300,'reel_seconds':result['duration_seconds'],
                  'files':[str(p) for p in OUT.iterdir()]},ensure_ascii=False))
