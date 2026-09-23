#!/usr/bin/env python3
"""
check_cancelled.py

Verifica la corrispondenza tra l'Agenda Web di UniPD (piattaforma EasyStaff)
e il file .ics del calendario (docs/calendar.ics).

Rileva in particolare:
  - Lezioni contrassegnate come 'Annullato: 1' sul web ma ancora presenti come attive nell'ICS.
  - Lezioni presenti nell'ICS ma scomparse del tutto dall'Agenda Web.
  - Nuove lezioni presenti sul web ma non ancora sincronizzate nell'ICS.

Opzionalmente (con --fix) aggiorna il file .ics contrassegnando le lezioni annullate
con 'STATUS:CANCELLED' e prefisso '❌ [ANNULLATA]' (oppure rimuovendole con --action remove).
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from datetime import datetime

from unipd_agenda import (
    CANCELLED_SUMMARY_PREFIX,
    DEFAULT_WEB_URL,
    cell_is_cancelled,
    cell_matches_any_event,
    event_match_dict,
    event_matches_any_cell,
    extract_params_from_url,
    fetch_grid_cells,
    mark_component_cancelled,
    match_cell_to_ics,
    mondays_from,
    parse_flexible_date,
)


def parse_ics_events(file_path: str) -> list[dict]:
    """Legge un file .ics e restituisce un elenco di dizionari rappresentanti i VEVENT."""
    if not os.path.exists(file_path):
        return []

    try:
        from icalendar import Calendar

        with open(file_path, "rb") as f:
            cal = Calendar.from_ical(f.read())
        events = []
        for comp in cal.walk("VEVENT"):
            fields = event_match_dict(comp)
            dtstart = comp.get("DTSTART")
            events.append(
                {
                    **fields,
                    "status": str(comp.get("STATUS", "")),
                    "dtstart": dtstart.dt if dtstart else None,
                    "description": str(comp.get("DESCRIPTION", "")),
                    "location": str(comp.get("LOCATION", "")),
                    "_component": comp,
                    "_cal": cal,
                }
            )
        return events
    except ImportError:
        return _parse_ics_events_fallback(file_path)


def _parse_ics_events_fallback(file_path: str) -> list[dict]:
    events = []
    with open(file_path, encoding="utf-8", errors="ignore") as f:
        lines = f.readlines()
    curr = None
    for raw_line in lines:
        line = raw_line.rstrip("\r\n")
        if line == "BEGIN:VEVENT":
            curr = {}
        elif line == "END:VEVENT":
            if curr is not None:
                dtstart_raw = curr.get("DTSTART", "")
                curr["uid"] = curr.get("UID", "")
                curr["summary"] = curr.get("SUMMARY", "").replace(r"\,", ",")
                curr["status"] = curr.get("STATUS", "")
                curr["dtstart_str"] = dtstart_raw.replace("T", "")[:12]
                curr["description"] = curr.get("DESCRIPTION", "")
                curr["location"] = curr.get("LOCATION", "")
                events.append(curr)
            curr = None
        elif curr is not None:
            if line.startswith((" ", "\t")):
                if "_last_key" in curr:
                    curr[curr["_last_key"]] += line[1:]
            elif ":" in line:
                k, v = line.split(":", 1)
                k = k.split(";")[0]
                curr[k] = v
                curr["_last_key"] = k
    return events


def compare_schedules(grid_cells: list[dict], ics_events: list[dict]) -> dict:
    """Confronta le celle dell'agenda web con gli eventi dell'ICS."""
    cancelled_web = [c for c in grid_cells if cell_is_cancelled(c)]
    active_web = [c for c in grid_cells if not cell_is_cancelled(c)]

    cancelled_matches = []
    for cell in cancelled_web:
        matched = [e for e in ics_events if match_cell_to_ics(cell, e)]
        already_marked = bool(
            matched
            and (
                "ANNULLAT" in matched[0].get("summary", "").upper()
                or matched[0].get("status") == "CANCELLED"
            )
        )
        if already_marked:
            status_in_ics = "ALREADY_MARKED"
        elif matched:
            status_in_ics = "PRESENT_ACTIVE"
        else:
            status_in_ics = "NOT_IN_ICS"
        cancelled_matches.append(
            {"cell": cell, "matched_events": matched, "status_in_ics": status_in_ics}
        )

    missing_in_ics = [cell for cell in active_web if not cell_matches_any_event(cell, ics_events)]

    return {
        "total_web": len(grid_cells),
        "active_web": len(active_web),
        "cancelled_web": len(cancelled_web),
        "cancelled_details": cancelled_matches,
        "missing_in_ics": missing_in_ics,
    }


def apply_fix_to_ics(file_path: str, cancelled_cells: list[dict], action: str = "cancel") -> int:
    """Aggiorna il file .ics applicando l'azione scelta per le lezioni annullate."""
    if not os.path.exists(file_path):
        print(f"File {file_path} non trovato, impossibile applicare il fix.")
        return 0

    try:
        from icalendar import Calendar

        with open(file_path, "rb") as f:
            cal = Calendar.from_ical(f.read())

        new_cal = Calendar()
        for key in ("PRODID", "VERSION", "X-WR-TIMEZONE"):
            if cal.get(key) is not None:
                new_cal.add(key, cal.get(key))
        if new_cal.get("PRODID") is None:
            new_cal.add("prodid", "-//OrariUniPD Auto Export//")
        if new_cal.get("VERSION") is None:
            new_cal.add("version", "2.0")

        modified_count = 0
        for comp in cal.walk("VEVENT"):
            is_cancelled = event_matches_any_cell(event_match_dict(comp), cancelled_cells)
            if is_cancelled:
                modified_count += 1
                if action == "remove":
                    continue
                mark_component_cancelled(comp)
            new_cal.add_component(comp)

        with open(file_path, "wb") as f:
            f.write(new_cal.to_ical())
        return modified_count

    except ImportError:
        return _apply_fix_fallback(file_path, cancelled_cells, action)


