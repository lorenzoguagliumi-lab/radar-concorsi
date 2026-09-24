#!/usr/bin/env python3
"""
Radar Concorsi — Gazzetta Ufficiale 4a Serie Speciale "Concorsi ed esami".

Scarica i sommari delle ultime Gazzette, estrae i bandi, li classifica per
inquadramento e area professionale, calcola la distanza dalla citta' di
riferimento e rigenera una dashboard HTML autonoma.

Uso:
    python3 radar_concorsi.py                 # scarico reale, ultimi 30 giorni
    python3 radar_concorsi.py --giorni 14
    python3 radar_concorsi.py --tutti         # niente filtri, solo classificazione
    python3 radar_concorsi.py --demo          # dati finti, per provare la dashboard
    python3 radar_concorsi.py --debug         # stampa cosa trova pagina per pagina

Dipendenze: requests, beautifulsoup4  (pip install requests beautifulsoup4)
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
import time
import unicodedata
from datetime import date, datetime, timedelta
from pathlib import Path

import requests
from bs4 import BeautifulSoup, NavigableString, Tag

# ---------------------------------------------------------------------------
# CONFIGURAZIONE — modifica qui, non serve toccare il resto
# ---------------------------------------------------------------------------

CONFIG = {
    # punto di riferimento per la prossimita'
    "origine": {"nome": "Bologna", "sigla": "BO", "lat": 44.4949, "lon": 11.3426},

    # raggio massimo considerato (km). Oltre, il bando viene scartato
    # a meno di --tutti. E' anche il fondo scala del filtro nella dashboard.
    "raggio_km": 300,

    # inquadramenti che ti interessano. Vuoto = tutti.
    "inquadramenti_target": ["Dirigenza", "Funzionari/EQ", "Istruttori"],

    # aree professionali che ti interessano. Vuoto = tutte.
    "aree_target": ["Amministrativa", "Economico-finanziaria", "Informatica/Dati", "Tecnica"],

    # scarta i bandi gia' scaduti o con meno giorni di questi
    "giorni_minimi": 3,

    # pesi del punteggio di affinita' (somma libera, viene normalizzata a 1-5)
    "pesi": {
        "inquadramento": 40,   # inquadramento in target
        "area": 30,            # area in target
        "vicinanza": 25,       # decresce linearmente con la distanza
        "tempo": 5,            # premia chi ha ancora margine per candidarsi
    },

    # file prodotti
    "output_html": "radar_concorsi.html",
    "output_json": "concorsi.json",

    # cortesia verso il server: pausa fra una richiesta e l'altra (secondi)
    "pausa": 1.0,
    "timeout": 30,
    "user_agent": "RadarConcorsi/1.0 (uso personale; monitoraggio bandi GU)",
}

BASE = "https://www.gazzettaufficiale.it"
URL_30GIORNI = BASE + "/30giorni/concorsi"
URL_SOMMARIO = BASE + "/gazzetta/concorsi/caricaDettaglio?dataPubblicazioneGazzetta={data}&numeroGazzetta={numero}"
URL_INPA_RICERCA = "https://portale.inpa.gov.it/ui/public/concorsi?keyword={q}"

# ---------------------------------------------------------------------------
# Anagrafica geografica minima (capoluoghi). Per una copertura completa dei
# comuni, scarica l'elenco ISTAT in CSV e salvalo come "comuni.csv" accanto
# allo script, con colonne: comune;sigla;lat;lon  — viene caricato in automatico.
# ---------------------------------------------------------------------------

COMUNI = {
    "bologna": ("BO", 44.4949, 11.3426), "imola": ("BO", 44.3531, 11.7141),
    "modena": ("MO", 44.6471, 10.9252), "carpi": ("MO", 44.7828, 10.8858),
    "reggio emilia": ("RE", 44.6980, 10.6307), "parma": ("PR", 44.8015, 10.3279),
    "piacenza": ("PC", 45.0526, 9.6929), "ferrara": ("FE", 44.8381, 11.6198),
    "ravenna": ("RA", 44.4184, 12.2035), "faenza": ("RA", 44.2856, 11.8833),
    "forli": ("FC", 44.2227, 12.0407), "cesena": ("FC", 44.1391, 12.2431),
    "rimini": ("RN", 44.0678, 12.5695), "riccione": ("RN", 43.9990, 12.6555),
    "firenze": ("FI", 43.7696, 11.2558), "prato": ("PO", 43.8777, 11.1023),
    "pistoia": ("PT", 43.9330, 10.9179), "lucca": ("LU", 43.8430, 10.5079),
    "pisa": ("PI", 43.7160, 10.3966), "livorno": ("LI", 43.5485, 10.3106),
    "arezzo": ("AR", 43.4633, 11.8796), "siena": ("SI", 43.3188, 11.3308),
    "grosseto": ("GR", 42.7635, 11.1128), "massa": ("MS", 44.0362, 10.1414),
    "carrara": ("MS", 44.0793, 10.0977), "empoli": ("FI", 43.7186, 10.9470),
    "milano": ("MI", 45.4642, 9.1900), "monza": ("MB", 45.5845, 9.2744),
    "bergamo": ("BG", 45.6983, 9.6773), "brescia": ("BS", 45.5416, 10.2118),
    "como": ("CO", 45.8081, 9.0852), "varese": ("VA", 45.8206, 8.8251),
    "pavia": ("PV", 45.1847, 9.1582), "cremona": ("CR", 45.1332, 10.0227),
    "mantova": ("MN", 45.1564, 10.7914), "lodi": ("LO", 45.3142, 9.5034),
    "lecco": ("LC", 45.8566, 9.3977), "sondrio": ("SO", 46.1699, 9.8785),
    "torino": ("TO", 45.0703, 7.6869), "novara": ("NO", 45.4469, 8.6216),
    "alessandria": ("AL", 44.9133, 8.6151), "asti": ("AT", 44.9009, 8.2064),
    "cuneo": ("CN", 44.3841, 7.5426), "vercelli": ("VC", 45.3206, 8.4231),
    "biella": ("BI", 45.5664, 8.0533), "verbania": ("VB", 45.9211, 8.5518),
    "genova": ("GE", 44.4056, 8.9463), "savona": ("SV", 44.3091, 8.4772),
    "la spezia": ("SP", 44.1025, 9.8241), "imperia": ("IM", 43.8858, 8.0276),
    "venezia": ("VE", 45.4408, 12.3155), "padova": ("PD", 45.4064, 11.8768),
    "verona": ("VR", 45.4384, 10.9916), "vicenza": ("VI", 45.5455, 11.5354),
    "treviso": ("TV", 45.6669, 12.2430), "rovigo": ("RO", 45.0705, 11.7902),
    "belluno": ("BL", 46.1400, 12.2170), "trento": ("TN", 46.0748, 11.1217),
    "bolzano": ("BZ", 46.4983, 11.3548), "trieste": ("TS", 45.6495, 13.7768),
    "udine": ("UD", 46.0711, 13.2346), "pordenone": ("PN", 45.9563, 12.6605),
    "gorizia": ("GO", 45.9410, 13.6218),
    "ancona": ("AN", 43.6158, 13.5189), "pesaro": ("PU", 43.9102, 12.9132),
    "macerata": ("MC", 43.2999, 13.4530), "ascoli piceno": ("AP", 42.8537, 13.5749),
    "fermo": ("FM", 43.1607, 13.7186), "perugia": ("PG", 43.1107, 12.3908),
    "terni": ("TR", 42.5636, 12.6427), "roma": ("RM", 41.9028, 12.4964),
    "latina": ("LT", 41.4676, 12.9037), "frosinone": ("FR", 41.6396, 13.3419),
    "viterbo": ("VT", 42.4207, 12.1077), "rieti": ("RI", 42.4043, 12.8567),
    "napoli": ("NA", 40.8518, 14.2681), "salerno": ("SA", 40.6824, 14.7681),
    "caserta": ("CE", 41.0723, 14.3327), "benevento": ("BN", 41.1298, 14.7826),
    "avellino": ("AV", 40.9144, 14.7906), "bari": ("BA", 41.1171, 16.8719),
    "lecce": ("LE", 40.3515, 18.1750), "taranto": ("TA", 40.4644, 17.2470),
    "brindisi": ("BR", 40.6327, 17.9418), "foggia": ("FG", 41.4622, 15.5446),
    "pescara": ("PE", 42.4618, 14.2161), "laquila": ("AQ", 42.3498, 13.3995),
    "chieti": ("CH", 42.3512, 14.1680), "teramo": ("TE", 42.6589, 13.7042),
    "campobasso": ("CB", 41.5603, 14.6627), "potenza": ("PZ", 40.6395, 15.8052),
    "matera": ("MT", 40.6664, 16.6043), "cosenza": ("CS", 39.2983, 16.2536),
    "catanzaro": ("CZ", 38.9098, 16.5877), "reggio calabria": ("RC", 38.1113, 15.6473),
    "palermo": ("PA", 38.1157, 13.3615), "catania": ("CT", 37.5079, 15.0830),
    "messina": ("ME", 38.1938, 15.5540), "siracusa": ("SR", 37.0755, 15.2866),
    "trapani": ("TP", 38.0176, 12.5365), "agrigento": ("AG", 37.3111, 13.5765),
    "cagliari": ("CA", 39.2238, 9.1217), "sassari": ("SS", 40.7259, 8.5557),
    "nuoro": ("NU", 40.3210, 9.3300), "oristano": ("OR", 39.9062, 8.5880),
    "aosta": ("AO", 45.7372, 7.3206),
}

# Ripiego quando l'ente cita la regione e non il comune (es. "Regione Emilia-Romagna"):
# si usa il capoluogo, con l'avvertenza che la sede effettiva va verificata nel bando.
REGIONI = {
    "emilia-romagna": "bologna", "emilia romagna": "bologna", "toscana": "firenze",
    "lombardia": "milano", "veneto": "venezia", "piemonte": "torino", "liguria": "genova",
    "marche": "ancona", "umbria": "perugia", "lazio": "roma", "campania": "napoli",
    "puglia": "bari", "abruzzo": "laquila", "molise": "campobasso", "basilicata": "potenza",
    "calabria": "catanzaro", "sicilia": "palermo", "sardegna": "cagliari",
    "friuli venezia giulia": "trieste", "valle daosta": "aosta", "trentino alto adige": "trento",
}

# ---------------------------------------------------------------------------
# Regole di classificazione — sono la parte che vorrai tarare col tempo
# ---------------------------------------------------------------------------

REGOLE_INQUADRAMENTO = [
    ("Dirigenza",      r"\bdirigent|\bdirettore general|\bdirettore ammin"),
    ("Funzionari/EQ",  r"\bfunzionari|elevata qualificazione|\bEQ\b|categoria d\b|\barea dei funzionari|istruttore direttivo|specialista\b"),
    ("Istruttori",     r"\bistruttor|categoria c\b|\bcollaborator|\barea degli istruttori|assistente\b"),
    ("Operatori",      r"\boperator|categoria b\b|\bausiliar|\barea degli operatori"),
]

REGOLE_AREA = [
    ("Informatica/Dati",       r"informatic|\bIT\b|informativ|dati\b|digital|cyber|statistic|analis[it] dat|transizione digitale"),
    ("Economico-finanziaria",  r"contabil|ragioner|economic|finanziar|bilancio|tribut|controllo di gestione|fiscal"),
    ("Tecnica",                r"\btecnic|ingegner|architett|geometra|geolog|agronom|manutenzion|lavori pubblici|urbanistic"),
    ("Sanitaria",              r"medic|infermier|\bOSS\b|sanitari|farmacist|biolog|veterinar|psicolog|tecnico di laboratorio"),
    ("Docenza/Ricerca",        r"ricercator|professor|docent|borsa di ricerca|assegno di ricerca|dottorat"),
    ("Legale",                 r"\blegal|avvocat|contenzios|appalt|contratti pubblici"),
    ("Amministrativa",         r"amministrativ|segretari|protocoll|personale\b|risorse umane|servizi al cittadino|anagraf"),
]

# Atti che compaiono nella 4a Serie ma non sono bandi a cui candidarsi.
REGOLE_ESCLUSIONE = r"""
graduatoria|registro dei revisori|revisori legali|commissione esaminatrice|
diario delle prove|calendario delle prove|nomina della commissione|
annullamento|revoca del concorso|errata corrige|rettifica.{0,40}graduatoria|
elenco dei vincitori|sorteggio dei componenti|conferimento di.{0,30}borse di studio
""".replace("\n", "").strip()

REGOLE_TIPO = [
    ("Mobilità",  r"mobilit"),
    ("Selezione", r"selezion|avviso|manifestazione di interesse|elenco idonei|conferimento"),
    ("Concorso",  r"concors"),
]

MESI = {
    "gennaio": 1, "febbraio": 2, "marzo": 3, "aprile": 4, "maggio": 5, "giugno": 6,
    "luglio": 7, "agosto": 8, "settembre": 9, "ottobre": 10, "novembre": 11, "dicembre": 12,
}

NUMERI_PAROLA = {
    "un": 1, "uno": 1, "una": 1, "due": 2, "tre": 3, "quattro": 4, "cinque": 5,
    "sei": 6, "sette": 7, "otto": 8, "nove": 9, "dieci": 10, "undici": 11,
    "dodici": 12, "quindici": 15, "venti": 20, "trenta": 30,
}


# ---------------------------------------------------------------------------
# Utilita'
# ---------------------------------------------------------------------------

def normalizza(testo: str) -> str:
    """minuscolo, senza accenti, spazi compattati."""
    t = unicodedata.normalize("NFKD", testo or "")
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", t).strip().lower()


def distanza_km(lat1, lon1, lat2, lon2) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return r * 2 * math.asin(math.sqrt(a))


def carica_comuni_csv(cartella: Path) -> None:
    """Se esiste comuni.csv accanto allo script, arricchisce l'anagrafica."""
    f = cartella / "comuni.csv"
    if not f.exists():
        return
    import csv
    aggiunti = 0
    with f.open(encoding="utf-8-sig", newline="") as fh:
        for riga in csv.DictReader(fh, delimiter=";"):
            try:
                nome = normalizza(riga["comune"])
                COMUNI[nome] = (riga["sigla"].strip().upper(),
                                float(str(riga["lat"]).replace(",", ".")),
                                float(str(riga["lon"]).replace(",", ".")))
                aggiunti += 1
            except (KeyError, ValueError):
                continue
    print(f"  anagrafica comuni: +{aggiunti} da comuni.csv")


