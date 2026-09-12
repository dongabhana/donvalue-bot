"""Fail closed when a referenced official price can no longer be confirmed."""
import re
import unicodedata
from html.parser import HTMLParser
from urllib.parse import urlparse
import requests

ALLOWED_HOSTS = {'support.apple.com', 'www.apple.com', 'www.microsoft.com', 'store.nintendo.co.kr', 'news.seoul.go.kr'}

class VisibleText(HTMLParser):
    def __init__(self):
        super().__init__(); self.parts=[]; self.hidden=0
    def handle_starttag(self,tag,attrs):
        if tag in ('script','style'): self.hidden+=1
    def handle_endtag(self,tag):
        if tag in ('script','style'): self.hidden=max(0,self.hidden-1)
    def handle_data(self,data):
        if not self.hidden: self.parts.append(data)

def normalized(value):
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC',value))

def matches_official_page(source,html):
    parser=VisibleText(); parser.feed(html); body=normalized(' '.join(parser.parts))
    start=normalized(source['scope_start']); end=normalized(source['scope_end'])
    # Menus may contain repeated headings: inspect bounded matching sections only.
    for match in re.finditer(re.escape(start),body):
        finish=body.find(end,match.end())
        if finish < 0: continue
        section=body[match.end():finish]
        if len(section)>30000: continue
        def contains(token):
            token=normalized(token)
            if re.fullmatch(r'[0-9,]+',token):
                return bool(re.search(r'(?<![0-9,])'+re.escape(token)+r'(?![0-9,])',section))
            return token in section
        if all(contains(token) for token in source['required_tokens']): return True
    return False

def check_prices(item,session=requests):
    if not item.get('verification',{}).get('real_world_price_claim'): return
    if item.get('editorial_revision') != 'official-comparison-2026-09-12': return
    for source in item['verification']['sources']:
        url=source['url']; parsed=urlparse(url)
        if parsed.scheme!='https' or parsed.hostname not in ALLOWED_HOSTS:
            raise RuntimeError('Unexpected official price source')
        try:
            response=session.get(url,timeout=25,headers={'User-Agent':'Mozilla/5.0 donvalue-price-check'},allow_redirects=False)
        except requests.RequestException:
            raise RuntimeError('Official price source temporarily unavailable') from None
        if response.status_code!=200 or not matches_official_page(source,response.text):
            raise RuntimeError('Official price unavailable or changed; revised content required')
