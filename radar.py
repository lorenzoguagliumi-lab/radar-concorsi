#!/usr/bin/env python3
"""
Radar Concorsi — Gazzetta Ufficiale, 4a Serie Speciale "Concorsi ed esami".

Gira ogni mattina su GitHub Actions:
  1. legge le Gazzette degli ultimi 30 giorni
  2. estrae i bandi, li classifica e calcola la distanza da Bologna
  3. rigenera la pagina docs/index.html (GitHub Pages)
  4. se ci sono bandi nuovi in target scrive avviso.md: il workflow lo
     trasforma in una issue, e GitHub te la manda per email

Uso locale:
    python radar.py            # scarico reale
    python radar.py --demo     # dati finti, senza rete
    python radar.py --debug    # stampa cosa legge da ogni sommario
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import re
import sys
import time
import unicodedata
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup, NavigableString, Tag

# ---------------------------------------------------------------------------
# CONFIGURAZIONE — si modifica qui, il resto non va toccato
# ---------------------------------------------------------------------------

CONFIG = {
    "origine": {"nome": "Bologna", "lat": 44.4949, "lon": 11.3426},
    "giorni_finestra": 30,          # Gazzette da leggere
    "giorni_minimi": 0,             # scarta i bandi che scadono prima di N giorni

    # cosa entra nella pagina (i filtri fini li fai dalla pagina stessa)
    "inquadramenti_pagina": ["Dirigenza", "Funzionari", "Istruttori"],
    "aree_pagina": ["Amministrativa", "Economico-finanziaria", "Informatica/Dati", "Tecnica/Logistica"],

    # cosa fa scattare l'email
    "inquadramenti_avviso": ["Dirigenza", "Funzionari"],
    "raggio_avviso_km": 100,        # oltre questa distanza niente email (i bandi senza sede nota avvisano comunque)

    "pausa": 1.5,
    "timeout": 40,
    "user_agent": "Mozilla/5.0 (RadarConcorsi; uso personale, 1 lettura al giorno)",
}

BASE = "https://www.gazzettaufficiale.it"
URL_30GIORNI = BASE + "/30giorni/concorsi"
URL_SOMMARIO = BASE + "/gazzetta/concorsi/caricaDettaglio?dataPubblicazioneGazzetta={data}&numeroGazzetta={numero}"

CARTELLA = Path(__file__).resolve().parent
DOCS = CARTELLA / "docs"
STATO = CARTELLA / "stato" / "visti.json"

# ---------------------------------------------------------------------------
# Regole di classificazione (l'ordine conta: vince la prima che corrisponde)
# ---------------------------------------------------------------------------

REGOLE_INQUADRAMENTO = [
    ("Dirigenza",  r"\bdirigent|\bdirettore general|\bdirettore amministrativ|\bsegretario general"),
    ("Funzionari", r"\bfunzionari|elevata qualificazione|\be\.?q\.?\b|categoria d\b|istruttore direttivo|specialista\b|collaboratore amministrativo professionale|collaboratore tecnico professionale|\bv livello|quinto livello|\btecnologo"),
    ("Istruttori", r"\bistruttor|categoria c\b|\barea degli istruttori|\bassistent|\bcollaborator"),
    ("Operatori",  r"\boperator|categoria b\b|\bausiliar|\bcommess|\bautist"),
]

REGOLE_AREA = [
    ("Informatica/Dati",      r"informatic|sistemi informativ|servizi informativ|\bict\b|\bdati\b|digital|cyber|statistic|analisi dat|data scien|transizione digitale|sistemista"),
    ("Economico-finanziaria", r"contabil|ragioner|economic|finanziar|bilancio|tribut|controllo di gestione|fiscal|revisor"),
    ("Tecnica/Logistica",     r"\btecnic|ingegner|architett|geometra|lavori pubblici|manutenzion|patrimonio|logistic|acquist|provveditor|appalt|contratti pubblici|gare\b|urbanistic"),
    ("Sanitaria",             r"\bmedic|infermier|\boss\b|sanitari|farmacist|biolog|veterinar|psicolog|ostetric|fisioterap|radiolog"),
    ("Docenza/Ricerca",       r"ricercator|professor|docent|borsa di ricerca|assegno di ricerca|dottorat|incarico di ricerca"),
    ("Legale",                r"\blegal|avvocat|contenzios"),
    ("Sociale/Educativa",     r"assistente social|educator|insegnant|pedagog|servizi social"),
    ("Vigilanza",             r"polizia|vigil|agente"),
    ("Amministrativa",        r"amministrativ|gestional|segreteri|protocoll|personale\b|risorse umane|affari generali|servizi al cittadino|anagraf|giuridic"),
]

REGOLE_TIPO = [
    ("Mobilità",  r"mobilita"),
    ("Selezione", r"selezion|avviso|manifestazione di interesse|elenco (di )?idonei|conferimento"),
    ("Concorso",  r"concors"),
]

# atti che non sono bandi a cui candidarsi
ESCLUSIONI = (r"graduatori|diario|diari delle|calendario|nomina|commission|cancellazion|registro dei revisori|"
              r"rettifica|errata|annullament|revoca|sorteggio|esito|rinvio|convocazion|ammess|elenco degli ammessi|"
              r"riapertura dei termini di.*(graduatori)|avviso di sostituzione")

MESI = {"gennaio": 1, "febbraio": 2, "marzo": 3, "aprile": 4, "maggio": 5, "giugno": 6, "luglio": 7,
        "agosto": 8, "settembre": 9, "ottobre": 10, "novembre": 11, "dicembre": 12}

NUMERI_PAROLA = {"un": 1, "uno": 1, "una": 1, "due": 2, "tre": 3, "quattro": 4, "cinque": 5, "sei": 6,
                 "sette": 7, "otto": 8, "nove": 9, "dieci": 10, "undici": 11, "dodici": 12, "tredici": 13,
                 "quattordici": 14, "quindici": 15, "venti": 20, "trenta": 30, "cinquanta": 50, "cento": 100}

ETICHETTE = {"avviso", "concorso", "concorsi", "graduatoria", "graduatorie", "nomina", "nomine", "diario", "diari",
             "selezione", "selezioni", "mobilita", "esame", "esami", "rettifica", "proroga", "riapertura",
             "annullamento", "revoca", "sorteggio", "comunicato", "errata corrige", "pag", "sommario", "indice",
             "concorsi ed esami", "enti locali", "amministrazioni centrali", "enti pubblici statali",
             "universita e istituzioni", "altri enti", "aziende sanitarie locali ed altri enti sanitari",
             "enti di ricerca", "universita", "aziende sanitarie", "diari", "4a serie speciale"}

REGIONI = {"emilia-romagna": "bologna", "emilia romagna": "bologna", "toscana": "firenze", "lombardia": "milano",
           "veneto": "venezia", "piemonte": "torino", "liguria": "genova", "marche": "ancona", "umbria": "perugia",
           "lazio": "roma", "campania": "napoli", "puglia": "bari", "abruzzo": "l'aquila", "molise": "campobasso",
           "basilicata": "potenza", "calabria": "catanzaro", "sicilia": "palermo", "sardegna": "cagliari",
           "friuli venezia giulia": "trieste", "friuli-venezia giulia": "trieste", "trentino": "trento"}

# ---------------------------------------------------------------------------
# Utilità
# ---------------------------------------------------------------------------

def normalizza(testo: str) -> str:
    t = unicodedata.normalize("NFKD", testo or "")
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", t).strip().lower()


def distanza_km(lat1, lon1, lat2, lon2) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return r * 2 * math.asin(math.sqrt(a))


def titolo_ente(t: str) -> str:
    minuscole = {"di", "del", "della", "dei", "degli", "delle", "e", "ed", "per", "la", "il", "lo", "le", "in", "a", "da", "al"}
    parole = re.sub(r"\s+", " ", t).strip(" -–.").lower().split(" ")
    out = []
    def cap(x):
        return "-".join(y[:1].upper() + y[1:] for y in x.split("-"))
    for i, p in enumerate(parole):
        if "'" in p:
            testa, coda = p.split("'", 1)
            testa = testa if (i and testa in {"dell", "dall", "all", "nell", "sull", "d", "l"}) else cap(testa)
            out.append(f"{testa}'{cap(coda)}")
        elif i and p in minuscole:
            out.append(p)
        else:
            out.append(cap(p))
    return " ".join(out).replace(" Usl ", " USL ").replace("Ausl", "AUSL").replace("Asp ", "ASP ")


# --- comuni: ricerca per n-grammi, esatta e veloce -------------------------

COMUNI: dict[str, tuple[str, str, float, float]] = {}   # nome normalizzato -> (nome, sigla, lat, lon)
NOMI_AMBIGUI = set()   # nomi corti che sono anche parole comuni: valgono solo dopo una preposizione


URL_COMUNI = "https://raw.githubusercontent.com/matteocontrini/comuni-json/master/comuni.json"
URL_COORD = "https://raw.githubusercontent.com/MatteoHenryChinaski/Comuni-Italiani-2018-Sql-Json-excel/master/italy_geo.json"


def costruisci_comuni(f: Path) -> None:
    """Se manca comuni.csv lo crea dalle anagrafiche pubbliche (una volta sola)."""
    print("Creo comuni.csv dalle anagrafiche pubbliche…")
    geo = {}
    for r in requests.get(URL_COORD, timeout=60).json():
        try:
            geo[int(r["istat"])] = (float(r["lat"]), float(r["lng"]))
        except (KeyError, ValueError, TypeError):
            continue
    righe = []
    for c in requests.get(URL_COMUNI, timeout=60).json():
        k = int(c["codice"])
        if k in geo:
            righe.append((c["nome"], c["sigla"], f"{geo[k][0]:.5f}", f"{geo[k][1]:.5f}"))
    with f.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh, delimiter=";")
        w.writerow(["comune", "sigla", "lat", "lon"])
        w.writerows(sorted(righe))
    print(f"  {len(righe)} comuni")


def carica_comuni() -> None:
    f = CARTELLA / "comuni.csv"
    if not f.exists():
        costruisci_comuni(f)
    with f.open(encoding="utf-8-sig", newline="") as fh:
        for r in csv.DictReader(fh, delimiter=";"):
            try:
                COMUNI[normalizza(r["comune"])] = (r["comune"], r["sigla"].upper(), float(r["lat"]), float(r["lon"]))
            except (KeyError, ValueError):
                continue
    comuni_parole = {"sale", "ne", "lu", "este", "bella", "sori", "vita", "zone", "cento", "bra", "ala", "arco", "corte",
                     "piazza", "porto", "monte", "ponte", "valle", "villa", "rocca", "costa", "torre", "castello",
                     "sole", "mare", "bosco", "fiume", "lago", "campo", "fontana", "rio", "pace", "casa", "prato",
                     "scala", "musei", "mezzane", "pieve", "badia", "dolo", "fara", "caselle", "vigone", "moda", "lodi"}
    for nome in list(COMUNI):
        if nome in comuni_parole or len(nome) <= 3:
            NOMI_AMBIGUI.add(nome)
    NOMI_AMBIGUI.discard("lodi")  # capoluogo: di solito compare come "comune di lodi" ed è comunque valido


def trova_comune(testo: str) -> tuple[str, str, float, float] | None:
    t = normalizza(testo).replace("'", "' ")
    t = re.sub(r"[^a-z0-9' ]", " ", t)
    parole = t.split()
    migliore = None
    for n in range(6, 0, -1):
        for i in range(len(parole) - n + 1):
            cand = " ".join(parole[i:i + n]).replace("' ", "'")
            if cand in COMUNI:
                if cand in NOMI_AMBIGUI:
                    prima = parole[i - 1] if i else ""
                    if prima not in {"di", "del", "della", "a", "in", "comune", "sede"}:
                        continue
                migliore = COMUNI[cand]
                return migliore
    return migliore


def trova_sede(ente: str, oggetto: str) -> tuple[str, float, float, bool] | None:
    for fonte in (ente, oggetto):
        c = trova_comune(fonte)
        if c:
            return f"{c[0]} ({c[1]})", c[2], c[3], True
    t = normalizza(f"{ente} {oggetto}")
    for regione, capoluogo in REGIONI.items():
        if regione in t and capoluogo in COMUNI:
            c = COMUNI[capoluogo]
            return f"{c[0]} ({c[1]}), sede da verificare", c[2], c[3], False
    return None


# ---------------------------------------------------------------------------
# Rete
# ---------------------------------------------------------------------------

def sessione() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": CONFIG["user_agent"], "Accept-Language": "it-IT,it;q=0.9"})
    return s


def scarica(sess: requests.Session, url: str) -> str | None:
    for tentativo in range(3):
        try:
            r = sess.get(url, timeout=CONFIG["timeout"])
            r.raise_for_status()
            r.encoding = r.apparent_encoding or "utf-8"
            return r.text
        except requests.RequestException as e:
            print(f"  ! tentativo {tentativo + 1} fallito: {url}\n    {e}", file=sys.stderr)
            time.sleep(5 * (tentativo + 1))
    return None


# ---------------------------------------------------------------------------
# Estrazione
# ---------------------------------------------------------------------------

def trova_gazzette(html: str, giorni: int) -> list[tuple[str, str]]:
    limite = date.today() - timedelta(days=giorni)
    trovate: dict[str, str] = {}
    for d, n in re.findall(r"dataPubblicazioneGazzetta=(\d{4}-\d{2}-\d{2})[^\"'>]*?numeroGazzetta=(\d+)", html):
        trovate[n] = d
    for n, d in re.findall(r"numeroGazzetta=(\d+)[^\"'>]*?dataPubblicazioneGazzetta=(\d{4}-\d{2}-\d{2})", html):
        trovate.setdefault(n, d)
    uscite = [(n, d) for n, d in trovate.items() if datetime.strptime(d, "%Y-%m-%d").date() >= limite]
    return sorted(uscite, key=lambda x: x[1], reverse=True)


def _e_intestazione(t: str) -> bool:
    if len(t) > 130 or "scad" in t.lower():
        return False
    if normalizza(t).strip(" .:-") in ETICHETTE:
        return False
    lettere = [c for c in t if c.isalpha()]
    if len(lettere) < 6:
        return False
    return sum(1 for c in lettere if c.isupper()) / len(lettere) > 0.85


def estrai_atti(html: str, numero: str, data_iso: str) -> list[dict]:
    """Il sommario raggruppa gli atti sotto un'intestazione con il nome dell'ente:
    si scorre il documento nell'ordine tenendo traccia dell'ultima intestazione vista."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()
    atti, visti, ente_corrente = [], set(), ""
    data_gu = datetime.strptime(data_iso, "%Y-%m-%d").strftime("%d-%m-%Y")

    for nodo in soup.descendants:
        if isinstance(nodo, Tag):
            if nodo.name != "a":
                continue
            href = nodo.get("href") or ""
            if "caricaDettaglioAtto" not in href:
                continue
            m = re.search(r"codiceRedazionale=([\w\.]+)", href)
            if not m or m.group(1) in visti:
                continue
            visti.add(m.group(1))
            oggetto = re.sub(r"\s+", " ", nodo.get_text(" ", strip=True))
            riga = nodo.parent.get_text(" ", strip=True) if nodo.parent else oggetto
            atti.append({
                "codice": m.group(1),
                "ente_grezzo": ente_corrente,
                "oggetto": oggetto,
                "contesto": re.sub(r"\s+", " ", riga),
                "gu": f"n. {numero} del {data_gu}",
                "url_gu": href if href.startswith("http") else BASE + ("" if href.startswith("/") else "/") + href,
            })
        elif isinstance(nodo, NavigableString):
            t = str(nodo).strip()
            if t and not nodo.find_parent("a") and _e_intestazione(t):
                ente_corrente = t
    return atti


