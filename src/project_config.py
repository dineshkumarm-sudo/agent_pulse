"""Shared project configuration used by the dashboard and background monitor."""

# Add each project's Google Sheets URL here when its tracker is ready.
PROJECT_SHEETS = {
    "Superbreakers": (
        "https://docs.google.com/spreadsheets/d/"
        "15hpOWzz9oK6idTrKq0HEaVIwAf-C-5yy_f2fC5Mhtfc/"
        "edit?gid=547444785#gid=547444785"
    ),
    "Our Shopee": (
        "https://docs.google.com/spreadsheets/d/"
        "1xD37rzMdX8ugiEYSQjcT9QSaDpUDcAdxBuv2Ffk6QlY/"
        "edit?gid=30197157#gid=30197157"
    ),
}

PROJECT_NAMES = [
    "Superbreakers",
    "Our Shopee",
    "PCCG",
    "Uno Clean",
    "Baby Riddle",
    "Renegade",
    "Catalog Mapping",
]

# Productivity thresholds apply only to projects using the productivity model.
PRODUCTIVITY_ALERT_THRESHOLDS = {
    "Superbreakers": 90,
}