def sessione() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": CONFIG["user_agent"], "Accept-Language": "it-IT,it;q=0.9"})
    return s


def scarica(sess: requests.Session, url: str) -> str | None:
    try:
        r = sess.get(url, timeout=CONFIG["timeout"])
        r.raise_for_status()
        r.encoding = r.encoding or "utf-8"
        return r.text
    except requests.RequestException as e:
        print(f"  ! richiesta fallita: {url}\n    {e}", file=sys.stderr)
        return None


# ---------------------------------------------------------------------------
# Estrazione
# ---------------------------------------------------------------------------

def trova_gazzette(html: str, giorni: int) -> list[tuple[str, str]]:
    """Dalla pagina /30giorni/concorsi ricava (numero, data ISO) delle uscite."""
    limite = date.today() - timedelta(days=giorni)
    trovate: dict[str, str] = {}

    # forma tipica del link al sommario di una singola Gazzetta
    for data_iso, numero in re.findall(
        r"dataPubblicazioneGazzetta=(\d{4}-\d{2}-\d{2})[^\"'>]*?numeroGazzetta=(\d+)", html):
        trovate[numero] = data_iso
    # ordine invertito dei parametri, per sicurezza
    for numero, data_iso in re.findall(
        r"numeroGazzetta=(\d+)[^\"'>]*?dataPubblicazioneGazzetta=(\d{4}-\d{2}-\d{2})", html):
        trovate.setdefault(numero, data_iso)

    uscite = []
    for numero, data_iso in trovate.items():
        try:
            d = datetime.strptime(data_iso, "%Y-%m-%d").date()
        except ValueError:
            continue
        if d >= limite:
            uscite.append((numero, data_iso))
    return sorted(uscite, key=lambda x: x[1], reverse=True)