def estrai_scadenza(testo: str) -> date | None:
    m = re.search(r"scad\.?\s*:?\s*(\d{1,2})\s+([a-zà-ù]+)\s+(\d{4})", testo, re.IGNORECASE)
    if m and MESI.get(normalizza(m.group(2))):
        try:
            return date(int(m.group(3)), MESI[normalizza(m.group(2))], int(m.group(1)))
        except ValueError:
            return None
    m = re.search(r"scad\.?\s*:?\s*(\d{1,2})[/-](\d{1,2})[/-](\d{4})", testo, re.IGNORECASE)
    if m:
        try:
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except ValueError:
            return None
    return None


def estrai_posti(testo: str) -> int | None:
    t = normalizza(testo)
    m = re.search(r"\bn\.?\s*(\d{1,4})\s+(?:post|unita)", t) or re.search(r"\b(\d{1,4})\s+(?:post|unita)", t)
    if m:
        return int(m.group(1))
    m = re.search(r"\b([a-z]+)\s+(?:post|unita)", t)
    if m and m.group(1) in NUMERI_PAROLA:
        return NUMERI_PAROLA[m.group(1)]
    return None


def classifica(testo: str, regole, default=None):
    t = normalizza(testo)
    for etichetta, pattern in regole:
        if re.search(pattern, t):
            return etichetta
    return default


