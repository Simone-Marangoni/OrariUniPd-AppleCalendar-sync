"""
Scarica dall'Agenda Web di UniPD gli orari di un intervallo di settimane
(da questa settimana fino a WEEKS_RANGE settimane nel futuro) e li unisce a
un file .ics cumulativo (docs/calendar.ics) che puoi pubblicare con GitHub
Pages e sottoscrivere una sola volta su Calendario Apple (o Google Calendar).

Ogni settimana viene ri-scaricata e confrontata quotidianamente con l'Agenda Web:
- Rileva eventuali variazioni di aula/orario/docente (upsert per UID).
- Interroga l'API della griglia web (grid_call.php) per verificare lo stato
  effettivo di ciascuna lezione (Annullato: 0 oppure 1).
- Gestisce le lezioni annullate secondo CANCELLED_ACTION:
    * "cancel": contrassegna l'evento con STATUS:CANCELLED e "❌ [ANNULLATA]" nel titolo,
                così da renderlo visibile su Apple Calendar.
    * "remove": rimuove completamente l'evento dal calendario.
- Rimuove eventuali lezioni eliminate del tutto dall'orario nella finestra controllata.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta

from icalendar import Calendar

from event_formatting import restructure_event
from unipd_agenda import (
    DEFAULT_WEB_URL,
    SOURCE_URL_TEMPLATE,
    cell_is_cancelled,
    event_match_dict,
    event_matches_any_cell,
    extract_params_from_url,
    fetch_grid_cells,
    fetch_week_ics,
    is_component_cancelled,
    mark_component_cancelled,
    mondays_from,
)

# ---------------------------------------------------------------------------
# CONFIGURAZIONE
# ---------------------------------------------------------------------------

AGENDA_WEB_URL = DEFAULT_WEB_URL

# Quante settimane totali coprire ogni giorno, a partire da questa settimana
# (settimana corrente inclusa). Con WEEKS_RANGE = 3: questa settimana + le
# prossime 2 vengono ri-scaricate e ri-controllate ogni giorno.
WEEKS_RANGE = 3

# Dove viene scritto il calendario cumulativo (servito da GitHub Pages se
# messo dentro /docs).
OUTPUT_PATH = "docs/calendar.ics"

# Gestione delle lezioni annullate su Apple Calendar:
# - "cancel": Mantiene la lezione con STATUS:CANCELLED e prefisso "❌ [ANNULLATA]"
# - "remove": Rimuove la lezione dal calendario
CANCELLED_ACTION = "cancel"

# Se True, riorganizza titolo, aula e note in formato ordinato per Apple Calendar
RESTRUCTURE_EVENTS = True

# ---------------------------------------------------------------------------


def load_existing(path: str) -> Calendar:
    if os.path.exists(path):
        with open(path, "rb") as f:
            return Calendar.from_ical(f.read())
    cal = Calendar()
    cal.add("prodid", "-//OrariUniPD Auto Export//")
    cal.add("version", "2.0")
    return cal


def merge_week_events(
    new_ics_bytes: bytes,
    events_by_uid: dict,
    cancelled_cells: list[dict],
    seen_uids_in_window: set,
    action: str = CANCELLED_ACTION,
    restructure: bool = RESTRUCTURE_EVENTS,
    grid_ok: bool = True,
) -> tuple[int, int]:
    """Processa gli eventi scaricati per la settimana, applica formattazione e cancellazioni."""
    new_cal = Calendar.from_ical(new_ics_bytes)
    added_or_updated = 0
    cancelled_count = 0

    for component in new_cal.walk("VEVENT"):
        uid = str(component.get("UID"))
        seen_uids_in_window.add(uid)

        if restructure:
            restructure_event(component)

        is_cancelled = False
        if grid_ok:
            is_cancelled = event_matches_any_cell(event_match_dict(component), cancelled_cells)
        else:
            existing = events_by_uid.get(uid)
            is_cancelled = existing is not None and is_component_cancelled(existing)

        if is_cancelled:
            cancelled_count += 1
            if action == "remove":
                events_by_uid.pop(uid, None)
                continue
            mark_component_cancelled(component)

        events_by_uid[uid] = component
        added_or_updated += 1

    return added_or_updated, cancelled_count


def prune_orphans(
    events_by_uid: dict,
    seen_uids: set,
    fetched_ranges: list[tuple],
) -> int:
    """Rimuove eventi della sola finestra effettivamente scaricata, non più presenti su UniPD."""
    pruned = 0
    for uid, comp in list(events_by_uid.items()):
        if uid in seen_uids:
            continue
        dtstart = comp.get("DTSTART")
        if not dtstart or not hasattr(dtstart.dt, "date"):
            continue
        ev_date = dtstart.dt.date()
        if any(start <= ev_date < end for start, end in fetched_ranges):
            del events_by_uid[uid]
            pruned += 1
    return pruned


def write_calendar(events_by_uid: dict, path: str) -> Calendar:
    merged_cal = Calendar()
    merged_cal.add("prodid", "-//OrariUniPD Auto Export//")
    merged_cal.add("version", "2.0")
    merged_cal.add("x-wr-timezone", "Europe/Rome")
    for comp in events_by_uid.values():
        merged_cal.add_component(comp)

    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "wb") as f:
        f.write(merged_cal.to_ical())
    return merged_cal


def main() -> None:
    today = datetime.now()
    target_mondays = mondays_from(today, WEEKS_RANGE)
    window_start = target_mondays[0].date()
    window_end = (target_mondays[-1] + timedelta(days=7)).date()

    print(
        f"Ricontrollo {len(target_mondays)} settimane (dal {window_start:%d-%m-%Y} al {window_end:%d-%m-%Y}): "
        + ", ".join(m.strftime("%d-%m-%Y") for m in target_mondays)
    )
    print(f"Modalità gestione lezioni annullate: {CANCELLED_ACTION}")

    web_params = extract_params_from_url(AGENDA_WEB_URL)
    existing_cal = load_existing(OUTPUT_PATH)

    events_by_uid = {
        str(component.get("UID")): component for component in existing_cal.walk("VEVENT")
    }

    seen_uids_in_window: set[str] = set()
    fetched_ranges: list[tuple] = []
    total_cancelled = 0

    for monday in target_mondays:
        date_str = monday.strftime("%d-%m-%Y")
        print(f"\nElaboro la settimana del {date_str}:")

        cancelled_cells: list[dict] = []
        grid_ok = False
        try:
            cells = fetch_grid_cells(date_str, web_params)
            cancelled_cells = [c for c in cells if cell_is_cancelled(c)]
            grid_ok = True
            if cancelled_cells:
                print(f"  • Rilevate {len(cancelled_cells)} lezioni ANNULLATE sull'Agenda Web")
                for c in cancelled_cells:
                    print(
                        f"    - {c.get('data')} {c.get('ora_inizio')}: "
                        f"{c.get('nome_insegnamento')} ({c.get('aula')})"
                    )
            else:
                print("  • Nessuna lezione annullata rilevata sull'Agenda Web")
        except Exception as exc:
            print(f"  ⚠️  Impossibile verificare l'Agenda Web per questa settimana ({exc})")
            print("     Conservo lo stato di cancellazione già presente nel calendario.")

        try:
            new_ics = fetch_week_ics(monday, SOURCE_URL_TEMPLATE)
        except Exception as exc:
            print(f"  ⚠️  Impossibile scaricare l'export .ics per questa settimana ({exc})")
            continue

        added, cancelled = merge_week_events(
            new_ics,
            events_by_uid,
            cancelled_cells,
            seen_uids_in_window,
            action=CANCELLED_ACTION,
            restructure=RESTRUCTURE_EVENTS,
            grid_ok=grid_ok,
        )
        fetched_ranges.append((monday.date(), (monday + timedelta(days=7)).date()))
        total_cancelled += cancelled
        print(f"  • {added} eventi elaborati/salvati ({cancelled} marcati come annullati)")

    pruned = prune_orphans(events_by_uid, seen_uids_in_window, fetched_ranges)
    if pruned > 0:
        print(f"\nRimossi {pruned} eventi orfani non più presenti nell'orario UniPD.")

    merged_cal = write_calendar(events_by_uid, OUTPUT_PATH)
    total = len(merged_cal.walk("VEVENT"))
    print(f"\nFatto: {total} eventi totali salvati in {OUTPUT_PATH}")
    print(f"Lezioni annullate gestite con successo: {total_cancelled}")


if __name__ == "__main__":
    main()
