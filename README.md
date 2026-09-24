# Radar Concorsi

Ogni mattina legge la Gazzetta Ufficiale (4ª Serie Speciale), tiene i bandi da Funzionario,
Dirigente e Istruttore nelle aree amministrativa, economico-finanziaria, informatica/dati e
tecnica/logistica, calcola la distanza da Bologna e aggiorna la pagina del radar.

Quando esce un bando nuovo da Funzionario o Dirigente entro 100 km, apre una issue:
GitHub te la manda per email.

## File
- `radar.py` — lettura della Gazzetta, classificazione, pagina, avvisi. Le impostazioni sono nel blocco `CONFIG` in cima.
- `template.html` — grafica della pagina.
- `comuni.csv` — 7.856 comuni con coordinate, per le distanze.
- `.github/workflows/radar.yml` — orario e passi dell'aggiornamento automatico.
- `docs/` — la pagina pubblicata (generata, non modificare a mano).
- `stato/visti.json` — bandi già segnalati, per non ripetere le email.

## Se qualcosa non va
Apri la scheda **Actions**, entra nell'ultima esecuzione e guarda il passo "Leggo la Gazzetta Ufficiale":
il messaggio che inizia con ERRORE dice cosa è successo.
