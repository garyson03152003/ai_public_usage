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

# 2-digit FIPS codes, needed to build BLS LAUS series IDs (e.g. state
# unemployment rate) which are keyed by FIPS rather than postal abbreviation.
US_STATE_TO_FIPS = {
    "Alabama": "01", "Alaska": "02", "Arizona": "04", "Arkansas": "05",
    "California": "06", "Colorado": "08", "Connecticut": "09", "Delaware": "10",
    "District of Columbia": "11", "Florida": "12", "Georgia": "13", "Hawaii": "15",
    "Idaho": "16", "Illinois": "17", "Indiana": "18", "Iowa": "19",
    "Kansas": "20", "Kentucky": "21", "Louisiana": "22", "Maine": "23",
    "Maryland": "24", "Massachusetts": "25", "Michigan": "26", "Minnesota": "27",
    "Mississippi": "28", "Missouri": "29", "Montana": "30", "Nebraska": "31",
    "Nevada": "32", "New Hampshire": "33", "New Jersey": "34", "New Mexico": "35",
    "New York": "36", "North Carolina": "37", "North Dakota": "38", "Ohio": "39",
    "Oklahoma": "40", "Oregon": "41", "Pennsylvania": "42", "Rhode Island": "44",
    "South Carolina": "45", "South Dakota": "46", "Tennessee": "47", "Texas": "48",
    "Utah": "49", "Vermont": "50", "Virginia": "51", "Washington": "53",
    "West Virginia": "54", "Wisconsin": "55", "Wyoming": "56",
}

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
