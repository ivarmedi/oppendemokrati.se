from django.conf import settings
from django.core.paginator import Paginator
from django.db.models import Case, ExpressionWrapper, F, FloatField, IntegerField, Q, Value, When
from django.shortcuts import get_object_or_404, render
from django.views.decorators.cache import cache_page
from django.views.decorators.vary import vary_on_headers

from .calendar import fetch_upcoming, group_by_day
from .charts import ledamot_charts
from .documents import bakgrund_for
from .models import Ledamot, PartiLinje, Rost, Uppdrag, Votering
from .parties import PARTY_ORDER, PARTIES, has_party_line, party_name

LEDAMOT_SORTS = {
    "namn": {"label": "Namn", "default_dir": "asc"},
    "parti": {"label": "Parti", "default_dir": "asc"},
    "valkrets": {"label": "Valkrets", "default_dir": "asc"},
    "narvaro": {"label": "Närvaro", "default_dir": "desc"},
    "partilinje": {"label": "Partilinje", "default_dir": "desc"},
    "avvikelser": {"label": "Avvikelser", "default_dir": "desc"},
    "franvaro": {"label": "Frånvaro", "default_dir": "desc"},
    "fodd": {"label": "Födelseår", "default_dir": "desc"},
}

VOTERING_SORTS = {
    "datum": {"label": "Datum", "default_dir": "desc", "fields": ["datum", "beteckning", "punkt"]},
    "arende": {"label": "Ärende", "default_dir": "asc", "fields": ["beteckning", "punkt", "-datum"]},
    "titel": {"label": "Titel", "default_dir": "asc", "fields": ["titel", "beteckning"]},
    "ja": {"label": "Ja", "default_dir": "desc", "fields": ["ja", "-datum"]},
    "nej": {"label": "Nej", "default_dir": "desc", "fields": ["nej", "-datum"]},
    "avstar": {"label": "Avstår", "default_dir": "desc", "fields": ["avstar", "-datum"]},
    "franvarande": {"label": "Frånvarande", "default_dir": "desc", "fields": ["franvarande", "-datum"]},
}


def cached_page(view):
    return cache_page(settings.PAGE_CACHE_SECONDS)(vary_on_headers("HX-Request")(view))


def is_htmx(request):
    return request.headers.get("HX-Request") == "true"


def _party_filters():
    return [{"kod": kod, "namn": PARTIES[kod]["name"]} for kod in PARTY_ORDER if kod in PARTIES]


@cached_page
def ledamot_list(request):
    query = request.GET.get("q", "").strip()
    parti = request.GET.get("parti", "").strip()
    sort, direction = _ledamot_sort(request)
    view = request.GET.get("view", "").strip()
    if view not in ("kort", "tabell"):
        view = "kort"
    ledamoter = Ledamot.objects.filter(is_current=True)
    if not ledamoter.exists():
        ledamoter = Ledamot.objects.all()
    if parti:
        ledamoter = ledamoter.filter(parti=parti)
    if query:
        ledamoter = ledamoter.filter(
            Q(tilltalsnamn__icontains=query)
            | Q(efternamn__icontains=query)
            | Q(sorteringsnamn__icontains=query)
            | Q(valkrets__icontains=query)
        )
    ledamoter = _order_ledamoter(ledamoter, sort, direction)
    context = {
        "ledamoter": ledamoter,
        "q": query,
        "parti": parti,
        "sort": sort,
        "dir": direction,
        "view": view,
        "sorts": _sort_options(sort, direction, LEDAMOT_SORTS),
        "party_filters": _party_filters(),
        "antal": ledamoter.count(),
    }
    if is_htmx(request):
        return render(request, "riksdag/partials/ledamot_panel.html", context)
    return render(request, "riksdag/ledamot_list.html", context)


