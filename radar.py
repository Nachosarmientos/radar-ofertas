"""Radar de Ofertas: lee config.yaml, recoge ofertas y genera docs/index.html.

Uso:  python radar.py            (busca y regenera)
      python radar.py --solo-html (regenera la página sin buscar)
"""
import hashlib
import html
import json
import re
import sys
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path

import feedparser
import requests
import yaml
from bs4 import BeautifulSoup

RAIZ = Path(__file__).parent
DATOS = RAIZ / "data" / "ofertas.json"
SALIDA = RAIZ / "docs" / "index.html"
PLANTILLA = RAIZ / "plantilla.html"
AHORA = datetime.now(timezone.utc)
UA = {"User-Agent": "Mozilla/5.0 (RadarDeOfertas; +https://github.com)"}


# ---------- utilidades ----------
def normaliza(txt: str) -> str:
    txt = unicodedata.normalize("NFKD", txt or "").encode("ascii", "ignore").decode().lower()
    txt = re.sub(r"(/|\()(a|as|es|os|o)\b\)?", "", txt)   # técnico/a, coordinador(a)
    return re.sub(r"\s+", " ", txt)


def limpia(txt: str, n: int = 400) -> str:
    txt = BeautifulSoup(txt or "", "html.parser").get_text(" ")
    txt = re.sub(r"\s+", " ", txt).strip()
    return txt[:n] + ("…" if len(txt) > n else "")


def iso(d) -> str | None:
    if not d:
        return None
    if isinstance(d, str):
        try:
            d = datetime.fromisoformat(d.replace("Z", "+00:00"))
        except ValueError:
            return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc).isoformat()


def oferta(fuente, titulo, url, entidad="", lugar="", publicada=None, cierre=None, resumen=""):
    return {
        "id": hashlib.sha1((url or titulo).encode()).hexdigest()[:12],
        "fuente": fuente,
        "titulo": limpia(titulo, 200),
        "url": url,
        "entidad": limpia(entidad, 120),
        "lugar": limpia(lugar, 120),
        "publicada": iso(publicada),
        "cierre": iso(cierre),
        "resumen": limpia(resumen),
    }


# ---------- fuentes ----------
def lee_rss(f):
    feed = feedparser.parse(f["url"], agent=UA["User-Agent"])
    for e in feed.entries:
        fecha = e.get("published_parsed") or e.get("updated_parsed")
        fecha = datetime(*fecha[:6], tzinfo=timezone.utc) if fecha else None
        autor = e.get("author", "") or (e.get("source") or {}).get("title", "")
        yield oferta(f["nombre"], e.get("title", ""), e.get("link", ""),
                     entidad=autor, publicada=fecha,
                     resumen=e.get("summary", ""))


def lee_reliefweb(f):
    cuerpo = {
        "limit": int(f.get("limite", 100)),
        "sort": ["date.created:desc"],
        "fields": {"include": ["title", "url_alias", "source.name", "country.name",
                               "city.name", "date.created", "date.closing", "body"]},
    }
    if f.get("paises"):
        cuerpo["filter"] = {"field": "country.name", "value": f["paises"], "operator": "OR"}
    r = requests.post("https://api.reliefweb.int/v2/jobs",
                      params={"appname": f["appname"]}, json=cuerpo, headers=UA, timeout=40)
    r.raise_for_status()
    for item in r.json().get("data", []):
        c = item["fields"]
        lugar = ", ".join([x["name"] for x in c.get("city", [])] +
                          [x["name"] for x in c.get("country", [])])
        yield oferta(f["nombre"], c.get("title", ""), c.get("url_alias", ""),
                     entidad=", ".join(s["name"] for s in c.get("source", [])),
                     lugar=lugar,
                     publicada=c.get("date", {}).get("created"),
                     cierre=c.get("date", {}).get("closing"),
                     resumen=c.get("body", ""))


