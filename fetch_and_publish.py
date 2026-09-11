"""
Scarica dall'Agenda Web di UniPD gli orari della settimana che inizia tra
WEEKS_AHEAD settimane, e li unisce a un file .ics cumulativo (docs/calendar.ics)
che puoi pubblicare con GitHub Pages e sottoscrivere una sola volta su
Calendario Apple (o Google Calendar).

Ogni evento nell'ics di UniPD ha un UID stabile: lo script lo usa per evitare
duplicati e per aggiornare un evento se orario/aula cambiano.
"""

import os
from datetime import datetime, timedelta

import requests
from icalendar import Calendar

# ---------------------------------------------------------------------------
# CONFIGURAZIONE
# ---------------------------------------------------------------------------

# URL copiato dal pulsante di export dell'Agenda Web (contiene già il tuo
# corso/canale/anno). La parte "date=28-09-2026" viene sostituita a runtime.
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

# Quante settimane prima dell'inizio della settimana va pubblicata.
WEEKS_AHEAD = 2

# Dove viene scritto il calendario cumulativo (servito da GitHub Pages se
# messo dentro /docs).
OUTPUT_PATH = "docs/calendar.ics"

# ---------------------------------------------------------------------------


def get_target_monday() -> datetime:
    """Lunedì della settimana che inizia tra WEEKS_AHEAD settimane."""
    today = datetime.now()
    this_monday = today - timedelta(days=today.weekday())
    return this_monday + timedelta(weeks=WEEKS_AHEAD)


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


def merge(existing_cal: Calendar, new_ics_bytes: bytes) -> Calendar:
    new_cal = Calendar.from_ical(new_ics_bytes)

    events_by_uid = {}
    for component in existing_cal.walk("VEVENT"):
        events_by_uid[str(component.get("UID"))] = component
    for component in new_cal.walk("VEVENT"):
        events_by_uid[str(component.get("UID"))] = component  # upsert

    merged = Calendar()
    merged.add("prodid", "-//OrariUniPD Auto Export//")
    merged.add("version", "2.0")
    merged.add("x-wr-timezone", "Europe/Rome")
    for comp in events_by_uid.values():
        merged.add_component(comp)
    return merged


def main() -> None:
    target_monday = get_target_monday()
    print(f"Scarico la settimana che inizia il {target_monday.strftime('%d-%m-%Y')}")

    new_ics = fetch_week(target_monday)
    existing_cal = load_existing(OUTPUT_PATH)
    merged_cal = merge(existing_cal, new_ics)

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "wb") as f:
        f.write(merged_cal.to_ical())

    total = len(merged_cal.walk("VEVENT"))
    print(f"Fatto: {total} eventi totali salvati in {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
