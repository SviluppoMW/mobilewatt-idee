#!/usr/bin/env python3
"""Le tre idee del giorno per i Reel, dalle notizie dello scraper (notizie.py).

Prende le notizie di oggi in ordine di punteggio, una per fonte, mai una già proposta in un giorno
precedente, e scrive:
    idee.json         le tre di oggi (la pagina del piano le mette in cima)
    idee-tutte.json   tutti i giorni, dal più recente (non si toglie mai niente)
    idee/<data>.json  la copia del giorno
"""
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

QUI = Path(__file__).resolve().parent
oggi = datetime.now(ZoneInfo("Europe/Rome")).date().isoformat()
notizie = json.loads((QUI / "notizie" / f"{oggi}.json").read_text())
tutte = json.loads((QUI / "idee-tutte.json").read_text()) if (QUI / "idee-tutte.json").exists() else []
tutte = [g for g in tutte if g["data"] != oggi]
gia = {i["link"] for g in tutte for i in g["idee"]}

scelte, fonti = [], set()
for n in notizie:
    if n["link"] in gia or n["fonte"] in fonti:
        continue
    sommario = n.get("sommario", "").strip()
    scelte.append({"titolo": n["titolo"], "fonte": n["fonte"], "link": n["link"], "uscita": n["data"][:10],
                   "sommario": sommario[:320] + ("…" if len(sommario) > 320 else "")})
    fonti.add(n["fonte"])
    if len(scelte) == 3:
        break

giorno = {"data": oggi, "idee": scelte}
(QUI / "idee.json").write_text(json.dumps(giorno, ensure_ascii=False, indent=1) + "\n")
(QUI / "idee" / f"{oggi}.json").write_text(json.dumps(giorno, ensure_ascii=False, indent=1) + "\n")
(QUI / "idee-tutte.json").write_text(json.dumps([giorno] + tutte, ensure_ascii=False, indent=1) + "\n")
for i in scelte:
    print(f"{i['fonte']:20}  {i['titolo']}")
print("ESITO: OK" if len(scelte) == 3 else f"ESITO: ATTENZIONE, solo {len(scelte)} idee")
