"""Provider-neutral release genres; never infer a genre from an artist's name."""

import re

GENRES = (
    "Alternative & Indie",
    "Blues",
    "Classical",
    "Country",
    "Electronic & Dance",
    "Folk & Acoustic",
    "Hip-Hop & Rap",
    "Jazz",
    "Metal",
    "Pop",
    "Punk",
    "R&B & Soul",
    "Reggae",
    "Rock",
    "Soundtracks",
    "World & Latin",
)
RULES = {
    "Alternative & Indie": (
        "alternative",
        "indie",
        "shoegaze",
        "britpop",
        "dream pop",
        "grunge",
    ),
    "Blues": ("blues",),
    "Classical": ("classical", "baroque", "chamber music", "opera", "orchestral"),
    "Country": ("country", "americana", "bluegrass"),
    "Electronic & Dance": (
        "electronic",
        "electronica",
        "dance",
        "house",
        "techno",
        "trance",
        "ambient",
        "dubstep",
        "drum and bass",
        "drum & bass",
        "idm",
        "trip hop",
        "trip-hop",
        "disco",
        "synthpop",
    ),
    "Folk & Acoustic": ("folk", "acoustic", "singer-songwriter"),
    "Hip-Hop & Rap": ("hip hop", "hip-hop", "rap", "grime", "trap"),
    "Jazz": ("jazz",),
    "Metal": ("metal",),
    "Pop": ("pop",),
    "Punk": ("punk",),
    "R&B & Soul": ("r&b", "rnb", "rhythm and blues", "soul", "funk", "gospel"),
    "Reggae": ("reggae", "ska", "dancehall", "dub"),
    "Rock": ("rock", "rockabilly"),
    "Soundtracks": ("soundtrack", "score", "musical"),
    "World & Latin": (
        "world",
        "international",
        "latin",
        "afrobeat",
        "afrobeats",
        "salsa",
        "bossa nova",
        "flamenco",
        "reggaeton",
    ),
}


def categories(name):
    name = re.sub(r"\s+", " ", str(name).strip().casefold())
    return [
        genre
        for genre, terms in RULES.items()
        if any(re.search(r"(?<!\w)" + re.escape(term) + r"(?!\w)", name) for term in terms)
    ]


def extract(record):
    """Keep declared genres; accept only recognizable music genres from free-form tags."""
    labels = []
    for field in ("genres", "genre", "primaryGenreName", "tags", "tag-list"):
        values = record.get(field, [])
        if isinstance(values, (str, dict)):
            values = [values]
        if not isinstance(values, list):
            continue
        for value in values:
            name = value.get("name", "") if isinstance(value, dict) else value
            if isinstance(value, dict):
                try:
                    if float(value.get("count", 1)) <= 0:
                        continue
                except (ValueError, TypeError):
                    continue
            if not isinstance(name, str):
                continue
            name = name.strip()
            if not name or len(name) > 100:
                continue
            if field in ("tags", "tag-list") and not categories(name):
                continue
            if name.casefold() not in {v.casefold() for v in labels}:
                labels.append(name)
    return labels[:30]


def normalized(record):
    labels = extract(record)
    broad = sorted({genre for label in labels for genre in categories(label)})
    return labels, broad