def elabora(atti: list[dict]) -> list[dict]:
    org, oggi, fuori = CONFIG["origine"], date.today(), []
    for a in atti:
        testo = f"{a['contesto']} {a['oggetto']}"
        if re.search(ESCLUSIONI, normalizza(a["oggetto"])) and not re.search(r"concorso pubblico|selezione pubblica", normalizza(a["oggetto"])):
            continue
        ente = titolo_ente(a["ente_grezzo"]) if a["ente_grezzo"] else "Ente non rilevato"
        scad = estrai_scadenza(testo)
        sede = trova_sede(ente, a["oggetto"])
        fuori.append({
            "cod": a["codice"],
            "e": ente,
            "t": a["oggetto"][:240],
            "tipo": classifica(testo, REGOLE_TIPO, "Concorso"),
            "i": classifica(testo, REGOLE_INQUADRAMENTO),
            "a": classifica(a["oggetto"], REGOLE_AREA) or classifica(testo, REGOLE_AREA),
            "n": estrai_posti(a["oggetto"]),
            "c": sede[0] if sede else None,
            "km": round(distanza_km(org["lat"], org["lon"], sede[1], sede[2])) if sede else None,
            "s": scad.isoformat() if scad else None,
            "gg": (scad - oggi).days if scad else None,
            "gu": a["gu"],
            "u": a["url_gu"],
        })
    return fuori


