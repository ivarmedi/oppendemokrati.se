from urllib.parse import urlencode

from django import template
from django.urls import reverse

from riksdag.parties import party_color, party_name

register = template.Library()


@register.simple_tag(takes_context=True)
def ledamot_list_url(context, **overrides):
    params = {
        "q": context.get("q") or "",
        "parti": context.get("parti") or "",
        "sort": context.get("sort") or "namn",
        "dir": context.get("dir") or "asc",
        "view": context.get("view") or "kort",
    }
    params.update({key: value for key, value in overrides.items() if value is not None})
    if params.get("view") == "kort":
        params["view"] = ""
    query = urlencode({key: value for key, value in params.items() if value})
    url = reverse("ledamot_list")
    return f"{url}?{query}" if query else url


@register.simple_tag(takes_context=True)
def votering_list_url(context, **overrides):
    params = {
        "q": context.get("q") or "",
        "rm": context.get("rm") or "",
        "sort": context.get("sort") or "datum",
        "dir": context.get("dir") or "desc",
        "page": "",
    }
    params.update({key: value for key, value in overrides.items() if value is not None})
    query = urlencode({key: value for key, value in params.items() if value})
    url = reverse("votering_list")
    return f"{url}?{query}" if query else url


@register.filter
def parti_namn(code):
    return party_name(code)


@register.filter
def parti_farg(code):
    return party_color(code)


@register.filter
def pct(value):
    if value is None:
        return "–"
    return f"{value:.0f} %".replace(".", ",")


@register.filter
def rost_klass(value):
    mapping = {
        "Ja": "vote-yes",
        "Nej": "vote-no",
        "Avstår": "vote-abstain",
        "Frånvarande": "vote-absent",
    }
    return mapping.get(value, "")
