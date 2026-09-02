"""Fetch Riksdagen open data into the local SQLite database."""

from __future__ import annotations

import csv
import io
import zipfile
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path

import httpx
from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone

from .models import Betankande, Ledamot, PartiLinje, Rost, Uppdrag, Votering

BASE = "https://data.riksdagen.se"
CURRENT_TERM = ["2022/23", "2023/24", "2024/25", "2025/26"]
DATA_DIR = Path(getattr(settings, "DOWNLOAD_DIR", settings.BASE_DIR / "data"))


def as_list(value):
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def parse_date(value):
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(text[:19] if len(text) >= 19 else text, fmt).date()
        except ValueError:
            continue
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def uppgift_text(item):
    raw = item.get("uppgift")
    if isinstance(raw, list):
        return str(raw[0]) if raw else ""
    return str(raw or "")


class SyncError(RuntimeError):
    pass


def client():
    return httpx.Client(
        timeout=httpx.Timeout(60.0, connect=20.0),
        follow_redirects=True,
        headers={"User-Agent": "OppenDemokrati/0.1 (+local)"},
    )


def fetch_json(http: httpx.Client, url: str, params=None):
    response = http.get(url, params=params)
    response.raise_for_status()
    return response.json()


def sync_all(rms=None, log=print):
    rms = rms or CURRENT_TERM
    DATA_DIR.mkdir(exist_ok=True)
    with client() as http:
        log("Hämtar ledamöter…")
        n_ledamoter = sync_ledamoter(http, log=log)
        log("Hämtar betänkanden…")
        n_bet = sync_betankanden(http, rms, log=log)
        log("Hämtar voteringar…")
        n_votes = sync_voteringar(http, rms, log=log)
    log("Beräknar partilinje och statistik…")
    n_linjer = compute_party_lines(rms)
    compute_ledamot_stats()
    cache.clear()
    log(
        f"Klart. {n_ledamoter} ledamöter, {n_bet} betänkanden, "
        f"{n_votes} röster, {n_linjer} partilinjer. Sidcachen tömd."
    )


def sync_ledamoter(http: httpx.Client, log=print) -> int:
    payload = fetch_json(
        http,
        f"{BASE}/personlista/",
        params={
            "iid": "",
            "fnamn": "",
            "enamn": "",
            "f_ar": "",
            "kn": "",
            "parti": "",
            "valkrets": "",
            "org": "",
            "utformat": "json",
        },
    )
    people = as_list(payload.get("personlista", {}).get("person"))
    if not people:
        raise SyncError("Personlistan var tom.")

    today = timezone.localdate()
    seen = []
    with transaction.atomic():
        Ledamot.objects.filter(is_current=True).update(is_current=False)
        for person in people:
            iid = (person.get("intressent_id") or "").strip()
            if not iid:
                continue
            seen.append(iid)
            email = ""
            title = ""
            for item in as_list((person.get("personuppgift") or {}).get("uppgift")):
                kod = item.get("kod") or ""
                if kod == "Officiell e-postadress":
                    email = uppgift_text(item).replace("[på]", "@")
                elif kod == "sv":
                    title = uppgift_text(item)
            Ledamot.objects.update_or_create(
                intressent_id=iid,
                defaults={
                    "sourceid": person.get("sourceid") or "",
                    "tilltalsnamn": person.get("tilltalsnamn") or "",
                    "efternamn": person.get("efternamn") or "",
                    "sorteringsnamn": person.get("sorteringsnamn")
                    or f"{person.get('efternamn', '')},{person.get('tilltalsnamn', '')}",
                    "parti": (person.get("parti") or "-").strip() or "-",
                    "valkrets": person.get("valkrets") or "",
                    "status": person.get("status") or "",
                    "kon": person.get("kon") or "",
                    "fodd_ar": int(person["fodd_ar"]) if person.get("fodd_ar") else None,
                    "bild_url": person.get("bild_url_192") or person.get("bild_url_max") or "",
                    "bild_url_liten": person.get("bild_url_80") or "",
                    "epost": email,
                    "titel": title,
                    "is_current": True,
                },
            )
            Uppdrag.objects.filter(ledamot_id=iid).delete()
            current_rows = []
            for uppdrag in as_list((person.get("personuppdrag") or {}).get("uppdrag")):
                from_date = parse_date(uppdrag.get("from"))
                to_date = parse_date(uppdrag.get("tom"))
                is_current = (from_date is None or from_date <= today) and (
                    to_date is None or to_date >= today
                )
                if not is_current:
                    continue
                organ_namn = ""
                raw_uppgift = uppdrag.get("uppgift")
                if isinstance(raw_uppgift, list) and raw_uppgift:
                    first = raw_uppgift[0]
                    organ_namn = first if isinstance(first, str) else ""
                current_rows.append(
                    Uppdrag(
                        ledamot_id=iid,
                        organ_kod=uppdrag.get("organ_kod") or "",
                        organ_namn=organ_namn,
                        roll=uppdrag.get("roll_kod") or "",
                        typ=uppdrag.get("typ") or "",
                        from_date=from_date,
                        to_date=to_date,
                        is_current=True,
                    )
                )
            Uppdrag.objects.bulk_create(current_rows)
    log(f"  {len(seen)} nuvarande ledamöter")
    return len(seen)


