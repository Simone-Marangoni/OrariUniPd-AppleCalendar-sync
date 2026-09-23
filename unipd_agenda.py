"""Funzioni condivise per Agenda Web UniPD (EasyStaff) e file .ics."""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from datetime import datetime, timedelta

# URL della pagina EasyCourse (corso/canale/anno). La data viene sovrascritta a runtime.
DEFAULT_WEB_URL = (
    "https://agendastudentiunipd.easystaff.it/index.php?view=easycourse&form-type=corso&include=corso"
    "&txtcurr=1+-+GENERALE+%28canale+1%29&anno=2026&scuola=ScuoladiIngegneria&corso=IN2912"
    "&anno2%5B%5D=001PD_C1%7C1&date=2026-09-28&periodo_didattico=&_lang=it&list=&week_grid_type=-1"
    "&ar_codes_=&ar_select_=&col_cells=0&empty_box=0&only_grid=0&highlighted_date=0&all_events=0&faculty_group=0#"
)

# URL copiato dal pulsante di export iCal. La parte "date={date}" è sostituita a runtime (DD-MM-YYYY).
SOURCE_URL_TEMPLATE = (
    "https://agendastudentiunipd.easystaff.it/export/ec_download_ical_grid.php?"
    "view=easycourse&form-type=corso&include=corso&txtcurr=1+-+GENERALE+%28canale+1%29"
    "&anno=2026&scuola=ScuoladiIngegneria&corso=IN2912&anno2%5B%5D=001PD_C1%7C1"
    "&date={date}&periodo_didattico=&_lang=it&list=&week_grid_type=-1&ar_codes_="
    "&ar_select_=&col_cells=0&empty_box=0&only_grid=0&highlighted_date=0&all_events=0"
    "&faculty_group=0&ar_codes_=EC957274|EC957283|EC151723|EC151736"
    "&ar_select_=true|true|true|true&txtaa=2026/2027"
    "&txtcorso=IN2912%20-%20INGEGNERIA%20INFORMATICA%20(Laurea)"
    "&txtanno=&docente=&attivita=&txtdocente=&txtattivita="
)

GRID_ENDPOINT = "https://agendastudentiunipd.easystaff.it/grid_call.php"
HTTP_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; UniPdSyncBot/1.0)"}

CANCELLED_SUMMARY_PREFIX = "❌ [ANNULLATA]"
CANCELLED_DESCRIPTION_NOTE = "[ATTENZIONE: Lezione ANNULLATA su Agenda Web UniPD]"


def monday_of(day: datetime) -> datetime:
    return day - timedelta(days=day.weekday())


def mondays_from(start: datetime, weeks: int) -> list[datetime]:
    monday = monday_of(start)
    return [monday + timedelta(weeks=i) for i in range(weeks)]


def parse_flexible_date(value: str) -> datetime:
    for fmt in ("%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    raise ValueError(f"formato data non valido '{value}'. Usa YYYY-MM-DD o DD-MM-YYYY.")


def extract_params_from_url(url: str) -> dict:
    """Estrae i parametri GET dall'URL dell'agenda per usarli nella richiesta POST a grid_call.php."""
    parsed = urllib.parse.urlparse(url)
    qs = urllib.parse.parse_qs(parsed.query)
    return {k: (v[0] if len(v) == 1 else v) for k, v in qs.items()}


def _urlopen(req: urllib.request.Request, timeout: int = 30):
    return urllib.request.urlopen(req, timeout=timeout)


def fetch_grid_cells(date_str: str, base_params: dict) -> list[dict]:
    """Interroga grid_call.php per la settimana contenente la data indicata (DD-MM-YYYY o YYYY-MM-DD)."""
    params = dict(base_params)
    params["date"] = date_str
    post_data = urllib.parse.urlencode(params, doseq=True).encode("utf-8")
    req = urllib.request.Request(GRID_ENDPOINT, data=post_data, headers=HTTP_HEADERS)
    with _urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode("utf-8", errors="ignore"))
        return data.get("celle", [])


def fetch_week_ics(monday: datetime, url_template: str = SOURCE_URL_TEMPLATE) -> bytes:
    date_str = monday.strftime("%d-%m-%Y")
    url = url_template.format(date=date_str)
    req = urllib.request.Request(url, headers=HTTP_HEADERS)
    with _urlopen(req, timeout=30) as resp:
        content = resp.read()
    if not content.strip().startswith(b"BEGIN:VCALENDAR"):
        raise RuntimeError(
            f"La risposta per la settimana del {date_str} non sembra un file "
            ".ics valido. Il link potrebbe essere scaduto o richiedere di "
            "nuovo il login."
        )
    return content


def cell_is_cancelled(cell: dict) -> bool:
    return cell.get("Annullato") in (1, "1", True)


def dtstart_str_from_value(dtstart) -> str:
    if dtstart is None:
        return ""
    dt = dtstart.dt if hasattr(dtstart, "dt") else dtstart
    if hasattr(dt, "strftime"):
        return dt.strftime("%Y%m%d%H%M")
    return str(dt).replace("T", "")[:12]


def event_match_dict(component) -> dict:
    return {
        "uid": str(component.get("UID", "")),
        "summary": str(component.get("SUMMARY", "")),
        "dtstart_str": dtstart_str_from_value(component.get("DTSTART")),
    }


def _cell_dtstart_key(cell: dict) -> str:
    cell_date = cell.get("data", "")
    cell_time = cell.get("ora_inizio", "")
    if not cell_date or not cell_time:
        return ""
    parts = cell_date.split("-")
    if len(parts) != 3:
        return ""
    time_part = cell_time.replace(":", "")
    if len(parts[0]) == 4:
        return f"{parts[0]}{parts[1]}{parts[2]}{time_part}"
    return f"{parts[2]}{parts[1]}{parts[0]}{time_part}"


def match_cell_to_ics(cell: dict, ics_event: dict) -> bool:
    """Verifica se una cella di grid_call.php corrisponde a un evento dell'ICS."""
    uid = ics_event.get("uid", "")
    ts = str(cell.get("timestamp", ""))

    if ts and uid.startswith(ts):
        return True

    expected = _cell_dtstart_key(cell)
    if expected and ics_event.get("dtstart_str", "").startswith(expected):
        nome = cell.get("nome_insegnamento", "").lower()
        summary = ics_event.get("summary", "").lower()
        if nome and (nome in summary or summary in nome):
            return True

    return False


def event_matches_any_cell(event: dict, cells: list[dict]) -> bool:
    return any(match_cell_to_ics(cell, event) for cell in cells)


def cell_matches_any_event(cell: dict, events: list[dict]) -> bool:
    return any(match_cell_to_ics(cell, event) for event in events)


def is_component_cancelled(component) -> bool:
    status = str(component.get("STATUS", "")).upper()
    summary = str(component.get("SUMMARY", ""))
    return status == "CANCELLED" or summary.startswith(CANCELLED_SUMMARY_PREFIX)


def mark_component_cancelled(component) -> None:
    component["STATUS"] = "CANCELLED"
    summary = str(component.get("SUMMARY", ""))
    if not summary.startswith(CANCELLED_SUMMARY_PREFIX):
        component["SUMMARY"] = f"{CANCELLED_SUMMARY_PREFIX} {summary}"
    desc = str(component.get("DESCRIPTION", ""))
    if "ANNULLATA" not in desc:
        prefix = f"{CANCELLED_DESCRIPTION_NOTE}\n" if desc else CANCELLED_DESCRIPTION_NOTE
        component["DESCRIPTION"] = f"{prefix}{desc}"
