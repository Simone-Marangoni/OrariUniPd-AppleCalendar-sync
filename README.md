# Sincronizzazione automatica OrariUniPD → Calendario Apple

Questo mini-progetto scarica ogni giorno, in automatico, gli orari delle
lezioni dall'Agenda Web di UniPD per la settimana che inizia tra **2
settimane**, e li pubblica in un file `.ics` che il tuo Calendario Apple può
sottoscrivere **una sola volta**. Da lì in poi si aggiorna da solo.

## Come funziona

1. Ogni giorno, GitHub Actions (gratuito) esegue `fetch_and_publish.py`.
2. Lo script calcola il lunedì della settimana target e scarica l'export di
   quella settimana dal sito di UniPD.
3. Unisce quegli eventi a `docs/calendar.ics`, senza cancellare le settimane
   già raccolte in precedenza (usa l'UID di ogni lezione per evitare
   duplicati).
4. GitHub Pages pubblica `docs/calendar.ics` a un URL pubblico stabile.
5. Il tuo iPhone si sottoscrive a quell'URL e vede sempre gli aggiornamenti.



### - Sottoscrivi il calendario su iPhone

- Apri **Impostazioni → App → Calendario → Account** (su iOS più recenti:
  Impostazioni → Calendario → Account).
- "Aggiungi account" → "Altro" → "Aggiungi calendario sottoscritto".
- Incolla l'URL: `https://simone-marangoni.github.io/OrariUniPd-AppleCalendar-sync/calendar.ics`
- Salva. Fatto: da ora in poi si aggiorna da solo (iOS controlla gli
  aggiornamenti periodicamente, di solito ogni poche ore/un giorno).

