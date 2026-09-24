# Radar Concorsi

Monitora la 4ª Serie Speciale "Concorsi ed esami" della Gazzetta Ufficiale, classifica i
bandi per inquadramento e area, calcola la distanza da Bologna e rigenera una dashboard
HTML che si apre con un doppio clic.

## File

| File | Cosa fa |
|---|---|
| `radar_concorsi.py` | scarico, parsing, classificazione, punteggio |
| `template.html` | aspetto della dashboard (i dati vengono iniettati dentro) |
| `radar_concorsi.html` | prodotto a ogni esecuzione — è quello che apri |
| `comuni.csv` | anagrafica dei comuni con coordinate, per il calcolo delle distanze |
| `concorsi.json` | stessi dati in formato lavorabile (Power BI, Excel, SQL) |

## Installazione

```bash
pip3 install requests beautifulsoup4
```

## Uso

```bash
python3 radar_concorsi.py              # ultimi 30 giorni, filtrato sul profilo
python3 radar_concorsi.py --giorni 14  # finestra più stretta
python3 radar_concorsi.py --tutti      # niente filtri: vedi tutto e filtri a mano
python3 radar_concorsi.py --demo       # dati finti, per provare senza rete
python3 radar_concorsi.py --debug      # mostra cosa legge da ogni sommario
```

Poi apri `radar_concorsi.html`.

## Prima esecuzione: cosa controllare

Il parsing si appoggia alla struttura delle pagine di gazzettaufficiale.it, che
cambia senza preavviso. Se qualcosa non torna, lo script te lo dice:

- **"Nessuna uscita trovata"** → è cambiato il formato dei link in `/30giorni/concorsi`.
  Apri la pagina, guarda un link a una singola Gazzetta e adegua la regex in `trova_gazzette`.
- **"nessun atto estratto"** → è cambiato il sommario. Lancia con `--debug` e adegua `estrai_atti`.
- **Ente o scadenza sbagliati** → sono estratti dal testo del sommario con regex, in
  `estrai_ente` e `estrai_scadenza`.

Inquadramento e area sono **dedotti** dal testo: usali per ordinare le priorità, non come
verità. Il link "Testo in GU" porta al bando integrale, che resta la fonte da leggere prima
di candidarsi.

## Tarare i filtri

Tutto sta nel blocco `CONFIG` in cima allo script: città di riferimento, raggio in km,
inquadramenti e aree che ti interessano, giorni minimi residui, pesi del punteggio.
Le parole chiave della classificazione stanno in `REGOLE_INQUADRAMENTO` e `REGOLE_AREA`:
aggiungine man mano che vedi bandi classificati male.

## Precisione geografica

Il file `comuni.csv` allegato contiene tutti i 7.856 comuni italiani con le coordinate:
tienilo nella stessa cartella e viene caricato da solo a ogni esecuzione. Senza di esso lo
script funziona lo stesso, ma riconosce solo i capoluoghi.

Il riconoscimento cerca il comune prima nel nome dell'ente e poi nel testo del bando. I nomi
brevi che coincidono con parole italiane (Ne, Lu, Sale, Este) vengono accettati solo se
preceduti da una preposizione, per evitare abbagli.

Quando l'ente cita solo la regione, la sede viene stimata sul capoluogo ed etichettata
"sede da verificare".

## Farlo girare da solo

**macOS / Linux** — `crontab -e`, poi una riga per martedì e venerdì alle 7:30
(la GU esce quei giorni):

```
30 7 * * 2,5 cd /percorso/della/cartella && /usr/bin/python3 radar_concorsi.py >> radar.log 2>&1
```

**Windows** — Utilità di pianificazione, nuova attività settimanale su martedì e venerdì,
azione `python.exe` con argomento `radar_concorsi.py` e "Inizio in" impostato sulla cartella.

## Candidature

La dashboard porta alla ricerca su InPA per codice redazionale. La domanda si presenta lì
con SPID o CIE, oppure sul portale dell'ente quando il bando lo prevede: il radar segnala e
apre la strada, l'invio resta un gesto tuo.