ETICHETTE = {
    "avviso", "concorso", "concorsi", "graduatoria", "graduatorie", "nomina", "nomine",
    "diario", "diari", "selezione", "selezioni", "mobilita", "esame", "esami", "rettifica",
    "proroga", "riapertura", "annullamento", "revoca", "sorteggio", "comunicato",
    "errata corrige", "pag", "sommario", "indice", "concorsi ed esami",
}


def _e_intestazione(t: str) -> bool:
    """Vero se la stringa sembra il nome di un ente: quasi tutta maiuscola,
    non una delle etichette di rubrica, non una riga di atto."""
    if len(t) > 130 or "scad" in t.lower():
        return False
    if normalizza(t).strip(" .:-") in ETICHETTE:
        return False
    lettere = [c for c in t if c.isalpha()]
    if len(lettere) < 6:
        return False
    return sum(1 for c in lettere if c.isupper()) / len(lettere) > 0.85


def estrai_atti(html: str, numero: str, data_iso: str) -> list[dict]:
    """Dal sommario di una Gazzetta ricava i singoli bandi.

    Il sommario raggruppa gli atti sotto un'intestazione con il nome dell'ente:
    si scorre il documento nell'ordine e si tiene traccia dell'ultima vista.
    """
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style"]):
        tag.decompose()

    atti: list[dict] = []
    visti: set[str] = set()
    ente_corrente = ""

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
            codice = m.group(1)
            visti.add(codice)

            oggetto = re.sub(r"\s+", " ", nodo.get_text(" ", strip=True))
            riga = nodo.parent.get_text(" ", strip=True) if nodo.parent else oggetto

            atti.append({
                "codice": codice,
                "ente_grezzo": ente_corrente,
                "oggetto": oggetto,
                "contesto": re.sub(r"\s+", " ", riga),
                "gu": f"n. {numero} del {datetime.strptime(data_iso, '%Y-%m-%d').strftime('%d-%m-%Y')}",
                "url_gu": href if href.startswith("http") else BASE + ("" if href.startswith("/") else "/") + href,
            })
            continue

        # nodo di testo: candidato a essere l'intestazione dell'ente
        if isinstance(nodo, NavigableString):
            t = str(nodo).strip()
            if not t or nodo.find_parent("a"):
                continue
            if _e_intestazione(t):
                ente_corrente = t

    return atti