def sync_betankanden(http: httpx.Client, rms, log=print) -> int:
    total = 0
    for rm in rms:
        url = f"{BASE}/dokumentlista/"
        params = {"doktyp": "bet", "rm": rm, "utformat": "json", "sz": "200"}
        page_count = 0
        while url:
            payload = fetch_json(http, url, params=params)
            params = None
            docs = as_list(payload.get("dokumentlista", {}).get("dokument"))
            rows = []
            for doc in docs:
                dok_id = (doc.get("dok_id") or doc.get("id") or "").strip()
                if not dok_id:
                    continue
                rows.append(
                    Betankande(
                        dok_id=dok_id,
                        rm=doc.get("rm") or rm,
                        beteckning=doc.get("beteckning") or "",
                        titel=doc.get("titel") or "",
                        organ=doc.get("organ") or "",
                        datum=parse_date(doc.get("datum")),
                        notis=(doc.get("notisrubrik") or "").strip(),
                    )
                )
            Betankande.objects.bulk_create(rows, update_conflicts=True, unique_fields=["dok_id"], update_fields=["rm", "beteckning", "titel", "organ", "datum", "notis"])
            total += len(rows)
            page_count += 1
            nxt = payload.get("dokumentlista", {}).get("@nasta_sida")
            url = nxt.replace("http://", "https://") if nxt else ""
        log(f"  {rm}: {page_count} sidor betänkanden")
    return total


def sync_voteringar(http: httpx.Client, rms, log=print) -> int:
    total = 0
    for rm in rms:
        rows = load_vote_rows(http, rm, log=log)
        total += import_vote_rows(rm, rows, log=log)
    return total


def load_vote_rows(http: httpx.Client, rm: str, log=print) -> list[dict]:
    compact = rm.replace("/", "")
    candidates = [
        f"{BASE}/dataset/votering/votering-{compact}.csv.zip",
        f"{BASE}/dataset/votering/votering-{rm.replace('/', '-')}.csv.zip",
    ]
    for url in candidates:
        try:
            rows = download_vote_zip(http, url, rm)
            if rows:
                log(f"  {rm}: {len(rows)} rader från dataset")
                return rows
        except httpx.HTTPError as exc:
            log(f"  {rm}: dataset misslyckades ({exc})")
    rows = fetch_vote_api(http, rm, log=log)
    log(f"  {rm}: {len(rows)} rader från API")
    return rows


def download_vote_zip(http: httpx.Client, url: str, rm: str) -> list[dict]:
    dest = DATA_DIR / f"votering-{rm.replace('/', '')}.csv.zip"
    if dest.exists() and dest.stat().st_size > 1000:
        raw_zip = dest.read_bytes()
    else:
        response = http.get(url)
        response.raise_for_status()
        dest.write_bytes(response.content)
        raw_zip = response.content
    with zipfile.ZipFile(io.BytesIO(raw_zip)) as archive:
        name = next(n for n in archive.namelist() if n.lower().endswith(".csv"))
        raw = archive.read(name)
    return parse_vote_csv(raw)


VOTE_FIELDS = [
    "rm",
    "beteckning",
    "votering_id",
    "punkt",
    "namn",
    "intressent_id",
    "parti",
    "valkrets",
    "rost",
    "avser",
    "banknummer",
    "kon",
    "fodd",
    "datum",
]


def parse_vote_csv(raw: bytes) -> list[dict]:
    text = raw.decode("utf-8-sig")
    delimiter = ";" if text[:2048].count(";") > text[:2048].count(",") else ","
    stream = io.StringIO(text)
    first = stream.readline()
    stream.seek(0)
    has_header = "votering_id" in first.lower() or first.lower().startswith("rm")
    reader = csv.DictReader(
        stream,
        fieldnames=None if has_header else VOTE_FIELDS,
        delimiter=delimiter,
    )
    rows = []
    for row in reader:
        cleaned = {(k or "").strip(): (v or "").strip() for k, v in row.items() if k}
        if cleaned.get("votering_id") in {"", "votering_id"}:
            continue
        rows.append(cleaned)
    return rows


