"""Monthly attendance and party-line series for a ledamot."""

from __future__ import annotations

from django.db.models import Count, Q
from django.db.models.functions import TruncMonth

from .models import Rost

MONTHS = "jan feb mar apr maj jun jul aug sep okt nov dec".split()


def ledamot_charts(ledamot):
    rows = list(
        Rost.objects.filter(intressent_id=ledamot.intressent_id, votering__datum__isnull=False)
        .annotate(period=TruncMonth("votering__datum"))
        .values("period")
        .annotate(
            totalt=Count("id"),
            franvarande=Count("id", filter=Q(rost="Frånvarande")),
            med=Count("id", filter=Q(med_partiet=True)),
            mot=Count("id", filter=Q(med_partiet=False)),
        )
        .order_by("period")
    )
    max_mot = max((row["mot"] for row in rows), default=0)
    points = []
    prev_year = None
    for row in rows:
        period = row["period"]
        if period is None:
            continue
        totalt = row["totalt"]
        compared = row["med"] + row["mot"]
        present = totalt - row["franvarande"]
        year = period.year
        label = f"{MONTHS[period.month - 1]} {year}"
        narvaro = round(100 * present / totalt, 1) if totalt else None
        partilinje = round(100 * row["med"] / compared, 1) if compared else None
        mot = row["mot"]
        points.append(
            {
                "label": label,
                "year": year,
                "year_start": year != prev_year,
                "narvaro": narvaro,
                "narvaro_height": round(narvaro) if narvaro is not None else None,
                "narvaro_title": f"{label}: {_pct(narvaro)}",
                "partilinje": partilinje,
                "partilinje_height": round(partilinje) if partilinje is not None else None,
                "partilinje_title": f"{label}: {_pct(partilinje)}",
                "avvikelser": mot,
                "avvikelser_height": round(100 * mot / max_mot) if max_mot else 0,
                "avvikelser_title": f"{label}: {mot}",
            }
        )
        prev_year = year
    return {
        "points": points,
        "max_avvikelser": max_mot,
    }


def _pct(value):
    if value is None:
        return "–"
    return f"{value:.1f} %".replace(".", ",")
