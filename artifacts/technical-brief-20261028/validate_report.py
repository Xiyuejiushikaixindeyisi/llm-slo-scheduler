
from html.parser import HTMLParser
from pathlib import Path
import json,hashlib,csv,re
root=Path(__file__).resolve().parents[2]
html=root/'docs/reports/LLM_SLO_SCHEDULER_TECHNICAL_BRIEF_20261028.html'
text=html.read_text()
class Audit(HTMLParser):
    def __init__(self):super().__init__();self.ids=[];self.links=[];self.assets=[];self.sections=0;self.svgs=0
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if 'id' in a:self.ids.append(a['id'])
        if tag=='a':self.links.append(a.get('href',''))
        if tag in ('script','img','link') and ('src' in a or 'href' in a):self.assets.append(a.get('src',a.get('href')))
        if tag=='section':self.sections+=1
        if tag=='svg':self.svgs+=1
a=Audit();a.feed(text)
assert len(a.ids)==len(set(a.ids)),'duplicate ids'
assert '\ufffd' not in text
for href in a.links:
    if href.startswith('#'):assert href[1:] in a.ids,href
    elif not href.startswith('https:'):assert (html.parent/href).resolve().exists(),href
assert not a.assets,a.assets
js=re.search(r'<script>(.*?)</script>',text,re.S).group(1)
(html.parent.parent.parent/'artifacts/technical-brief-20261028/report-script.js').write_text(js)
rows=list(csv.DictReader((root/'evidence/huawei/2026-10-28-g5-p-token-budget/perf_summary.original.csv').open()))
assert sum(int(r['n']) for r in rows)==285
results={'sections':a.sections,'embedded_svg':a.svgs,'links':len(a.links),'unique_ids':len(a.ids),'external_runtime_assets':len(a.assets),'sample_count':285,'html_bytes':html.stat().st_size,'html_sha256':hashlib.sha256(html.read_bytes()).hexdigest(),'checks':['unique ids','internal anchors','all local source links exist','no external runtime dependencies','UTF-8','CSV count and SHA checked by builder'],'notes':['Browser interaction/visual checks recorded separately.','No runtime source, deployment or benchmark changes.']}
(root/'artifacts/technical-brief-20261028/validation.json').write_text(json.dumps(results,indent=2,ensure_ascii=False))
print(json.dumps(results,ensure_ascii=False))