def fetch_vote_api(http: httpx.Client, rm: str, log=print) -> list[dict]:
    rows = []
    page = 1
    while True:
        payload = fetch_json(
            http,
            f"{BASE}/voteringlista/",
            params={"rm": rm, "utformat": "json", "antal": "10000", "p": str(page)},
        )
        chunk = as_list(payload.get("voteringlista", {}).get("votering"))
        if not chunk:
            break
        for item in chunk:
            rows.append(
                {
                    "rm": item.get("rm") or rm,
                    "beteckning": item.get("beteckning") or "",
                    "votering_id": item.get("votering_id") or "",
                    "punkt": item.get("punkt") or "1",
                    "namn": item.get("namn") or "",
                    "intressent_id": item.get("intressent_id") or "",
                    "parti": item.get("parti") or "",
                    "rost": item.get("rost") or "",
                    "avser": item.get("avser") or "",
                    "datum": (item.get("datum") or item.get("systemdatum") or "")[:10],
                    "dok_id": item.get("dok_id") or "",
                }
            )
        nxt = payload.get("voteringlista", {}).get("@nasta_sida")
        log(f"    sida {page}: {len(chunk)} rader")
        if nxt:
            # Follow official next-page URL on subsequent loops
            extra = fetch_paginated(http, nxt.replace("http://", "https://"))
            rows.extend(extra)
            break
        if len(chunk) < 10000:
            break
        page += 1
    return rows


def fetch_paginated(http: httpx.Client, url: str) -> list[dict]:
    rows = []
    while url:
        payload = fetch_json(http, url)
        chunk = as_list(payload.get("voteringlista", {}).get("votering"))
        for item in chunk:
            rows.append(
                {
                    "rm": item.get("rm") or "",
                    "beteckning": item.get("beteckning") or "",
                    "votering_id": item.get("votering_id") or "",
                    "punkt": item.get("punkt") or "1",
                    "namn": item.get("namn") or "",
                    "intressent_id": item.get("intressent_id") or "",
                    "parti": item.get("parti") or "",
                    "rost": item.get("rost") or "",
                    "avser": item.get("avser") or "",
                    "datum": (item.get("datum") or item.get("systemdatum") or "")[:10],
                    "dok_id": item.get("dok_id") or "",
                }
            )
        nxt = payload.get("voteringlista", {}).get("@nasta_sida")
        url = nxt.replace("http://", "https://") if nxt else ""
    return rows


def import_vote_rows(rm: str, rows: list[dict], log=print) -> int:
    titles = {}
    for bet in Betankande.objects.filter(rm=rm):
        titles[bet.dok_id.upper()] = bet
        titles[f"{bet.rm}:{bet.beteckning}".upper()] = bet

    voteringar = {}
    roster = []
    stub_ids = set()
    for row in rows:
        vid = (row.get("votering_id") or "").strip()
        iid = (row.get("intressent_id") or "").strip()
        if not vid or not iid:
            continue
        punkt = row.get("punkt") or "1"
        try:
            punkt_n = int(str(punkt).split(".")[0])
        except ValueError:
            punkt_n = 1
        dok_id = (row.get("dok_id") or "").strip()
        beteckning = (row.get("beteckning") or "").strip()
        if vid not in voteringar:
            bet = titles.get(dok_id.upper()) or titles.get(f"{rm}:{beteckning}".upper())
            voteringar[vid] = Votering(
                votering_id=vid,
                rm=row.get("rm") or rm,
                beteckning=beteckning,
                punkt=punkt_n,
                dok_id=dok_id,
                datum=parse_date(row.get("datum")),
                avser=row.get("avser") or "",
                titel=(bet.titel if bet else ""),
            )
        roster.append(
            Rost(
                votering_id=vid,
                ledamot_id=iid,
                intressent_id=iid,
                namn=row.get("namn") or "",
                parti=(row.get("parti") or "-").strip() or "-",
                rost=row.get("rost") or "",
            )
        )
        stub_ids.add((iid, row.get("namn") or "", (row.get("parti") or "-").strip() or "-"))

    existing = set(Ledamot.objects.filter(pk__in=[s[0] for s in stub_ids]).values_list("pk", flat=True))
    stubs = []
    for iid, namn, parti in stub_ids:
        if iid in existing:
            continue
        parts = namn.replace(",", " ").split()
        stubs.append(
            Ledamot(
                intressent_id=iid,
                tilltalsnamn=" ".join(parts[:-1]) if len(parts) > 1 else namn,
                efternamn=parts[-1] if parts else namn,
                sorteringsnamn=namn,
                parti=parti,
                is_current=False,
            )
        )
        existing.add(iid)
    if stubs:
        Ledamot.objects.bulk_create(stubs, ignore_conflicts=True)

    with transaction.atomic():
        Rost.objects.filter(votering__rm=rm).delete()
        Votering.objects.filter(rm=rm).delete()
        Votering.objects.bulk_create(voteringar.values(), batch_size=1000)
        Rost.objects.bulk_create(roster, batch_size=2000)
    log(f"  {rm}: importerade {len(voteringar)} voteringar, {len(roster)} röster")
    return len(roster)


