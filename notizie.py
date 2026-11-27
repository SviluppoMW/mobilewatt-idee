#!/usr/bin/env python3
"""Lo scraper delle notizie della settimana per la pagina LinkedIn di Mobile Watt.

Legge i feed RSS delle fonti di settore (Italia e mondo), tiene gli articoli degli ultimi N giorni, dà un
punteggio a ognuno (parole chiave dell'energia, numeri grossi, fonte primaria, Italia) e scrive:

    notizie/<data>.json   tutte le notizie trovate, ordinate per punteggio
    notizie/<data>.md     le prime 25, da leggere per scegliere quelle da pubblicare

    python3 tools/notizie.py                # ultimi 7 giorni
    python3 tools/notizie.py --giorni 3
    python3 tools/notizie.py --fonti        # prova solo quali feed rispondono

Solo libreria standard. Non pubblica niente: il post si scrive dopo, verificando la notizia sulla fonte.
"""
import argparse
import email.utils
import html
import json
import re
import ssl
import sys
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path

QUI = Path(__file__).resolve().parent
USCITA = QUI / "notizie"

# (nome, indirizzo del feed, peso della fonte, è italiana). Per aggiungerne una si prova prima che risponda.
FONTI = [
    ("Terna", "https://www.terna.it/it/media/comunicati-stampa/rss", 3, True),
    ("QualEnergia", "https://www.qualenergia.it/feed/", 2, True),
    ("pv magazine Italia", "https://www.pv-magazine.it/feed/", 2, True),
    ("Rinnovabili.it", "https://www.rinnovabili.it/feed/", 1, True),
    ("Staffetta Quotidiana", "https://www.staffettaquotidiana.it/rss", 2, True),
    ("Energy-Storage.news", "https://www.energy-storage.news/feed/", 3, False),
    ("pv magazine", "https://www.pv-magazine.com/feed/", 2, False),
    ("Canary Media", "https://www.canarymedia.com/rss.rss", 2, False),
    ("Utility Dive", "https://www.utilitydive.com/feeds/news/", 2, False),
    ("Electrek", "https://electrek.co/feed/", 1, False),
    ("CleanTechnica", "https://cleantechnica.com/feed/", 1, False),
    ("offshoreWIND.biz", "https://www.offshorewind.biz/feed/", 1, False),
    ("Renewable Energy World", "https://www.renewableenergyworld.com/feed/", 1, False),
    # aggiunte il 27/11/2026, provate una per una
    ("ESS News", "https://www.ess-news.com/feed/", 3, False),
    ("electrive", "https://www.electrive.com/feed/", 2, False),
    ("CnEVPost", "https://cnevpost.com/feed/", 2, False),
    ("CarNewsChina", "https://carnewschina.com/feed/", 1, False),
    ("InsideEVs", "https://insideevs.com/rss/news/all/", 1, False),
    ("Clean Energy Wire", "https://www.cleanenergywire.org/rss.xml", 2, False),
    ("Carbon Brief", "https://www.carbonbrief.org/feed/", 2, False),
    ("World Nuclear News", "https://www.world-nuclear-news.org/rss", 2, False),
    ("DatacenterDynamics", "https://www.datacenterdynamics.com/en/rss/", 1, False),
    ("TechCrunch Climate", "https://techcrunch.com/category/climate/feed/", 1, False),
    ("Solar Power World", "https://www.solarpowerworldonline.com/feed/", 1, False),
    ("edie", "https://www.edie.net/feed/", 1, False),
    ("Vaielettrico", "https://www.vaielettrico.it/feed/", 1, True),
    ("Il Sole 24 Ore economia", "https://www.ilsole24ore.com/rss/economia.xml", 1, True),
]

# parole che fanno una notizia da pagina sull'energia, col loro peso
PAROLE = {
    3: ["accumulo", "accumuli", "storage", "bess", "batteri", "battery", "batteries", "macse", "rete elettrica",
        "grid", "blackout", "sodio", "sodium", "solid-state", "stato solido", "terna", "arera", "capacity market",
        "mercato della capacità", "interconnes", "interconnector", "nuclear", "nucleare", "fusion", "fusione"],
    2: ["gigawatt", "gwh", "gw ", "megawatt", "mwh", "record", "asta", "auction", "data center", "datacenter",
        "idrogeno", "hydrogen", "pompaggio", "pumped hydro", "trasmissione", "transmission", "elettrodotto",
        "prezzo", "price", "cina", "china", "europa", "eu ", "commissione", "regolamento"],
    1: ["solare", "solar", "fotovoltaic", "eolic", "wind", "rinnovabil", "renewable", "ricarica", "charging",
        "veicoli elettrici", "ev ", "electric vehicle", "litio", "lithium"],
}
NUMERO_GROSSO = re.compile(r"\b\d+([.,]\d+)?\s?(gw|gwh|twh|mw|mwh|miliardi|billion|milioni|million)\b", re.I)
SCARTA = re.compile(r"webinar|sponsored|podcast|newsletter|job|evento sponsor|offerta di lavoro", re.I)


