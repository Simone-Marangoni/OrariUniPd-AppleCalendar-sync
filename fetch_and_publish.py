"""
Scarica dall'Agenda Web di UniPD gli orari delle lezioni e li mantiene
sincronizzati in un file .ics cumulativo (docs/calendar.ics), da pubblicare
con GitHub Pages e sottoscrivere una sola volta su Calendario Apple.

Comportamento:
- Ogni nuova settimana compare per la prima volta WEEKS_AHEAD settimane
  prima che inizi.
- Ad ogni esecuzione, oltre alla nuova settimana, vengono RICONTROLLATE
  anche le settimane già pubblicate (dalla settimana corrente fino a
  WEEKS_AHEAD settimane nel futuro): se una lezione che prima c'era ora
  non compare più nella fonte, viene considerata cancellata e rimossa dal
  file pubblicato. Le settimane più vecchie della settimana corrente non
  vengono più ricontrollate (restano "congelate" nello storico).
"""

import os
from datetime import date, datetime, timedelta

import requests
from icalendar import Calendar

# ---------------------------------------------------------------------------
# CONFIGURAZIONE
# ---------------------------------------------------------------------------

SOURCE_URL_TEMPLATE = (
    "https://agendastudentiunipd.easystaff.it/export/ec_download_ical_grid.php?"
    "view=easycourse&form-type=corso&include=corso&txtcurr=1+-+GENERALE+%28canale+1%29"
    "&anno=2026&scuola=ScuoladiIngegneria&corso=IN2912&anno2%5B%5D=001PD_C1%7C1"
    "&date={date}&periodo_didattico=&_lang=it&list=&week_grid_type=-1&ar_codes_="
    "&ar_select_=&col_cells=0&empty_box=0&only_grid=0&highlighted_date=0&all_events=0"
    "&faculty_group=0&_lang=it&ar_codes_=EC957274|EC957283|EC151723|EC151736"
    "&ar_select_=true|true|true|true&txtaa=2026/2027"
    "&txtcorso=IN2912%20-%20INGEGNERIA%20INFORMATICA%20(Laurea)"
    "&txtanno=&docente=&attivita=&txtdocente=&txtattivita="
)

# Quante settimane prima dell'inizio una settimana compare per la prima volta.
WEEKS_AHEAD = 2

OUTPUT_PATH = "docs/calendar.ics"

# ---------------------------------------------------------------------------


def get_this_monday() -> datetime:
    today = datetime.now()
    return today - timedelta(days=today.weekday())


def get_check_mondays() -> list[datetime]:
    """Lunedì delle settimane da (ri)controllare ad ogni esecuzione: dalla
    settimana corrente fino a WEEKS_AHEAD settimane nel futuro."""
    this_monday = get_this_monday()
    return [this_monday + timedelta(weeks=i) for i in range(0, WEEKS_AHEAD + 1)]


def to_date(value) -> date:
    return value.date() if hasattr(value, "date") else value


def fetch_week(monday: datetime) -> bytes:
    date_str = monday.strftime("%d-%m-%Y")
    url = SOURCE_URL_TEMPLATE.format(date=date_str)
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    if not resp.content.strip().startswith(b"BEGIN:VCALENDAR"):
        raise RuntimeError(
            "La risposta non sembra un file .ics valido. "
            "Il link potrebbe essere scaduto o richiedere di nuovo il login."
        )
    return resp.content


def load_existing(path: str) -> Calendar:
    if os.path.exists(path):
        with open(path, "rb") as f:
            return Calendar.from_ical(f.read())
    cal = Calendar()
    cal.add("prodid", "-//OrariUniPD Auto Export//")
    cal.add("version", "2.0")
    return cal


def main() -> None:
    check_mondays = get_check_mondays()
    window_start = check_mondays[0].date()
    window_end = (check_mondays[-1] + timedelta(days=7)).date()

    print(f"Ricontrollo le settimane dal {window_start:%d-%m-%Y} al {window_end:%d-%m-%Y}")

    fresh_events = {}
    for monday in check_mondays:
        print(f"  scarico settimana {monday:%d-%m-%Y}")
        ics_bytes = fetch_week(monday)
        cal = Calendar.from_ical(ics_bytes)
        for component in cal.walk("VEVENT"):
            fresh_events[str(component.get("UID"))] = component

    existing_cal = load_existing(OUTPUT_PATH)

    final_events = {}
    removed = 0
    for component in existing_cal.walk("VEVENT"):
        uid = str(component.get("UID"))
        dtstart_date = to_date(component.get("DTSTART").dt)
        in_checked_window = window_start <= dtstart_date < window_end
        if in_checked_window and uid not in fresh_events:
            removed += 1
            continue
        final_events[uid] = component

    added = sum(1 for uid in fresh_events if uid not in final_events)
    final_events.update(fresh_events)

    merged = Calendar()
    merged.add("prodid", "-//OrariUniPD Auto Export//")
    merged.add("version", "2.0")
    merged.add("x-wr-timezone", "Europe/Rome")
    for comp in final_events.values():
        merged.add_component(comp)

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "wb") as f:
        f.write(merged.to_ical())

    print(
        f"Eventi totali: {len(final_events)} | "
        f"nuovi/aggiornati: {added} | rimossi (cancellati): {removed}"
    )


if __name__ == "__main__":
    main()
