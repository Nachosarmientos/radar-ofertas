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


GENERICOS = re.compile(r"^(inscr[ií]bete|ver (m[aá]s|oferta|detalle)|leer m[aá]s|m[aá]s info|apply|view|detalles?)\b", re.I)


def descarga(url):
    r = requests.get(url, headers=UA, timeout=40)
    r.raise_for_status()
    return BeautifulSoup(r.text, "html.parser")


def tarjeta(a, patron, max_len=450):
    """Bloque más amplio que contiene el enlace, sin otras ofertas y sin pasar de max_len caracteres."""
    propio = a.get("href")
    mejor, p = a, a
    for _ in range(6):
        p = p.parent
        if p is None or p.name in ("body", "html"):
            break
        otros = {x.get("href") for x in p.find_all("a", href=True) if patron.search(x["href"]) or
                 patron.search(requests.compat.urljoin("https://x.org/", x["href"]))}
        if len(otros - {propio}) > 0 or len(p.get_text(" ", strip=True)) > max_len:
            break
        mejor = p
    return mejor


FECHA = r"(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})"
PUBLICADA = re.compile(r"publicad[ao][^0-9]{0,15}" + FECHA, re.I)
CIERRE = re.compile(r"(?:hasta|plazo|cierre|l[ií]mite|deadline|closing)[^0-9]{0,25}" + FECHA, re.I)
CONVOCA = re.compile(r"(?:convoca|entidad|organizaci[oó]n)\s*:\s*([^|·\n]{3,80}?)(?:\s{2,}|$|\s+(?:publicad|abierta|plazo))", re.I)


def fecha_en(rx, texto):
    m = rx.search(texto)
    if not m:
        return None
    d, mes, a = map(int, m.groups())
    try:
        return datetime(a, mes, d, 23, 59, tzinfo=timezone.utc)
    except ValueError:
        return None


FECHA_COLA = re.compile(r"\s+\d{1,2} de [a-záéíóú]+,? \d{4}\s*$", re.I)


def lee_enlaces(f):
    """Lee todos los enlaces de una página cuyo destino cumple 'patron' (expresión regular)."""
    sopa = descarga(f["url"])
    patron = re.compile(f["patron"])
    evitar = re.compile(f["excluir_patron"]) if f.get("excluir_patron") else None
    descartar = [normaliza(t) for t in f.get("descartar_si_texto", [])]
    vistos = set()
    for a in sopa.find_all("a", href=True):
        url = requests.compat.urljoin(f["url"], a["href"].strip())
        if not patron.search(url) or (evitar and evitar.search(url)):
            continue
        if f.get("enlace_listado"):  # la oferta solo se abre desde el listado
            url = f["url"] + "#" + re.sub(r"[^a-z0-9]+", "-", normaliza(a.get_text(" ", strip=True)))[:80]
        if url in vistos:
            continue
        caja = tarjeta(a, patron)
        contexto = caja.get_text(" ", strip=True)
        titulo = a.get_text(" ", strip=True)
        if len(titulo) < 8 or GENERICOS.match(titulo):
            textos = [t for t in caja.stripped_strings if t != titulo and not GENERICOS.match(t)]
            titulo = max(textos, key=len) if textos else ""
            titulo = re.sub(r"^\d+_\d{4}_\d{1,2}_", "", titulo).replace("_", " ")
        titulo = FECHA_COLA.sub("", titulo)
        if len(titulo) < 8 or any(d in normaliza(contexto) for d in descartar):
            continue
        vistos.add(url)
        entidad = f.get("entidad", "")
        m = CONVOCA.search(contexto)
        if m:
            entidad = m.group(1).strip()
        yield oferta(f["nombre"], titulo, url, entidad=entidad, lugar=f.get("lugar", ""),
                     publicada=fecha_en(PUBLICADA, contexto), cierre=fecha_en(CIERRE, contexto),
                     resumen=contexto if contexto != titulo else "")


def lee_fiiapp(f):
    """Tabla de ofertas de FIIAPP: solo las que figuran como 'abierto'."""
    sopa = descarga(f["url"])
    for est in sopa.select("div.job-cell.estado"):
        if "abierto" not in est.get("class", []):
            continue
        celdas = {}
        prev = est
        for _ in range(4):
            prev = prev.find_previous_sibling("div", class_="job-cell")
            if prev is None:
                break
            for c in ("referencia", "descripcion", "periodo", "docs"):
                if c in prev.get("class", []):
                    celdas[c] = prev
        desc = celdas.get("descripcion")
        if not desc:
            continue
        for t in desc.select(".mobile-head, .el-adjudicatario, .notas-candidaturas"):
            t.decompose()
        fechas = re.findall(r"(\d{2})/(\d{2})/(\d{4})", celdas.get("periodo").get_text() if celdas.get("periodo") else "")
        iso_f = [datetime(int(y), int(m), int(d), 23, 59, tzinfo=timezone.utc) for d, m, y in fechas]
        pdf = celdas.get("docs").find("a", href=True) if celdas.get("docs") else None
        ref = celdas["referencia"].get_text(" ", strip=True) if "referencia" in celdas else ""
        yield oferta(f["nombre"], desc.get_text(" ", strip=True), pdf["href"] if pdf else f["url"] + "#" + ref,
                     entidad="FIIAPP", lugar=f.get("lugar", ""),
                     publicada=iso_f[0] if iso_f else None, cierre=iso_f[-1] if len(iso_f) > 1 else None,
                     resumen=ref)


LECTORES = {"rss": lee_rss, "reliefweb": lee_reliefweb, "web": lee_web,
            "enlaces": lee_enlaces, "fiiapp": lee_fiiapp}
# Tipos que muestran la lista completa: si una oferta deja de aparecer, se retira.
COMPLETOS = {"enlaces", "fiiapp", "web"}


# ---------- proceso ----------
def termino(t):
    """Palabra completa; con * al final admite variantes (proyect* → proyecto, proyectos)."""
    t = normaliza(t).strip()
    if t.endswith("*"):
        return re.compile(r"\b" + re.escape(t[:-1]))
    return re.compile(r"\b" + re.escape(t) + r"\b")


def pasa_filtro(o, cfg):
    texto = normaliza(" ".join([o["titulo"], o["resumen"], o["entidad"]]))
    claves = [termino(k) for k in cfg.get("palabras_clave", [])]
    fuera = [termino(k) for k in cfg.get("excluir", [])]
    if claves and not any(k.search(texto) for k in claves):
        return False
    return not any(k.search(texto) for k in fuera)


def main():
    cfg = yaml.safe_load((RAIZ / "config.yaml").read_text(encoding="utf-8"))
    previas = json.loads(DATOS.read_text(encoding="utf-8")) if DATOS.exists() else {}
    estado = []

    if "--solo-html" not in sys.argv:
        for f in cfg.get("fuentes", []):
            if not f.get("activa"):
                continue
            try:
                n, crudas, ids = 0, 0, set()
                for o in LECTORES[f["tipo"]](f):
                    crudas += 1
                    if not o["url"] or not pasa_filtro(o, cfg):
                        continue
                    o["vista"] = previas.get(o["id"], {}).get("vista") or AHORA.isoformat()
                    previas[o["id"]] = o
                    ids.add(o["id"])
                    n += 1
                if f["tipo"] in COMPLETOS and crudas:  # retirar lo que ya no está publicado
                    for k in [k for k, o in previas.items() if o["fuente"] == f["nombre"] and k not in ids]:
                        del previas[k]
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