def filtra(bandi: list[dict]) -> tuple[list[dict], dict]:
    motivi = {"scaduti": 0, "inquadramento": 0, "area": 0}
    tenuti = []
    for b in bandi:
        if b["gg"] is not None and b["gg"] < CONFIG["giorni_minimi"]:
            motivi["scaduti"] += 1
        elif b["i"] not in CONFIG["inquadramenti_pagina"]:
            motivi["inquadramento"] += 1
        elif b["a"] not in CONFIG["aree_pagina"]:
            motivi["area"] += 1
        else:
            tenuti.append(b)
    return tenuti, motivi


# ---------------------------------------------------------------------------
# Uscite: pagina, stato, avviso
# ---------------------------------------------------------------------------

def scrivi_pagina(bandi: list[dict], letti: int, nota: str) -> None:
    DOCS.mkdir(exist_ok=True)
    ora = datetime.now(timezone.utc).astimezone()
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    html = (CARTELLA / "template.html").read_text(encoding="utf-8")
    html = (html.replace("__DATI__", json.dumps(bandi, ensure_ascii=False))
                .replace("__AGGIORNATO__", ora.isoformat())
                .replace("__LETTI__", str(letti))
                .replace("__REPO__", repo)
                .replace("__NOTA__", nota))
    (DOCS / "index.html").write_text(html, encoding="utf-8")
    (DOCS / "bandi.json").write_text(json.dumps(bandi, ensure_ascii=False, indent=1), encoding="utf-8")
    (DOCS / ".nojekyll").write_text("", encoding="utf-8")


