# Sincronizzazione automatica OrariUniPD → Calendario Apple

Questo mini-progetto scarica ogni giorno, in automatico, gli orari delle
lezioni dall'Agenda Web di UniPD per un intervallo di settimane (settimana corrente + le successive) e li pubblica in un file `.ics` che il tuo Calendario Apple può
sottoscrivere **una sola volta**. Da lì in poi si aggiorna da solo.

---

## Come funziona

1. **Esecuzione quotidiana**: GitHub Actions esegue `fetch_and_publish.py` ogni notte.
2. **Download e verifica**:
   - Scarica l'export iCal delle settimane coperte dal sito UniPD.
   - Interroga l'API dell'Agenda Web (`grid_call.php`) per rilevare lo stato effettivo di ciascuna lezione (`Annullato: 1`).
3. **Gestione lezioni annullate**:
   - Poiché l'export iCal standard di UniPD ignora le cancellazioni, lo script le individua e applica la modalità scelta:
     - `cancel` (predefinita): imposta `STATUS:CANCELLED` e antepone `❌ [ANNULLATA]` al titolo, rendendo subito evidente sul calendario Apple che la lezione è saltata.
     - `remove`: rimuove completamente l'evento dal file.
4. **Formattazione pulita**: Riorganizza materia, aula, docente ed edificio in campi ordinati per Apple Calendar (`event_formatting.py`).
5. **Pubblicazione**: GitHub Pages serve `docs/calendar.ics` a un URL pubblico stabile.
6. **Sincronizzazione**: Il tuo iPhone / Mac consulta periodicamente l'URL e riceve gli orari e le cancellazioni aggiornati.

---

## Script di verifica: `check_cancelled.py`

È disponibile uno script per verificare in tempo reale lo stato delle lezioni e confrontare l'Agenda Web con il file `docs/calendar.ics`:

```bash
# Verifica le prossime 3 settimane
python3 check_cancelled.py

# Verifica a partire da una data specifica (es. 28-09-2026)
python3 check_cancelled.py --date 2026-09-28 --weeks 2

# Applica direttamente le correzioni al file docs/calendar.ics
python3 check_cancelled.py --fix --action cancel

# Oppure rimuovi completamente le lezioni annullate
python3 check_cancelled.py --fix --action remove
```

Lo script analizza le lezioni della griglia web, mostra quali sono confermate e quali annullate, segnalando se compaiono ancora come attive nel file `.ics`.

---

## Sottoscrizione del calendario su iPhone / Apple Calendar

1. Apri **Impostazioni → App → Calendario → Account** (su iOS più recenti: *Impostazioni → Calendario → Account*).
2. Tocca **Aggiungi account** → **Altro** → **Aggiungi calendario sottoscritto**.
3. Incolla l'URL:
   ```
   https://simone-marangoni.github.io/OrariUniPd-AppleCalendar-sync/calendar.ics
   ```
4. Salva. Fatto: da ora in poi si aggiorna automaticamente.