def _ledamot_sort(request):
    sort = request.GET.get("sort", "").strip()
    if sort not in LEDAMOT_SORTS:
        sort = "namn"
    direction = request.GET.get("dir", "").strip()
    if direction not in ("asc", "desc"):
        direction = LEDAMOT_SORTS[sort]["default_dir"]
    return sort, direction


def _sort_options(sort, direction, catalog):
    options = []
    for key, meta in catalog.items():
        if key == sort:
            next_dir = "asc" if direction == "desc" else "desc"
        else:
            next_dir = meta["default_dir"]
        options.append(
            {
                "key": key,
                "label": meta["label"],
                "active": key == sort,
                "next_dir": next_dir,
                "aria_sort": direction if key == sort else "none",
            }
        )
    return options


def _order_ledamoter(ledamoter, sort, direction):
    party_rank = Case(
        *[When(parti=kod, then=Value(index)) for index, kod in enumerate(PARTY_ORDER)],
        default=Value(len(PARTY_ORDER)),
        output_field=IntegerField(),
    )
    ledamoter = ledamoter.annotate(
        party_rank=party_rank,
        narvaro_sort=Case(
            When(antal_voteringar=0, then=Value(None)),
            default=ExpressionWrapper(
                100.0 * (F("antal_voteringar") - F("antal_franvarande")) / F("antal_voteringar"),
                output_field=FloatField(),
            ),
        ),
        franvaro_sort=Case(
            When(antal_voteringar=0, then=Value(None)),
            default=ExpressionWrapper(
                100.0 * F("antal_franvarande") / F("antal_voteringar"),
                output_field=FloatField(),
            ),
        ),
        partilinje_sort=Case(
            When(antal_med_partiet=0, antal_mot_partiet=0, then=Value(None)),
            default=ExpressionWrapper(
                100.0 * F("antal_med_partiet") / (F("antal_med_partiet") + F("antal_mot_partiet")),
                output_field=FloatField(),
            ),
        ),
    )
    fields = {
        "namn": ["sorteringsnamn"],
        "parti": ["party_rank", "sorteringsnamn"],
        "valkrets": ["valkrets", "sorteringsnamn"],
        "narvaro": ["narvaro_sort", "sorteringsnamn"],
        "partilinje": ["partilinje_sort", "sorteringsnamn"],
        "avvikelser": ["antal_mot_partiet", "sorteringsnamn"],
        "franvaro": ["franvaro_sort", "sorteringsnamn"],
        "fodd": ["fodd_ar", "sorteringsnamn"],
    }[sort]
    descending = direction == "desc"
    return ledamoter.order_by(
        *[F(field).desc(nulls_last=True) if descending else F(field).asc(nulls_last=True) for field in fields]
    )


@cached_page
def ledamot_detail(request, intressent_id):
    ledamot = get_object_or_404(Ledamot, pk=intressent_id)
    rost_filter = request.GET.get("filter", "").strip()
    query = request.GET.get("q", "").strip()
    roster = (
        Rost.objects.filter(intressent_id=ledamot.intressent_id)
        .select_related("votering")
        .order_by("-votering__datum", "votering__beteckning")
    )
    if rost_filter == "franvarande":
        roster = roster.filter(rost="Frånvarande")
    elif rost_filter == "mot":
        roster = roster.filter(med_partiet=False)
    elif rost_filter == "med":
        roster = roster.filter(med_partiet=True)
    if query:
        roster = roster.filter(
            Q(votering__titel__icontains=query)
            | Q(votering__beteckning__icontains=query)
            | Q(votering__rm__icontains=query)
        )
    uppdrag = Uppdrag.objects.filter(ledamot=ledamot, is_current=True)
    context = {
        "ledamot": ledamot,
        "roster": roster[:250],
        "roster_total": roster.count(),
        "uppdrag": uppdrag,
        "filter": rost_filter,
        "q": query,
    }
    if is_htmx(request):
        return render(request, "riksdag/partials/ledamot_votes.html", context)
    context["charts"] = ledamot_charts(ledamot)
    return render(request, "riksdag/ledamot_detail.html", context)


