"""Upcoming chamber decisions from Riksdagen's calendar API."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone

from .models import Betankande, Votering
from .sync import as_list

CALENDAR_URL = "https://data.riksdagen.se/kalender/"
CALENDAR_CACHE_SECONDS = 15 * 60
DOC_BASE = "https://data.riksdagen.se"
STOCKHOLM = ZoneInfo("Europe/Stockholm")

DOC_LINE = re.compile(
    r"(?P<rm>\d{4}/\d{2}):(?P<bet>[A-Za-zÅÄÖåäö]+\d+)\s+(?P<titel>.+)"
)
DOK_IDS = re.compile(r"dok_id\{([^}]+)\}", re.I)

VOTE_KINDS = frozenset({"beslut", "debatt", "bordlaggning"})
SKIP_SUMMARY = re.compile(r"teckenspråk|opening of the", re.I)


@dataclass
class UpcomingDoc:
    rm: str
    beteckning: str
    titel: str
    dok_id: str = ""
    url: str = ""
    votering_url: str = ""


@dataclass
class UpcomingEvent:
    uid: str
    starts_at: datetime
    ends_at: datetime | None
    summary: str
    kind: str
    status: str = ""
    documents: list[UpcomingDoc] = field(default_factory=list)

    @property
    def kind_label(self):
        return {
            "beslut": "Beslut",
            "debatt": "Debatt",
            "bordlaggning": "Bordläggning",
            "annat": self.summary,
        }.get(self.kind, self.summary)

    @property
    def is_vote_related(self):
        return self.kind in VOTE_KINDS


def fetch_upcoming():
    payload = fetch_calendar()
    events = parse_calendar(payload)
    today = timezone.now().astimezone(STOCKHOLM).date()
    upcoming = [
        event
        for event in events
        if event.starts_at.date() >= today and not SKIP_SUMMARY.search(event.summary)
    ]
    upcoming.sort(key=lambda event: (event.starts_at, event.summary))
    return enrich(upcoming)


def fetch_calendar():
    cached = cache.get("kalender:kamm")
    if cached is not None:
        return cached
    try:
        with httpx.Client(timeout=20.0, follow_redirects=True) as client:
            response = client.get(CALENDAR_URL, params={"org": "kamm", "utformat": "json"})
            response.raise_for_status()
            payload = response.json()
    except (httpx.HTTPError, ValueError):
        cache.set("kalender:kamm", {}, 60)
        return {}
    cache.set("kalender:kamm", payload, CALENDAR_CACHE_SECONDS)
    return payload


def parse_calendar(payload) -> list[UpcomingEvent]:
    events = []
    raw = as_list((payload.get("kalenderlista") or {}).get("kalender"))
    for item in raw:
        starts = parse_dt(item.get("DTSTART"))
        if starts is None:
            continue
        summary = unescape_ical(item.get("SUMMARY") or "").strip() or "Händelse"
        status, body = description_parts(item.get("DESCRIPTION"))
        if not status:
            status = unescape_ical(item.get("XRDDTSTARTSTATUS") or "").strip()
        events.append(
            UpcomingEvent(
                uid=item.get("UID") or item.get("XRDDOKID") or "",
                starts_at=starts,
                ends_at=parse_dt(item.get("DTEND")),
                summary=summary,
                kind=classify(summary, item.get("CATEGORIES") or ""),
                status=status,
                documents=parse_documents(body, item.get("XRDDATA") or "", item.get("XRDRM") or ""),
            )
        )
    return events


def classify(summary: str, categories: str) -> str:
    text = f"{summary} {categories}".lower()
    if "votering" in text or summary == "Beslut":
        return "beslut"
    if summary.startswith("Bordläggning") or "bordläggning" in text:
        return "bordlaggning"
    if summary == "Debatt om förslag" or "arbetsplenum" in text:
        return "debatt"
    return "annat"


def parse_documents(body: str, xrddata: str, rm: str) -> list[UpcomingDoc]:
    dok_ids = []
    match = DOK_IDS.search(xrddata or "")
    if match:
        dok_ids = [part.strip() for part in match.group(1).split(",") if part.strip()]
    docs = []
    for line in (body or "").splitlines():
        parsed = DOC_LINE.search(line.strip())
        if not parsed:
            continue
        beteckning = parsed.group("bet")
        dok_id = next((item for item in dok_ids if beteckning.lower() in item.lower()), "")
        docs.append(
            UpcomingDoc(
                rm=parsed.group("rm"),
                beteckning=beteckning,
                titel=parsed.group("titel").strip(),
                dok_id=dok_id,
                url=f"{DOC_BASE}/dokument/{dok_id}.html" if dok_id else "",
            )
        )
    if docs:
        return docs
    return [
        UpcomingDoc(rm=rm, beteckning="", titel="", dok_id=dok_id, url=f"{DOC_BASE}/dokument/{dok_id}.html")
        for dok_id in dok_ids
    ]


def enrich(events: list[UpcomingEvent]) -> list[UpcomingEvent]:
    keys = {(doc.rm, doc.beteckning) for event in events for doc in event.documents if doc.beteckning}
    if not keys:
        return events
    rms = {rm for rm, _ in keys}
    bets = {
        (row.rm, row.beteckning): row
        for row in Betankande.objects.filter(rm__in=rms)
        if (row.rm, row.beteckning) in keys
    }
    votes: dict[tuple[str, str], Votering] = {}
    for row in Votering.objects.filter(rm__in=rms).order_by("punkt"):
        key = (row.rm, row.beteckning)
        if key in keys and key not in votes:
            votes[key] = row
    for event in events:
        for doc in event.documents:
            bet = bets.get((doc.rm, doc.beteckning))
            if bet:
                doc.titel = doc.titel or bet.titel
                doc.dok_id = doc.dok_id or bet.dok_id
                if doc.dok_id:
                    doc.url = f"{DOC_BASE}/dokument/{doc.dok_id}.html"
            vote = votes.get((doc.rm, doc.beteckning))
            if vote:
                doc.votering_url = reverse("votering_detail", args=[vote.votering_id])
    return events


def group_by_day(events: list[UpcomingEvent]):
    days = []
    current = None
    for event in events:
        day = event.starts_at.date()
        if current is None or current["datum"] != day:
            current = {"datum": day, "events": []}
            days.append(current)
        current["events"].append(event)
    return days


def parse_dt(value):
    text = str(value or "").strip()
    if not text:
        return None
    for fmt in ("%Y%m%dT%H%M%S", "%Y%m%dT%H%M", "%Y%m%d"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=STOCKHOLM)
        except ValueError:
            continue
    return None


def description_parts(value):
    parts = [unescape_ical(part).strip() for part in as_list(value) if part]
    status = parts[0] if parts else ""
    body = parts[1] if len(parts) > 1 else ""
    if len(parts) == 1 and DOC_LINE.search(status):
        return "", status
    return status, body


def unescape_ical(text: str) -> str:
    return (text or "").replace("\\n", "\n").replace("\\,", ",").replace("\\;", ";")