def scrivi_avviso(bandi: list[dict]) -> int:
    STATO.parent.mkdir(exist_ok=True)
    primo_giro = not STATO.exists()
    visti = set(json.loads(STATO.read_text(encoding="utf-8"))) if not primo_giro else set()
    nuovi = [b for b in bandi if b["cod"] not in visti
             and b["i"] in CONFIG["inquadramenti_avviso"]
             and (b["km"] is None or b["km"] <= CONFIG["raggio_avviso_km"])]
    STATO.write_text(json.dumps(sorted(visti | {b["cod"] for b in bandi})), encoding="utf-8")

    avviso = CARTELLA / "avviso.md"
    if avviso.exists():
        avviso.unlink()
    if primo_giro or not nuovi:
        return 0

    owner = os.environ.get("GITHUB_REPOSITORY_OWNER", "")
    pagina = f"https://{owner.lower()}.github.io/{os.environ.get('GITHUB_REPOSITORY', '/').split('/')[1]}/" if owner else ""
    righe = [f"@{owner}" if owner else "", "", f"**{len(nuovi)} bandi nuovi in target** · [apri il radar]({pagina})", ""]
    for b in sorted(nuovi, key=lambda x: (x["km"] if x["km"] is not None else 9999)):
        scad = datetime.strptime(b["s"], "%Y-%m-%d").strftime("%d/%m") if b["s"] else "n.d."
        dove = f"{b['c']} · {b['km']} km" if b["km"] is not None else "sede da verificare"
        righe.append(f"- **{b['e']}** · {b['i']} · {b['a']} · scade {scad} · {dove}  \n  [{b['t'][:140]}]({b['u']})")
    avviso.write_text("\n".join(righe), encoding="utf-8")
    return len(nuovi)


# ---------------------------------------------------------------------------
# Demo e main
# ---------------------------------------------------------------------------

