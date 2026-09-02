PARTIES = {
    "S": {"name": "Socialdemokraterna", "color": "#c8102e"},
    "M": {"name": "Moderaterna", "color": "#0f8ad0"},
    "SD": {"name": "Sverigedemokraterna", "color": "#c9a227"},
    "V": {"name": "Vänsterpartiet", "color": "#9b0d16"},
    "C": {"name": "Centerpartiet", "color": "#1b7a3a"},
    "KD": {"name": "Kristdemokraterna", "color": "#1d2a6b"},
    "L": {"name": "Liberalerna", "color": "#006ab3"},
    "MP": {"name": "Miljöpartiet", "color": "#4f8a10"},
    "FP": {"name": "Folkpartiet", "color": "#006ab3"},
    "-": {"name": "Partilös", "color": "#6b6560"},
}

PARTY_ORDER = ["S", "M", "SD", "V", "C", "KD", "L", "MP", "-"]


def party_name(code: str) -> str:
    return PARTIES.get(code or "-", {"name": code or "Okänt"})["name"]


def party_color(code: str) -> str:
    return PARTIES.get(code or "-", PARTIES["-"])["color"]