def estrai_ente(ente_grezzo: str, contesto: str, oggetto: str) -> str:
    """Usa l'intestazione di gruppo; in mancanza ripiega sul testo della riga."""
    if ente_grezzo:
        return re.sub(r"\s+", " ", ente_grezzo).strip(" -–.").title()
    testa = contesto.split(oggetto)[0] if oggetto and oggetto in contesto else contesto
    m = re.search(r"([A-ZÀ-Ü][A-ZÀ-Ü'\-\.\s]{6,90})", testa.strip())
    if m:
        return re.sub(r"\s+", " ", m.group(1)).strip(" -–").title()
    return "Ente non rilevato"


def estrai_scadenza(testo: str) -> date | None:
    m = re.search(r"scad\.?\s*:?\s*(\d{1,2})\s+([a-zà-ù]+)\s+(\d{4})", testo, re.IGNORECASE)
    if m:
        giorno, mese, anno = int(m.group(1)), MESI.get(normalizza(m.group(2))), int(m.group(3))
        if mese:
            try:
                return date(anno, mese, giorno)
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
    m = re.search(r"\bn\.?\s*(\d{1,4})\s+post", t) or re.search(r"(\d{1,4})\s+post", t)
    if m:
        return int(m.group(1))
    m = re.search(r"\b([a-z]+)\s+post", t)
    if m and m.group(1) in NUMERI_PAROLA:
        return NUMERI_PAROLA[m.group(1)]
    if re.search(r"\bun\s+post|\bdi\s+un\s+post", t):
        return 1
    return None