def lee_web(f):
    r = requests.get(f["url"], headers=UA, timeout=40)
    r.raise_for_status()
    sopa = BeautifulSoup(r.text, "html.parser")

    def txt(bloque, sel):
        if not sel:
            return ""
        el = bloque.select_one(sel)
        return el.get_text(" ", strip=True) if el else ""

    for b in sopa.select(f["selector_oferta"]):
        a = b.select_one(f.get("selector_enlace", "a"))
        if not a or not a.get("href"):
            continue
        yield oferta(f["nombre"], txt(b, f.get("selector_titulo")) or a.get_text(" ", strip=True),
                     requests.compat.urljoin(f["url"], a["href"]),
                     entidad=txt(b, f.get("selector_entidad")),
                     lugar=txt(b, f.get("selector_lugar")),
                     publicada=AHORA)


LECTORES = {"rss": lee_rss, "reliefweb": lee_reliefweb, "web": lee_web}


# ---------- proceso ----------
def pasa_filtro(o, cfg):
    texto = normaliza(" ".join([o["titulo"], o["resumen"], o["entidad"]]))
    claves = [normaliza(k) for k in cfg.get("palabras_clave", [])]
    fuera = [normaliza(k) for k in cfg.get("excluir", [])]
    if claves and not any(k in texto for k in claves):
        return False
    return not any(k in texto for k in fuera)


def main():
    cfg = yaml.safe_load((RAIZ / "config.yaml").read_text(encoding="utf-8"))
    previas = json.loads(DATOS.read_text(encoding="utf-8")) if DATOS.exists() else {}
    estado = []

    if "--solo-html" not in sys.argv:
        for f in cfg.get("fuentes", []):
            if not f.get("activa"):
                continue
            try:
                n = 0
                for o in LECTORES[f["tipo"]](f):
                    if not o["url"] or not pasa_filtro(o, cfg):
                        continue
                    o["vista"] = previas.get(o["id"], {}).get("vista") or AHORA.isoformat()
                    previas[o["id"]] = o
                    n += 1
                estado.append({"fuente": f["nombre"], "ok": True, "n": n})
                print(f"✓ {f['nombre']}: {n} ofertas")
            except Exception as e:  # una fuente caída no rompe el resto
                estado.append({"fuente": f["nombre"], "ok": False, "error": str(e)[:160]})
                print(f"✗ {f['nombre']}: {e}")

    # caducar: fuera lo viejo y lo ya cerrado
    limite = AHORA - timedelta(days=int(cfg.get("dias_maximos", 45)))
    vigentes = {}
    for k, o in previas.items():
        ref = o.get("publicada") or o.get("vista")
        if ref and datetime.fromisoformat(ref) < limite:
            continue
        if o.get("cierre") and datetime.fromisoformat(o["cierre"]) < AHORA - timedelta(days=1):
            continue
        vigentes[k] = o

    DATOS.parent.mkdir(exist_ok=True)
    DATOS.write_text(json.dumps(vigentes, ensure_ascii=False, indent=1), encoding="utf-8")
    f_estado = DATOS.parent / "estado.json"
    if estado:
        f_estado.write_text(json.dumps(estado, ensure_ascii=False), encoding="utf-8")
    elif f_estado.exists():
        estado = json.loads(f_estado.read_text(encoding="utf-8"))

    datos = {
        "titulo": cfg.get("titulo", "Radar de Ofertas"),
        "subtitulo": cfg.get("subtitulo", ""),
        "idioma": cfg.get("idioma", "es"),
        "actualizado": AHORA.isoformat(),
        "estado": estado,
        "ofertas": sorted(vigentes.values(), key=lambda o: o.get("publicada") or o["vista"], reverse=True),
    }
    pagina = PLANTILLA.read_text(encoding="utf-8")
    pagina = pagina.replace("{{TITULO}}", html.escape(datos["titulo"]))
    pagina = pagina.replace("{{COLOR}}", re.sub(r"[^#0-9a-fA-F]", "", cfg.get("color", "#0075C3")))
    pagina = pagina.replace("{{IDIOMA}}", datos["idioma"])
    pagina = pagina.replace("/*{{DATOS}}*/null", json.dumps(datos, ensure_ascii=False).replace("</", "<\\/"))
    SALIDA.parent.mkdir(exist_ok=True)
    SALIDA.write_text(pagina, encoding="utf-8")
    print(f"→ {len(vigentes)} ofertas vigentes · {SALIDA}")


if __name__ == "__main__":
    main()
