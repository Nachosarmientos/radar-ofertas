import json, re, sys, pathlib, requests
from bs4 import BeautifulSoup
H={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36","Accept-Language":"es-ES,es;q=0.9"}
out=pathlib.Path("diag/html"); out.mkdir(parents=True,exist_ok=True); rep=[]
for line in open("diag/urls.txt"):
    if not line.strip(): continue
    k,u=line.split(None,1); u=u.strip(); r={"k":k,"url":u}
    try:
        x=requests.get(u,headers=H,timeout=40); r.update(status=x.status_code,final=x.url,bytes=len(x.content),ctype=x.headers.get("content-type",""))
        out.joinpath(k+".html").write_bytes(x.content[:3_000_000])
        s=BeautifulSoup(x.text,"html.parser"); r["title"]=(s.title.get_text(strip=True) if s.title else "")[:100]
        r["feeds"]=[l.get("href") for l in s.find_all("link",type=re.compile("rss|atom"))][:5]
        r["n_a"]=len(s.find_all("a")); r["items"]=len(s.find_all(["item","entry"]))
    except Exception as e: r["error"]=str(e)[:200]
    rep.append(r); print(json.dumps(r,ensure_ascii=False))
json.dump(rep,open("diag/report.json","w"),ensure_ascii=False,indent=1)