def classifica(testo: str, regole: list[tuple[str, str]], default: str | None = None) -> str | None:
    t = normalizza(testo)
    for etichetta, pattern in regole:
        if re.search(pattern, t, re.IGNORECASE):
            return etichetta
    return default


PREPOSIZIONI = {"di", "del", "dello", "della", "dei", "degli", "delle",
                "a", "ad", "in", "presso", "d", "comune", "citta", "sede"}


def trova_sede(ente: str, oggetto: str) -> tuple[str, float, float] | None:
    """Cerca il comune citato, provando prima nel nome dell'ente.

    Il confronto avviene su gruppi di 1-4 parole consecutive, non con una regex
    per ogni comune: e' molto piu' rapido su un'anagrafica di ottomila voci.
    I nomi corti (Ne, Lu, Sale, Este...) valgono solo se preceduti da una
    preposizione, altrimenti coinciderebbero con parole italiane comuni.
    """
    for fonte, esigente in ((ente, False), (oggetto, True)):
        if not fonte:
            continue
        tok = re.findall(r"[a-z0-9']+", normalizza(fonte))
        migliore = None

        for i in range(len(tok)):
            for n in range(4, 0, -1):
                if i + n > len(tok):
                    continue
                nome = " ".join(tok[i:i + n])
                dati = COMUNI.get(nome)
                if not dati:
                    continue
                # nome ambiguo, o ricerca dentro il testo del bando: serve un aggancio
                if (esigente or len(nome) <= 5) and (i == 0 or tok[i - 1] not in PREPOSIZIONI):
                    continue
                if migliore is None or len(nome) > len(migliore[0]):
                    migliore = (nome, dati)

        if migliore:
            nome, (sigla, lat, lon) = migliore
            return f"{nome.title()} ({sigla})", lat, lon

    # nessun comune: provo con la regione, segnalando l'approssimazione
    t = normalizza(f"{ente} {oggetto}")
    for regione, capoluogo in REGIONI.items():
        if re.search(rf"\b{re.escape(regione)}\b", t):
            sigla, lat, lon = COMUNI[capoluogo]
            return f"{capoluogo.title()} ({sigla}) - sede da verificare", lat, lon
    return None


