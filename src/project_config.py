"""Shared project configuration used by the dashboard and background monitor."""

# Add each project's Google Sheets URL here when its tracker is ready.
# Only projects with a configured URL are connected to live dashboard/monitoring data.
PROJECT_SHEETS = {
    "Superbreakers": (
        "https://docs.google.com/spreadsheets/d/"
        "15hpOWzz9oK6idTrKq0HEaVIwAf-C-5yy_f2fC5Mhtfc/"
        "edit?gid=547444785#gid=547444785"
    )
}

# Project directory displayed in the dashboard. Additional projects can be connected later.
PROJECT_NAMES = [
    "Superbreakers",
    "Our Shopee",
    "PCCG",
    "Uno Clean",
    "Baby Riddle",
    "Renegade",
    "Catalog Mapping",
]

# Thresholds are configurable per project. Only Superbreakers has been specified so far.
PRODUCTIVITY_ALERT_THRESHOLDS = {
    "Superbreakers": 90,
}