@cached_page
def votering_list(request):
    query = request.GET.get("q", "").strip()
    rm = request.GET.get("rm", "").strip()
    sort, direction = _votering_sort(request)
    voteringar = Votering.objects.all()
    rms = list(Votering.objects.order_by("-rm").values_list("rm", flat=True).distinct())
    if rm:
        voteringar = voteringar.filter(rm=rm)
    if query:
        voteringar = voteringar.filter(
            Q(titel__icontains=query) | Q(beteckning__icontains=query) | Q(dok_id__icontains=query)
        )
    voteringar = _order_voteringar(voteringar, sort, direction)
    page = Paginator(voteringar, 40).get_page(request.GET.get("page") or 1)
    context = {
        "page": page,
        "q": query,
        "rm": rm,
        "rms": rms,
        "sort": sort,
        "dir": direction,
        "sorts": _sort_options(sort, direction, VOTERING_SORTS),
    }
    if is_htmx(request):
        return render(request, "riksdag/partials/votering_panel.html", context)
    return render(request, "riksdag/votering_list.html", context)


def _votering_sort(request):
    sort = request.GET.get("sort", "").strip()
    if sort not in VOTERING_SORTS:
        sort = "datum"
    direction = request.GET.get("dir", "").strip()
    if direction not in ("asc", "desc"):
        direction = VOTERING_SORTS[sort]["default_dir"]
    return sort, direction


def _order_voteringar(voteringar, sort, direction):
    descending = direction == "desc"
    order = []
    for field in VOTERING_SORTS[sort]["fields"]:
        name = field.lstrip("-")
        field_desc = descending if not field.startswith("-") else not descending
        order.append(F(name).desc(nulls_last=True) if field_desc else F(name).asc(nulls_last=True))
    return voteringar.order_by(*order)


@cached_page
def kommande_list(request):
    events = fetch_upcoming()
    vote_events = [event for event in events if event.is_vote_related]
    other_events = [event for event in events if not event.is_vote_related]
    return render(
        request,
        "riksdag/kommande_list.html",
        {
            "vote_days": group_by_day(vote_events),
            "other_days": group_by_day(other_events),
            "nasta": events[0] if events else None,
            "antal_beslut": sum(1 for event in vote_events if event.kind == "beslut"),
            "antal_debatter": sum(1 for event in vote_events if event.kind == "debatt"),
        },
    )


@cached_page
def votering_detail(request, votering_id):
    votering = get_object_or_404(Votering, pk=votering_id)
    roster = votering.roster.select_related("ledamot").order_by("parti", "namn")
    linjer = {row.parti: row.linje for row in PartiLinje.objects.filter(votering=votering)}
    groups = []
    by_party = {}
    for rost in roster:
        by_party.setdefault(rost.parti, []).append(rost)
    for kod in PARTY_ORDER:
        if kod in by_party:
            groups.append(_party_group(kod, by_party.pop(kod), linjer.get(kod, "")))
    for kod, items in by_party.items():
        groups.append(_party_group(kod, items, linjer.get(kod, "")))
    return render(
        request,
        "riksdag/votering_detail.html",
        {"votering": votering, "groups": groups, "bakgrund": bakgrund_for(votering)},
    )


def _party_group(kod, items, linje):
    follows_line = has_party_line(kod)
    if not follows_line:
        linje = ""
    counts = {"Ja": 0, "Nej": 0, "Avstår": 0, "Frånvarande": 0}
    line_count = 0
    for item in items:
        counts[item.rost] = counts.get(item.rost, 0) + 1
        if linje and item.rost == linje:
            line_count += 1
    return {
        "kod": kod,
        "namn": party_name(kod),
        "linje": linje,
        "follows_line": follows_line,
        "roster": items,
        "counts": counts,
        "line_count": line_count,
    }
