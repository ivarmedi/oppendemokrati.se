"""Load readable background for a votering from Riksdagen dokumentstatus."""

from __future__ import annotations

import html
import re

import httpx
from django.core.cache import cache

from .models import Betankande
from .sync import as_list

DOC_CACHE_SECONDS = 60 * 60 * 24
DOC_BASE = "https://data.riksdagen.se"


def bakgrund_for(votering):
    bet = None
    if votering.dok_id:
        bet = Betankande.objects.filter(pk=votering.dok_id).first()
    if bet is None:
        bet = Betankande.objects.filter(rm=votering.rm, beteckning=votering.beteckning).first()
    payload = fetch_dokumentstatus(bet.dok_id) if bet else None
    parsed = parse_dokumentstatus(payload, votering.punkt) if payload else {}
    if bet and not parsed.get("sammanfattning"):
        parsed["sammanfattning"] = bet.notis
    if bet:
        parsed.setdefault("dok_id", bet.dok_id)
        parsed.setdefault("titel", bet.titel or votering.titel)
    parsed.setdefault("dok_id", votering.dok_id)
    parsed.setdefault("titel", votering.titel)
    return parsed


def fetch_dokumentstatus(dok_id: str):
    if not dok_id:
        return None
    key = f"dokumentstatus:{dok_id.upper()}"
    cached = cache.get(key)
    if cached is not None:
        return cached or None
    try:
        with httpx.Client(timeout=20.0, follow_redirects=True) as client:
            response = client.get(f"{DOC_BASE}/dokumentstatus/{dok_id}.json")
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError):
        cache.set(key, {}, 60)
        return None
    cache.set(key, payload, DOC_CACHE_SECONDS)
    return payload


def parse_dokumentstatus(payload, punkt) -> dict:
    status = payload.get("dokumentstatus") or {}
    dokument = status.get("dokument") or {}
    uppgifter = {
        item.get("kod"): (item.get("text") or "").strip()
        for item in as_list((status.get("dokuppgift") or {}).get("uppgift"))
        if item.get("kod")
    }
    punkt_text = ""
    punkt_rubrik = ""
    motforslag_nummer = ""
    motforslag_partier = ""
    omrostning = ""
    for forslag in as_list((status.get("dokutskottsforslag") or {}).get("utskottsforslag")):
        if str(forslag.get("punkt") or "") != str(punkt):
            continue
        punkt_rubrik = tidy_prose(forslag.get("rubrik") or "")
        punkt_text = tidy_prose(forslag.get("forslag") or "")
        motforslag_nummer = str(forslag.get("motforslag_nummer") or "").strip()
        if motforslag_nummer in {"", "0"}:
            motforslag_nummer = ""
        motforslag_partier = format_parties(forslag.get("motforslag_partier") or "")
        omrostning = caption_text(forslag.get("votering_sammanfattning_html"))
        break
    related = []
    for ref in as_list((status.get("dokreferens") or {}).get("referens")):
        typ = (ref.get("ref_dok_typ") or "").lower()
        if typ not in {"prop", "mot"}:
            continue
        related.append(
            {
                "typ": typ,
                "typ_namn": "Proposition" if typ == "prop" else "Motion",
                "dok_id": ref.get("ref_dok_id") or "",
                "beteckning": ref.get("ref_dok_bet") or "",
                "rm": ref.get("ref_dok_rm") or "",
                "titel": tidy_prose(ref.get("ref_dok_titel") or ""),
                "undertitel": tidy_prose(ref.get("ref_dok_subtitel") or ""),
                "url": f"{DOC_BASE}/dokument/{ref.get('ref_dok_id')}.html" if ref.get("ref_dok_id") else "",
            }
        )
    related.sort(key=lambda item: (0 if item["typ"] == "prop" else 1, item["beteckning"]))
    pdf = ""
    for bilaga in as_list((status.get("dokbilaga") or {}).get("bilaga")):
        if (bilaga.get("filtyp") or "").lower() == "pdf" and bilaga.get("fil_url"):
            pdf = bilaga["fil_url"]
            break
    dok_id = dokument.get("dok_id") or ""
    return {
        "dok_id": dok_id,
        "titel": dokument.get("titel") or "",
        "sammanfattning": tidy_prose(uppgifter.get("notis") or uppgifter.get("utsknotis") or ""),
        "beslut": tidy_prose(uppgifter.get("rdbeslut") or ""),
        "utskottet": tidy_prose(uppgifter.get("beslutssammanfattningusk") or ""),
        "punkt_rubrik": punkt_rubrik,
        "punkt_text": punkt_text,
        "motforslag_nummer": motforslag_nummer,
        "motforslag_partier": motforslag_partier,
        "omrostning": omrostning,
        "related": related,
        "html_url": f"{DOC_BASE}/dokument/{dok_id}.html" if dok_id else "",
        "pdf_url": pdf,
    }


def format_parties(value: str) -> str:
    parts = [part.strip().strip('"') for part in (value or "").split(",") if part.strip().strip('"')]
    return ", ".join(parts)


def caption_text(payload) -> str:
    table = (payload or {}).get("table") if isinstance(payload, dict) else {}
    caption = (table or {}).get("caption") or ""
    if isinstance(caption, dict):
        return tidy_prose(caption.get("#text") or "")
    return tidy_prose(str(caption))


def collapse_space(text: str) -> str:
    return re.sub(r"[ \t]+", " ", (text or "").replace("\u00ad", "")).strip()


def tidy_prose(text: str) -> str:
    cleaned = html.unescape(html.unescape(text or ""))
    cleaned = re.sub(r"(?i)<br\s*/?>", "\n", cleaned)
    cleaned = re.sub(r"(?i)</p\s*>", "\n\n", cleaned)
    cleaned = re.sub(r"<[^>]+>", "", cleaned)
    cleaned = collapse_space(cleaned).replace(" \n", "\n")
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()
