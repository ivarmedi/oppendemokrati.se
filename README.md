# Öppen Demokrati

En enkel översikt över riksdagens ledamöter och voteringar, byggd med Django, HTMX och SQLite. Data kommer från [Riksdagens öppna data](https://data.riksdagen.se/).

## Stack

Django + sqlite + htmx

## Kör lokalt

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py sync_riksdagen          # innevarande mandatperiod
# eller bara senaste riksmötet:
python manage.py sync_riksdagen --rm 2025/26
python manage.py runserver            # 8000
python manage.py runserver 8080      # valfri port
PORT=8080 python manage.py runserver
```

## Nix

```bash
nix develop
nix run . -- --bind 127.0.0.1:8080
nix run .#manage -- migrate
nix run .#sync
```

NixOS: `nixosModules.default` kör gunicorn på 127.0.0.1. Första dataladdningen: `systemctl start oppen-demokrati-sync`.

Öppna [http://127.0.0.1:8000/](http://127.0.0.1:8000/) — eller den port du angav.

Sidor cacheas 6 timmar (`cache/`). `sync_riksdagen` tömmer cachen.

## Vad som räknas

- **Närvaro:** andelen voteringar där ledamoten inte är noterad som frånvarande.
- **Partilinje:** partiets vanligaste röst (ja / nej / avstår) i den voteringen. Vid lika är det ingen linje.
- **Avvikelse:** ledamoten röstade ja/nej/avstår, men inte som partiet. Frånvaro räknas inte som avvikelse.