def _apply_fix_fallback(file_path: str, cancelled_cells: list[dict], action: str) -> int:
    with open(file_path, encoding="utf-8", errors="ignore") as f:
        content = f.read()

    raw_events = re.findall(r"BEGIN:VEVENT.*?END:VEVENT", content, re.DOTALL)
    modified_count = 0
    new_content = content

    for raw in raw_events:
        uid_m = re.search(r"UID:(.*?)\r?\n", raw)
        uid = uid_m.group(1).strip() if uid_m else ""
        dt_m = re.search(r"DTSTART(?:;[^:]*)?:(.*?)\r?\n", raw)
        dt_str = dt_m.group(1).replace("T", "")[:12] if dt_m else ""
        summary_m = re.search(r"SUMMARY:(.*?)\r?\n", raw)
        summary = summary_m.group(1).strip() if summary_m else ""

        event_dict = {"uid": uid, "summary": summary, "dtstart_str": dt_str}
        if not event_matches_any_cell(event_dict, cancelled_cells):
            continue

        modified_count += 1
        if action == "remove":
            new_content = new_content.replace(raw + "\n", "").replace(raw, "")
            continue

        updated = raw
        if "STATUS:" in updated:
            updated = re.sub(r"STATUS:[^\r\n]+", "STATUS:CANCELLED", updated)
        else:
            updated = updated.replace("END:VEVENT", "STATUS:CANCELLED\nEND:VEVENT")
        if CANCELLED_SUMMARY_PREFIX not in updated:
            updated = updated.replace(
                f"SUMMARY:{summary}", f"SUMMARY:{CANCELLED_SUMMARY_PREFIX} {summary}"
            )
        new_content = new_content.replace(raw, updated)

    with open(file_path, "w", encoding="utf-8") as f:
        f.write(new_content)
    return modified_count


def _ics_status_icon(status_label: str) -> str:
    if status_label == "PRESENT_ACTIVE":
        return "❌ ATTIVA NEL CALENDARIO (NON ANNULLATA!)"
    if status_label == "ALREADY_MARKED":
        return "✔️  Già contrassegnata come annullata nel calendario"
    return "ℹ️  Non presente nel calendario"