# ---------------------------------------------------------------------------
# Punteggio
# ---------------------------------------------------------------------------

def punteggia(b: dict) -> tuple[float, int]:
    p = CONFIG["pesi"]
    tot = 0.0

    if not CONFIG["inquadramenti_target"] or b["inquadramento"] in CONFIG["inquadramenti_target"]:
        tot += p["inquadramento"]
    if not CONFIG["aree_target"] or b["area"] in CONFIG["aree_target"]:
        tot += p["area"]
    if b["km"] is not None:
        tot += p["vicinanza"] * max(0.0, 1 - b["km"] / CONFIG["raggio_km"])
    if b["giorni"] is not None:
        tot += p["tempo"] * min(1.0, b["giorni"] / 30)

    massimo = sum(p.values())
    percentuale = tot / massimo if massimo else 0
    return round(percentuale * 100, 1), max(1, min(5, math.ceil(percentuale * 5)))


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def elabora(atti: list[dict]) -> list[dict]:
    org = CONFIG["origine"]
    oggi = date.today()
    fuori: list[dict] = []

    for a in atti:
        testo = f"{a['contesto']} {a['oggetto']}"
        ente = estrai_ente(a.get("ente_grezzo", ""), a["contesto"], a["oggetto"])
        scadenza = estrai_scadenza(testo)
        giorni = (scadenza - oggi).days if scadenza else None

        sede = trova_sede(ente, a["oggetto"])
        if sede:
            nome_sede, lat, lon = sede
            km = round(distanza_km(org["lat"], org["lon"], lat, lon))
        else:
            nome_sede, km = None, None

        b = {
            "codice": a["codice"],
            "ente": ente,
            "titolo": a["oggetto"][:220],
            "tipo": classifica(testo, REGOLE_TIPO, "Concorso"),
            "inquadramento": classifica(testo, REGOLE_INQUADRAMENTO),
            "area": classifica(testo, REGOLE_AREA),
            "posti": estrai_posti(testo),
            "sede": nome_sede,
            "km": km,
            "scadenza": scadenza.isoformat() if scadenza else None,
            "giorni": giorni,
            "gu": a["gu"],
            "url_gu": a["url_gu"],
            "url_candidatura": URL_INPA_RICERCA.format(q=a["codice"]),
            "origine_sigla": org["sigla"],
        }
        b["punteggio"], b["affinita"] = punteggia(b)
        fuori.append(b)

    return fuori


