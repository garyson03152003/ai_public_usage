"""Canonical US state name <-> abbreviation mapping, used to align data
that arrives keyed by full name (Google Trends) with data keyed by
abbreviation or city (court stats, city open-data portals).
"""

US_STATE_TO_ABBR = {
    "Alabama": "AL", "Alaska": "AK", "Arizona": "AZ", "Arkansas": "AR",
    "California": "CA", "Colorado": "CO", "Connecticut": "CT", "Delaware": "DE",
    "District of Columbia": "DC", "Florida": "FL", "Georgia": "GA", "Hawaii": "HI",
    "Idaho": "ID", "Illinois": "IL", "Indiana": "IN", "Iowa": "IA",
    "Kansas": "KS", "Kentucky": "KY", "Louisiana": "LA", "Maine": "ME",
    "Maryland": "MD", "Massachusetts": "MA", "Michigan": "MI", "Minnesota": "MN",
    "Mississippi": "MS", "Missouri": "MO", "Montana": "MT", "Nebraska": "NE",
    "Nevada": "NV", "New Hampshire": "NH", "New Jersey": "NJ", "New Mexico": "NM",
    "New York": "NY", "North Carolina": "NC", "North Dakota": "ND", "Ohio": "OH",
    "Oklahoma": "OK", "Oregon": "OR", "Pennsylvania": "PA", "Rhode Island": "RI",
    "South Carolina": "SC", "South Dakota": "SD", "Tennessee": "TN", "Texas": "TX",
    "Utah": "UT", "Vermont": "VT", "Virginia": "VA", "Washington": "WA",
    "West Virginia": "WV", "Wisconsin": "WI", "Wyoming": "WY",
}

US_ABBR_TO_STATE = {abbr: name for name, abbr in US_STATE_TO_ABBR.items()}

# Maps a handful of major cities to the state they sit in, so city-level
# open-data (e.g. parking ticket appeals) can be rolled up to state level.
CITY_TO_STATE = {
    "New York City": "New York",
    "New York": "New York",
    "Chicago": "Illinois",
    "Los Angeles": "California",
    "San Francisco": "California",
    "Philadelphia": "Pennsylvania",
    "Houston": "Texas",
    "Seattle": "Washington",
    "Boston": "Massachusetts",
    "Washington DC": "District of Columbia",
}


def normalize_state_name(value: str) -> str | None:
    """Best-effort normalization of a state name/abbreviation to the
    canonical full name used as the join key across this project."""
    if value is None:
        return None
    value = value.strip()
    if value in US_STATE_TO_ABBR:
        return value
    upper = value.upper()
    if upper in US_ABBR_TO_STATE:
        return US_ABBR_TO_STATE[upper]
    if value in CITY_TO_STATE:
        return CITY_TO_STATE[value]
    return None