def main():
    parser = argparse.ArgumentParser(
        description="Verifica lezioni annullate confrontando Agenda Web UniPD e calendar.ics"
    )
    parser.add_argument("--url", default=DEFAULT_WEB_URL, help="URL della pagina EasyCourse UniPD")
    parser.add_argument(
        "--date",
        default=None,
        help="Data di inizio analisi (formato YYYY-MM-DD o DD-MM-YYYY). Default: lunedì corrente.",
    )
    parser.add_argument(
        "--weeks",
        type=int,
        default=3,
        help="Numero di settimane consecutive da verificare (default: 3)",
    )
    parser.add_argument(
        "--ics",
        default="docs/calendar.ics",
        help="Percorso del file .ics locale (default: docs/calendar.ics)",
    )
    parser.add_argument(
        "--fix",
        action="store_true",
        help="Aggiorna automaticamente il file .ics gestendo le lezioni annullate",
    )
    parser.add_argument(
        "--action",
        choices=["cancel", "remove"],
        default="cancel",
        help="Azione per le lezioni annullate con --fix: 'cancel' (marca ANNULLATA e STATUS:CANCELLED) oppure 'remove' (elimina)",
    )
    args = parser.parse_args()

    if args.date:
        try:
            start_date = parse_flexible_date(args.date)
        except ValueError as exc:
            print(f"Errore: {exc}")
            sys.exit(1)
    else:
        start_date = datetime.now()

    target_mondays = mondays_from(start_date, args.weeks)

    print("=" * 70)
    print("🔍 VERIFICA LEZIONI ANNULLATE — UniPD Agenda Web ⟷ calendar.ics")
    print("=" * 70)
    print(f"Settimane da verificare : {args.weeks} a partire dal {target_mondays[0].strftime('%d-%m-%Y')}")
    print(f"File calendario         : {args.ics}")
    print(f"Azione in caso di fix   : {args.action}")
    print("-" * 70)

    base_params = extract_params_from_url(args.url)
    ics_events = parse_ics_events(args.ics)
    print(f"Eventi caricati da {args.ics}: {len(ics_events)}")

    all_grid_cells: list[dict] = []
    all_cancelled_cells: list[dict] = []

    for monday in target_mondays:
        date_str = monday.strftime("%d-%m-%Y")
        try:
            cells = fetch_grid_cells(date_str, base_params)
            all_grid_cells.extend(cells)
            cancelled = [c for c in cells if cell_is_cancelled(c)]
            all_cancelled_cells.extend(cancelled)
            print(f"  • Settimana {date_str}: {len(cells)} lezioni sul web ({len(cancelled)} annullate)")
        except Exception as exc:
            print(f"  • Settimana {date_str}: ⚠️ Errore nel download ({exc})")

    report = compare_schedules(all_grid_cells, ics_events)

    print("\n" + "=" * 70)
    print("📊 RIEPILOGO CONFRONTO")
    print("=" * 70)
    print(f"Totale lezioni su Agenda Web : {report['total_web']}")
    print(f"Lezioni confermate (attive)   : {report['active_web']}")
    print(f"Lezioni ANNULLATE sul Web    : {report['cancelled_web']}")

    if report["cancelled_web"] > 0:
        print("\n⚠️  DETTAGLIO LEZIONI ANNULLATE:")
        print("-" * 70)
        for item in report["cancelled_details"]:
            c = item["cell"]
            docenti = c.get("docente") or "Non specificato"
            print(f"• Data & Ora : {c.get('data')} {c.get('ora_inizio')}-{c.get('ora_fine')}")
            print(f"  Materia    : {c.get('nome_insegnamento')}")
            print(f"  Aula       : {c.get('aula')}")
            print(f"  Docente/i  : {docenti}")
            print(f"  Stato .ics : {_ics_status_icon(item['status_in_ics'])}")
            print()
    else:
        print("\n✅ Nessuna lezione risulta annullata per le settimane analizzate.")

    if report["missing_in_ics"]:
        print(f"\nℹ️  Ci sono {len(report['missing_in_ics'])} lezioni attive sul web non presenti nell'ICS.")

    if args.fix:
        if not all_cancelled_cells:
            print("Nessuna lezione annullata da correggere.")
        else:
            print("\n" + "=" * 70)
            print(f"🛠️  APPLICAZIONE CORREZIONI ({args.action.upper()}) IN CORSO...")
            print("=" * 70)
            count = apply_fix_to_ics(args.ics, all_cancelled_cells, action=args.action)
            print(f"✅ Aggiornate {count} lezioni nel file {args.ics}.")
            print("Le modifiche saranno visibili su Apple Calendar al prossimo aggiornamento della sottoscrizione.")
    else:
        pending_fix = sum(
            1 for item in report["cancelled_details"] if item["status_in_ics"] == "PRESENT_ACTIVE"
        )
        if pending_fix > 0:
            print("\n💡 Suggerimento:")
            print(f"   Ci sono {pending_fix} lezioni annullate che compaiono ancora come attive nel tuo calendario.")
            print(f"   Esegui:  python3 check_cancelled.py --fix --action {args.action}")
            print("   per aggiornare il file docs/calendar.ics.")

    print("=" * 70)


if __name__ == "__main__":
    main()