def fixture_demo() -> list[dict]:
    oggi = date.today()
    def s(gg):
        d = oggi + timedelta(days=gg)
        return f"{d.day} {[k for k, v in MESI.items() if v == d.month][0]} {d.year}"
    righe = [
        ("COMUNE DI BOLOGNA", f"CONCORSO (scad. {s(18)})", "26E90001", "Concorso pubblico, per esami, per la copertura di sei posti di funzionario amministrativo, area dei funzionari e dell'elevata qualificazione, a tempo indeterminato."),
        ("REGIONE EMILIA-ROMAGNA", f"CONCORSO (scad. {s(5)})", "26E90002", "Concorso pubblico per quattro posti di funzionario esperto in analisi dati e sistemi informativi."),
        ("AZIENDA UNITA' SANITARIA LOCALE DI IMOLA", f"CONCORSO (scad. {s(29)})", "26E90003", "Concorso pubblico per un posto di dirigente amministrativo, area acquisti e logistica."),
        ("COMUNE DI MODENA", f"CONCORSO (scad. {s(12)})", "26E90004", "Concorso pubblico per due posti di funzionario contabile, area economico-finanziaria."),
        ("COMUNE DI SALA BOLOGNESE", "GRADUATORIA", "26E90005", "Graduatoria di merito del concorso per istruttore amministrativo."),
        ("MINISTERO DELL'ECONOMIA E DELLE FINANZE", f"CONCORSO (scad. {s(26)})", "26E90006", "Concorso pubblico per venti posti di funzionario, area analisi economica e statistica."),
        ("AZIENDA OSPEDALIERA DI PADOVA", f"CONCORSO (scad. {s(20)})", "26E90007", "Concorso pubblico per un posto di dirigente medico, disciplina di cardiologia."),
    ]
    html = "<html><body>"
    ultimo = ""
    for ente, etichetta, cod, ogg in righe:
        if ente != ultimo:
            html += f"<h3>{ente}</h3>"
            ultimo = ente
        html += (f"<div><span>{etichetta}</span><a href=\"/atto/concorsi/caricaDettaglioAtto/originario?"
                 f"atto.dataPubblicazioneGazzetta={oggi.isoformat()}&amp;atto.codiceRedazionale={cod}\">{ogg}</a></div>")
    return estrai_atti(html + "</body></html>", "99", oggi.isoformat())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--demo", action="store_true")
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args()
    carica_comuni()

    if args.demo:
        atti = fixture_demo()
        print(f"Demo: {len(atti)} atti.")
    else:
        sess = sessione()
        print("Leggo l'elenco delle ultime Gazzette…")
        indice = scarica(sess, URL_30GIORNI)
        if not indice:
            print("ERRORE: la Gazzetta non risponde. Riprovo domani.", file=sys.stderr)
            return 1
        uscite = trova_gazzette(indice, CONFIG["giorni_finestra"])
        if not uscite:
            print("ERRORE: nessuna uscita trovata, forse è cambiata la pagina /30giorni/concorsi.", file=sys.stderr)
            return 2
        print(f"  {len(uscite)} uscite")
        atti = []
        for numero, data_iso in uscite:
            html = scarica(sess, URL_SOMMARIO.format(data=data_iso, numero=numero))
            if html:
                trovati = estrai_atti(html, numero, data_iso)
                atti.extend(trovati)
                print(f"  GU n. {numero} del {data_iso}: {len(trovati)} atti")
                if args.debug and trovati:
                    for t in trovati[:3]:
                        print(f"    [{t['ente_grezzo'][:40]}] {t['oggetto'][:90]}")
            time.sleep(CONFIG["pausa"])
        if not atti:
            print("ERRORE: sommari letti ma nessun atto estratto, forse è cambiato il sommario.", file=sys.stderr)
            return 3
        atti = list({a["codice"]: a for a in atti}.values())

    tutti = elabora(atti)
    bandi, motivi = filtra(tutti)
    bandi.sort(key=lambda b: (b["km"] if b["km"] is not None else 9999))
    print(f"{len(atti)} atti letti, {len(tutti)} bandi, {len(bandi)} in pagina. Scartati: {motivi}")
    if args.debug:
        for b in bandi[:15]:
            print(f"  {str(b['km']):>4} km | {b['i']:10} | {b['a']:22} | {b['e'][:35]} | {b['c']}")

    nota = f"{len(atti)} atti letti dalle Gazzette degli ultimi {CONFIG['giorni_finestra']} giorni."
    scrivi_pagina(bandi, len(atti), nota)
    if not args.demo:
        n = scrivi_avviso(bandi)
        print(f"Bandi nuovi da segnalare: {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