def filtra(bandi: list[dict]) -> tuple[list[dict], dict]:
    """Applica i filtri di profilo e restituisce anche il conteggio degli scarti,
    utile per capire se una regola e' troppo stretta."""
    motivi = {"non è un bando": 0, "sede non riconosciuta": 0, "troppo lontano": 0,
              "scaduto o quasi": 0, "inquadramento fuori target": 0, "area fuori target": 0}
    tenuti = []

    for b in bandi:
        testo = normalizza(f"{b['titolo']} {b['tipo']}")
        if re.search(REGOLE_ESCLUSIONE, testo, re.IGNORECASE):
            motivi["non è un bando"] += 1
            continue
        if b["km"] is None:
            motivi["sede non riconosciuta"] += 1
            continue
        if b["km"] > CONFIG["raggio_km"]:
            motivi["troppo lontano"] += 1
            continue
        if b["giorni"] is not None and b["giorni"] < CONFIG["giorni_minimi"]:
            motivi["scaduto o quasi"] += 1
            continue
        if CONFIG["inquadramenti_target"] and b["inquadramento"] not in CONFIG["inquadramenti_target"]:
            motivi["inquadramento fuori target"] += 1
            continue
        if CONFIG["aree_target"] and b["area"] not in CONFIG["aree_target"]:
            motivi["area fuori target"] += 1
            continue
        tenuti.append(b)

    return tenuti, motivi