def compute_party_lines(rms) -> int:
    PartiLinje.objects.filter(votering__rm__in=rms).delete()
    counts = (
        Rost.objects.filter(votering__rm__in=rms)
        .exclude(rost="Frånvarande")
        .values("votering_id", "parti", "rost")
        .annotate(n=Count("id"))
    )
    grouped = defaultdict(list)
    for row in counts:
        grouped[(row["votering_id"], row["parti"])].append((row["rost"], row["n"]))

    linjer = []
    for key, tallies in grouped.items():
        tallies.sort(key=lambda item: (-item[1], item[0]))
        linje = ""
        if tallies:
            top_n = tallies[0][1]
            winners = [name for name, n in tallies if n == top_n]
            if len(winners) == 1:
                linje = winners[0]
        linjer.append(PartiLinje(votering_id=key[0], parti=key[1], linje=linje))
    PartiLinje.objects.bulk_create(linjer, batch_size=2000)

    from django.db import connection

    placeholders = ",".join(["%s"] * len(rms))
    with connection.cursor() as cursor:
        cursor.execute(
            f"""
            UPDATE riksdag_rost
            SET med_partiet = CASE
                WHEN rost = 'Frånvarande' THEN NULL
                WHEN COALESCE((
                    SELECT pl.linje FROM riksdag_partilinje pl
                    WHERE pl.votering_id = riksdag_rost.votering_id
                      AND pl.parti = riksdag_rost.parti
                ), '') = '' THEN NULL
                WHEN rost = (
                    SELECT pl.linje FROM riksdag_partilinje pl
                    WHERE pl.votering_id = riksdag_rost.votering_id
                      AND pl.parti = riksdag_rost.parti
                ) THEN 1
                ELSE 0
            END
            WHERE votering_id IN (
                SELECT votering_id FROM riksdag_votering WHERE rm IN ({placeholders})
            )
            """,
            rms,
        )

    tallies = (
        Rost.objects.filter(votering__rm__in=rms)
        .values("votering_id", "rost")
        .annotate(n=Count("id"))
    )
    by_vote = defaultdict(Counter)
    for row in tallies:
        by_vote[row["votering_id"]][row["rost"]] = row["n"]
    vote_updates = []
    for votering in Votering.objects.filter(rm__in=rms):
        c = by_vote[votering.votering_id]
        votering.ja = c.get("Ja", 0)
        votering.nej = c.get("Nej", 0)
        votering.avstar = c.get("Avstår", 0)
        votering.franvarande = c.get("Frånvarande", 0)
        vote_updates.append(votering)
    Votering.objects.bulk_update(vote_updates, ["ja", "nej", "avstar", "franvarande"], batch_size=1000)
    return len(linjer)


def compute_ledamot_stats():
    stats = (
        Rost.objects.values("intressent_id")
        .annotate(
            total=Count("id"),
            franvarande=Count("id", filter=Q(rost="Frånvarande")),
            med=Count("id", filter=Q(med_partiet=True)),
            mot=Count("id", filter=Q(med_partiet=False)),
        )
    )
    by_id = {row["intressent_id"]: row for row in stats}
    updates = []
    for ledamot in Ledamot.objects.all():
        row = by_id.get(ledamot.intressent_id, {})
        ledamot.antal_voteringar = row.get("total", 0)
        ledamot.antal_franvarande = row.get("franvarande", 0)
        ledamot.antal_med_partiet = row.get("med", 0)
        ledamot.antal_mot_partiet = row.get("mot", 0)
        updates.append(ledamot)
    Ledamot.objects.bulk_update(
        updates,
        ["antal_voteringar", "antal_franvarande", "antal_med_partiet", "antal_mot_partiet"],
        batch_size=500,
    )
