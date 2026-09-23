"""
Utility per riformattare gli eventi grezzi di UniPD in un formato più
ordinato su Calendario Apple.

Il file .ics di UniPD non separa i dati in campi distinti: tutto è
appiccicato in un unico SUMMARY, tipo:

    "FONDAMENTI DI INFORMATICA (A) PIZZI CINZIA, TREVISAN LUCA H11 [HUB] Lezione"

Questo modulo prova a scomporlo in: materia, docente/i, aula, edificio,
tipo attività — e li ridistribuisce così:
  - SUMMARY (titolo, visibile subito)  -> materia + aula
  - LOCATION (tappabile per Mappe)      -> aula, edificio, Padova
  - DESCRIPTION (visibile solo aprendo) -> docente/i, tipo attività, testo
                                            originale come riferimento

Il parsing si basa su un'euristica sul formato osservato (non documentato
ufficialmente da UniPD), quindi non è garantito al 100%: se il testo non
combacia con lo schema atteso, l'evento viene lasciato invariato invece di
essere scomposto in modo sbagliato.
"""

import re

ACTIVITY_TYPES = ["Lezione", "Esercitazione", "Laboratorio", "Esame", "Ricevimento", "Altro"]
_ACTIVITY_PATTERN = "|".join(ACTIVITY_TYPES)

_SUMMARY_RE = re.compile(
    r"^(?P<materia>.*?)\s+"
    r"(?:(?P<docenti>[A-ZÀ-Ý]+(?:\s[A-ZÀ-Ý]+)+(?:,\s*[A-ZÀ-Ý]+(?:\s[A-ZÀ-Ý]+)+)*)\s+)?"
    r"(?P<aula>\S+(?:\s\d+)?)\s+"
    r"\[(?P<edificio>[^\]]+)\]\s*"
    r"(?P<attivita>(?i:" + _ACTIVITY_PATTERN + r"))?\s*$"
)


_CANCELLED_PREFIX = "❌ [ANNULLATA]"


def parse_raw_summary(raw_summary: str):
    """Prova a scomporre il SUMMARY grezzo. Ritorna un dict di campi, oppure
    None se il formato non è riconosciuto (fallback: nessuna modifica)."""
    text = raw_summary.strip()
    if text.startswith(_CANCELLED_PREFIX):
        text = text[len(_CANCELLED_PREFIX) :].strip()
    match = _SUMMARY_RE.match(text)
    if not match:
        return None
    data = match.groupdict()
    if not data.get("materia") or not data.get("aula") or not data.get("edificio"):
        return None
    return {
        "materia": data["materia"].strip(),
        "docenti": (data.get("docenti") or "").strip() or None,
        "aula": data["aula"].strip(),
        "edificio": data["edificio"].strip(),
        "attivita": (data.get("attivita") or "").strip() or None,
    }


def restructure_event(component) -> None:
    """Modifica in place SUMMARY/LOCATION/DESCRIPTION del VEVENT per una
    visualizzazione più ordinata su Calendario Apple. Non fa nulla se il
    formato del SUMMARY non viene riconosciuto."""
    raw_summary = str(component.get("SUMMARY", ""))
    was_cancelled = raw_summary.startswith(_CANCELLED_PREFIX)
    parsed = parse_raw_summary(raw_summary)
    if parsed is None:
        return

    title = parsed["materia"]
    if parsed["aula"]:
        title += f" – {parsed['aula']}"

    location_bits = [b for b in [parsed["aula"], parsed["edificio"]] if b]
    location = (", ".join(location_bits) + ", Padova, Italia") if location_bits else "Padova, Italia"

    note_lines = []
    if parsed["docenti"]:
        note_lines.append(f"Docente/i: {parsed['docenti']}")
    if parsed["attivita"]:
        note_lines.append(f"Tipo: {parsed['attivita']}")
    note_lines.append(f"Originale: {raw_summary}")

    if was_cancelled:
        title = f"{_CANCELLED_PREFIX} {title}"

    component["SUMMARY"] = title
    component["LOCATION"] = location
    component["DESCRIPTION"] = "\n".join(note_lines)