def leggi(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Macintosh) lettore-rss"})
    ctx = ssl.create_default_context()
    try:
        import certifi  # noqa: F401
        ctx = ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        if Path("/etc/ssl/cert.pem").exists():
            ctx = ssl.create_default_context(cafile="/etc/ssl/cert.pem")
    with urllib.request.urlopen(req, timeout=20, context=ctx) as r:
        return r.read()


def testo(el, *nomi):
    for n in nomi:
        x = el.find(n)
        if x is not None and (x.text or "").strip():
            return x.text.strip()
        for figlio in el:
            if figlio.tag.split("}")[-1] == n and (figlio.text or "").strip():
                return figlio.text.strip()
    return ""


def data(s):
    if not s:
        return None
    try:
        d = email.utils.parsedate_to_datetime(s)
    except (TypeError, ValueError):
        try:
            d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def pulisci(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


def voci_a_mano(xml):
    """Per i feed scritti male (Terna, Staffetta): si leggono i blocchi <item> con le espressioni regolari."""
    t = xml.decode("utf-8", "replace")
    for blocco in re.findall(r"<item\b.*?</item>", t, re.S):
        def campo(n):
            m = re.search(rf"<{n}[^>]*>(.*?)</{n}>", blocco, re.S)
            return re.sub(r"<!\[CDATA\[(.*?)\]\]>", r"\1", m.group(1), flags=re.S).strip() if m else ""
        yield {"titolo": pulisci(campo("title")), "link": pulisci(campo("link")),
               "data": data(campo("pubDate") or campo("dc:date")), "sommario": pulisci(campo("description"))[:400]}


def voci(xml):
    try:
        radice = ET.fromstring(xml)
    except ET.ParseError:
        yield from voci_a_mano(xml)
        return
    for el in radice.iter():
        tag = el.tag.split("}")[-1]
        if tag not in ("item", "entry"):
            continue
        link = testo(el, "link")
        if not link:
            for figlio in el:
                if figlio.tag.split("}")[-1] == "link" and figlio.get("href"):
                    link = figlio.get("href")
                    break
        yield {
            "titolo": pulisci(testo(el, "title")),
            "link": link,
            "data": data(testo(el, "pubDate", "published", "updated", "date")),
            "sommario": pulisci(testo(el, "description", "summary", "content"))[:400],
        }


def punteggio(v, peso_fonte, italia):
    t = f"{v['titolo']} {v['sommario']}".lower()
    p = peso_fonte
    for peso, parole in PAROLE.items():
        p += peso * sum(1 for w in parole if w in t)
    if NUMERO_GROSSO.search(t):
        p += 3
    if italia:
        p += 2
    return p


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--giorni", type=int, default=7)
    ap.add_argument("--fonti", action="store_true", help="prova solo quali feed rispondono")
    a = ap.parse_args()

    dal = datetime.now(timezone.utc) - timedelta(days=a.giorni)
    trovate, viste, stato = [], set(), []
    for nome, url, peso, italia in FONTI:
        try:
            tutte = list(voci(leggi(url)))
        except Exception as e:  # una fonte che non risponde non ferma le altre
            stato.append(f"✗ {nome}: {type(e).__name__} {str(e)[:60]}")
            continue
        recenti = [v for v in tutte if v["data"] and v["data"] >= dal]
        stato.append(f"✓ {nome}: {len(tutte)} voci, {len(recenti)} negli ultimi {a.giorni} giorni")
        for v in recenti:
            chiave = re.sub(r"\W+", "", v["titolo"].lower())[:60]
            if not v["titolo"] or chiave in viste or SCARTA.search(v["titolo"]):
                continue
            viste.add(chiave)
            v.update(fonte=nome, italia=italia, punti=punteggio(v, peso, italia), data=v["data"].isoformat())
            trovate.append(v)

    print("\n".join(stato))
    if a.fonti:
        return
    trovate.sort(key=lambda v: (-v["punti"], v["data"]), reverse=False)
    USCITA.mkdir(exist_ok=True)
    oggi = datetime.now().strftime("%Y-%m-%d")
    (USCITA / f"{oggi}.json").write_text(json.dumps(trovate, ensure_ascii=False, indent=1))
    righe = [f"# Notizie dell'energia, ultimi {a.giorni} giorni (raccolte il {oggi})", "",
             f"{len(trovate)} notizie da {sum(1 for s in stato if s.startswith('✓'))} fonti. Le prime 25 per punteggio.", ""]
    for i, v in enumerate(trovate[:25], 1):
        righe += [f"{i}. **{v['titolo']}** ({v['fonte']}, {v['data'][:10]}, {v['punti']} punti)",
                  f"   {v['sommario'][:220]}", f"   {v['link']}", ""]
    (USCITA / f"{oggi}.md").write_text("\n".join(righe))
    print(f"\n{len(trovate)} notizie, scritto notizie/{oggi}.md")
    for v in trovate[:12]:
        print(f"{v['punti']:3d}  {v['data'][:10]}  {v['fonte'][:18]:18}  {v['titolo'][:95]}")


if __name__ == "__main__":
    sys.exit(main())
