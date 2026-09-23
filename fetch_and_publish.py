"""
Scarica dall'Agenda Web di UniPD gli orari di un intervallo di settimane
(da questa settimana fino a WEEKS_RANGE settimane nel futuro) e li unisce a
un file .ics cumulativo (docs/calendar.ics) che puoi pubblicare con GitHub
Pages e sottoscrivere una sola volta su Calendario Apple (o Google Calendar).

A differenza della prima versione, ogni settimana viene RI-scaricata ogni
giorno finché rientra nell'intervallo, non solo la prima volta che compare a
WEEKS_AHEAD settimane di distanza. Questo permette di rilevare eventuali
variazioni fatte da UniPD dopo il primo caricamento: annullamenti, cambi di
aula, cambi di orario, ecc. — perché lo stesso UID viene semplicemente
sovrascritto (upsert) con la versione più recente.

Ogni evento nell'ics di UniPD ha un UID stabile: lo script lo usa per evitare
duplicati e per aggiornare un evento se orario/aula/stato cambiano.
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

# Quante settimane totali coprire ogni giorno, a partire da questa settimana
# (settimana corrente inclusa). Con WEEKS_RANGE = 3: questa settimana + le
# prossime 2 vengono ri-scaricate e ri-controllate ogni giorno.
WEEKS_RANGE = 3

# Dove viene scritto il calendario cumulativo (servito da GitHub Pages se
# messo dentro /docs).
OUTPUT_PATH = "docs/calendar.ics"

# ---------------------------------------------------------------------------


def get_target_mondays() -> list[datetime]:
    """Lunedì di ciascuna settimana da ricontrollare oggi.

    Restituisce WEEKS_RANGE lunedì consecutivi, a partire dal lunedì della
    settimana corrente.
    """
    today = datetime.now()
    this_monday = today - timedelta(days=today.weekday())
    return [this_monday + timedelta(weeks=i) for i in range(WEEKS_RANGE)]


def fetch_week(monday: datetime) -> bytes:
    date_str = monday.strftime("%d-%m-%Y")
    url = SOURCE_URL_TEMPLATE.format(date=date_str)
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    if not resp.content.strip().startswith(b"BEGIN:VCALENDAR"):
        raise RuntimeError(
            f"La risposta per la settimana del {date_str} non sembra un file "
            ".ics valido. Il link potrebbe essere scaduto o richiedere di "
            "nuovo il login."
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


def merge(existing_cal: Calendar, new_ics_bytes: bytes, events_by_uid: dict) -> None:
    """Aggiorna events_by_uid in place con gli eventi del nuovo ics (upsert)."""
    new_cal = Calendar.from_ical(new_ics_bytes)
    for component in new_cal.walk("VEVENT"):
        events_by_uid[str(component.get("UID"))] = component


def main() -> None:
    target_mondays = get_target_mondays()
    print(
        f"Ricontrollo {len(target_mondays)} settimane: "
        + ", ".join(m.strftime("%d-%m-%Y") for m in target_mondays)
    )

    existing_cal = load_existing(OUTPUT_PATH)

    events_by_uid = {}
    for component in existing_cal.walk("VEVENT"):
        events_by_uid[str(component.get("UID"))] = component

    for monday in target_mondays:
        print(f"Scarico la settimana che inizia il {monday.strftime('%d-%m-%Y')}")
        try:
            new_ics = fetch_week(monday)
        except Exception as exc:
            # Non blocchiamo le altre settimane se una singola fallisce
            # (es. UniPD non ha ancora pubblicato quella settimana).
            print(f"  Attenzione: impossibile scaricare questa settimana ({exc})")
            continue
        merge(existing_cal, new_ics, events_by_uid)

    merged_cal = Calendar()
    merged_cal.add("prodid", "-//OrariUniPD Auto Export//")
    merged_cal.add("version", "2.0")
    merged_cal.add("x-wr-timezone", "Europe/Rome")
    for comp in events_by_uid.values():
        merged_cal.add_component(comp)

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, "wb") as f:
        f.write(merged_cal.to_ical())

    total = len(merged_cal.walk("VEVENT"))
    print(f"Fatto: {total} eventi totali salvati in {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