def scrivi_dashboard(bandi: list[dict], totale_letti: int, cartella: Path, nota: str) -> Path:
    template = (cartella / "template.html").read_text(encoding="utf-8")
    org = CONFIG["origine"]
    html = (template
            .replace("__DATI__", json.dumps(bandi, ensure_ascii=False))
            .replace("__RAGGIO__", str(CONFIG["raggio_km"]))
            .replace("__ORIGINE__", org["nome"])
            .replace("__TOTALE__", str(totale_letti))
            .replace("__AGGIORNAMENTO__", datetime.now().strftime("%d/%m %H:%M"))
            .replace("__SOTTOTITOLO__", "Gazzetta Ufficiale · 4ª Serie Speciale")
            .replace("__NOTA__", nota))
    out = cartella / CONFIG["output_html"]
    out.write_text(html, encoding="utf-8")
    (cartella / CONFIG["output_json"]).write_text(
        json.dumps(bandi, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def dati_demo() -> list[dict]:
    org = CONFIG["origine"]
    grezzi = [
        ("26E04591", "Comune Di Bologna", "Concorso pubblico, per esami, per la copertura di sei posti di funzionario amministrativo, area dei funzionari, a tempo indeterminato.", "n. 64 del 21-08-2026", 9),
        ("26E04512", "Regione Emilia-Romagna", "Concorso pubblico, per titoli ed esami, per la copertura di quattro posti di funzionario esperto in analisi dati e sistemi informativi.", "n. 63 del 18-08-2026", 21),
        ("26E04520", "Azienda Usl Di Modena", "Concorso pubblico per la copertura di due posti di collaboratore amministrativo per il controllo di gestione.", "n. 63 del 18-08-2026", 26),
        ("26E04466", "Comune Di Ferrara", "Concorso pubblico, per esami, per la copertura di tre posti di istruttore direttivo contabile presso il servizio ragioneria.", "n. 62 del 14-08-2026", 5),
        ("26E04603", "Provincia Di Ravenna", "Procedura di mobilita' volontaria per la copertura di un posto di funzionario dei servizi informativi.", "n. 64 del 21-08-2026", 14),
        ("26E04471", "Universita Di Parma", "Concorso pubblico per la copertura di un posto di dirigente dell'area organizzazione e sistemi informativi.", "n. 62 del 14-08-2026", 33),
        ("26E04402", "Comune Di Padova", "Concorso pubblico, per esami, per la copertura di due posti di funzionario esperto in appalti e contratti pubblici.", "n. 61 del 11-08-2026", 52),
    ]
    atti = []
    for codice, ente, oggetto, gu, gg in grezzi:
        scad = (date.today() + timedelta(days=gg)).strftime("%d {} %Y").format(
            [k for k, v in MESI.items() if v == (date.today() + timedelta(days=gg)).month][0])
        atti.append({
            "codice": codice,
            "oggetto": oggetto,
            "contesto": f"{ente.upper()} - CONCORSO (scad. {scad}) {oggetto}",
            "gu": gu,
            "url_gu": f"{BASE}/atto/concorsi/caricaDettaglioAtto/originario?atto.codiceRedazionale={codice}",
        })
    return elabora(atti)


def main() -> int:
    ap = argparse.ArgumentParser(description="Radar concorsi dalla GU 4a Serie Speciale")
    ap.add_argument("--giorni", type=int, default=30, help="finestra di pubblicazione da leggere")
    ap.add_argument("--tutti", action="store_true", help="non applicare i filtri di target")
    ap.add_argument("--demo", action="store_true", help="usa dati finti, senza rete")
    ap.add_argument("--debug", action="store_true", help="stampa il dettaglio del parsing")
    args = ap.parse_args()

    cartella = Path(__file__).resolve().parent
    carica_comuni_csv(cartella)

    if args.demo:
        bandi = dati_demo()
        totale = len(bandi)
        nota = "Dati dimostrativi: nessuna richiesta di rete effettuata."
        print(f"Demo: {totale} bandi generati.")
    else:
        sess = sessione()
        print("Leggo l'elenco delle ultime Gazzette…")
        indice = scarica(sess, URL_30GIORNI)
        if not indice:
            print("Non riesco a leggere l'indice. Controlla la connessione.", file=sys.stderr)
            return 1

        uscite = trova_gazzette(indice, args.giorni)
        if not uscite:
            print("Nessuna uscita trovata: la struttura della pagina è cambiata.\n"
                  "Apri /30giorni/concorsi e controlla il formato dei link.", file=sys.stderr)
            return 2
        print(f"  {len(uscite)} uscite negli ultimi {args.giorni} giorni")

        atti: list[dict] = []
        for numero, data_iso in uscite:
            url = URL_SOMMARIO.format(data=data_iso, numero=numero)
            html = scarica(sess, url)
            if not html:
                continue
            trovati = estrai_atti(html, numero, data_iso)
            atti.extend(trovati)
            print(f"  GU n. {numero} del {data_iso}: {len(trovati)} atti")
            if args.debug and trovati:
                print(f"    esempio → {trovati[0]['contesto'][:160]}")
            time.sleep(CONFIG["pausa"])

        if not atti:
            print("Sommari letti ma nessun atto estratto: da rivedere i selettori.", file=sys.stderr)
            return 3

        # deduplica sul codice redazionale
        unici = {a["codice"]: a for a in atti}
        bandi = elabora(list(unici.values()))
        totale = len(bandi)
        nota = (f"{totale} atti letti dalle Gazzette degli ultimi {args.giorni} giorni. "
                "Inquadramento e area sono dedotti dal testo del sommario: verifica sempre il bando originale.")

    if not args.tutti:
        prima = len(bandi)
        bandi, motivi = filtra(bandi)
        print(f"Filtro sul profilo: {len(bandi)} bandi su {prima}.")
        for motivo, quanti in sorted(motivi.items(), key=lambda x: -x[1]):
            if quanti:
                print(f"    scartati per {motivo}: {quanti}")

    bandi.sort(key=lambda b: (-b["punteggio"], b["km"] if b["km"] is not None else 9999))
    out = scrivi_dashboard(bandi, totale, cartella, nota)
    print(f"Dashboard pronta: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
