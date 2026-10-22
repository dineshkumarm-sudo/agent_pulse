"""Scheduled Agent Pulse email monitoring.

This script deliberately uses Python for calculations; it does not call an AI API.
Run it from GitHub Actions or locally with the required environment variables.
"""
from __future__ import annotations

import json
import os
import re
import smtplib
from email.message import EmailMessage
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import gspread
import pandas as pd
import requests
from google.oauth2.service_account import Credentials

from src.project_config import PROJECT_SHEETS

IST = ZoneInfo("Asia/Kolkata")
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]


def normalize_column_name(value: object) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value).lower())


def find_column(df: pd.DataFrame, candidates: list[str]) -> str | None:
    normalized = {normalize_column_name(col): col for col in df.columns}
    for candidate in candidates:
        key = normalize_column_name(candidate)
        if key in normalized:
            return normalized[key]
    return None


def parse_numeric(series: pd.Series) -> pd.Series:
    return pd.to_numeric(
        series.astype(str)
        .str.replace(",", "", regex=False)
        .str.replace("%", "", regex=False)
        .str.replace("hours", "", case=False, regex=False)
        .str.replace("hrs", "", case=False, regex=False)
        .str.strip(),
        errors="coerce",
    )


def load_google_client() -> gspread.Client:
    raw_credentials = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    if not raw_credentials:
        raise RuntimeError(
            "Missing GitHub Actions secret GOOGLE_SERVICE_ACCOUNT_JSON. "
            "Add the Google service-account JSON as a repository Actions secret."
        )
    try:
        credentials_dict = json.loads(raw_credentials)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            "GOOGLE_SERVICE_ACCOUNT_JSON is not valid JSON. Paste the full "
            "service-account JSON file contents into the GitHub secret."
        ) from exc

    if isinstance(credentials_dict.get("private_key"), str):
        credentials_dict["private_key"] = credentials_dict["private_key"].replace("\\n", "\n")
    credentials = Credentials.from_service_account_info(credentials_dict, scopes=SCOPES)
    return gspread.authorize(credentials)


def fetch_project_data(client: gspread.Client, spreadsheet_url: str) -> pd.DataFrame:
    match = re.search(r"/d/([a-zA-Z0-9-_]+)", spreadsheet_url)
    sheet = client.open_by_key(match.group(1)) if match else client.open_by_url(spreadsheet_url)
    try:
        worksheet = sheet.worksheet("Daily_Tracker")
    except gspread.WorksheetNotFound:
        worksheet = sheet.get_worksheet(0)
    return pd.DataFrame(worksheet.get_all_records())


def calculate_project_metrics(df: pd.DataFrame, now: datetime) -> dict:
    date_col = find_column(df, ["Date", "Work Date", "Log Date"])
    new_col = find_column(df, ["New Listings"])
    update_col = find_column(df, ["Listing Update"])
    hours_col = find_column(df, ["SB Hrs Worked"])

    missing = [
        label for label, column in (
            ("Date", date_col),
            ("New Listings", new_col),
            ("Listing Update", update_col),
            ("SB Hrs Worked", hours_col),
        ) if column is None
    ]
    if missing:
        raise ValueError("Missing required tracker columns: " + ", ".join(missing))

    result = df.copy()
    result["_date"] = pd.to_datetime(result[date_col], errors="coerce", dayfirst=True).dt.date
    for column in (new_col, update_col, hours_col):
        result[column] = parse_numeric(result[column]).fillna(0)

    today = now.date()
    today_rows = result.loc[result["_date"] == today]
    today_new = float(today_rows[new_col].sum())
    today_updates = float(today_rows[update_col].sum())
    today_hours = float(today_rows[hours_col].sum())
    today_productivity = (
        ((today_new / 20.0) + (today_updates / 25.0)) / (today_hours / 4.0) * 100.0
        if today_hours > 0 else None
    )

    monday = today - timedelta(days=today.weekday())
    week_rows = result.loc[result["_date"].apply(lambda value: pd.notna(value) and monday <= value <= today)]
    weekly_new = int(round(float(week_rows[new_col].sum())))

    return {
        "today_rows": len(today_rows),
        "today_new_listings": int(round(today_new)),
        "today_listing_updates": int(round(today_updates)),
        "today_hours": round(today_hours, 2),
        "today_productivity": round(today_productivity, 2) if today_productivity is not None else None,
        "weekly_new_listings": weekly_new,
        "week_start": monday,
        "week_end": today,
    }


def send_email(message: str, subject: str) -> None:
    sender = os.getenv("GMAIL_ADDRESS", "").strip()
    app_password = os.getenv("GMAIL_APP_PASSWORD", "").strip()
    if not sender or not app_password:
        raise RuntimeError(
            "Missing GitHub Actions secrets GMAIL_ADDRESS and/or GMAIL_APP_PASSWORD. "
            "Add your Gmail address and Gmail App Password under repository Actions secrets."
        )

    email = EmailMessage()
    email["Subject"] = subject
    email["From"] = sender
    email["To"] = sender
    email.set_content(message)

    with smtplib.SMTP("smtp.gmail.com", 587, timeout=30) as server:
        server.ehlo()
        server.starttls()
        server.ehlo()
        server.login(sender, app_password)
        server.send_message(email)


def main() -> None:
    now = datetime.now(IST)
    mode = os.getenv("MONITOR_MODE", "daily").strip().lower()
    if mode not in {"daily", "weekly"}:
        raise ValueError("MONITOR_MODE must be either 'daily' or 'weekly'.")

    client = load_google_client()
    daily_lines = [f"Agent Pulse — Daily Productivity ({now:%d %b %Y})", ""]
    weekly_below_target: list[tuple[str, int, object, object]] = []
    project_errors: list[str] = []

    for project_name, spreadsheet_url in PROJECT_SHEETS.items():
        try:
            df = fetch_project_data(client, spreadsheet_url)
            metrics = calculate_project_metrics(df, now)
            if mode == "daily":
                if metrics["today_productivity"] is None:
                    daily_lines.append(
                        f"• {project_name} — Today's productivity: N/A "
                        f"(no entries with valid hours for today; {metrics['today_rows']} row(s) found)."
                    )
                else:
                    daily_lines.append(
                        f"• {project_name} — Today's productivity: {metrics['today_productivity']:.2f}% "
                        f"| New Listings: {metrics['today_new_listings']} "
                        f"| Listing Updates: {metrics['today_listing_updates']} "
                        f"| Hours: {metrics['today_hours']:g}"
                    )
            if mode == "weekly" and metrics["weekly_new_listings"] < 50:
                weekly_below_target.append((
                    project_name, metrics["weekly_new_listings"],
                    metrics["week_start"], metrics["week_end"]
                ))
        except Exception as exc:
            project_errors.append(f"• {project_name}: {type(exc).__name__}: {exc}")
            if mode == "daily":
                daily_lines.append(f"• {project_name} — Update unavailable due to a data/configuration error.")

    if mode == "daily":
        if project_errors:
            daily_lines.extend(["", "Monitoring errors:", *project_errors])
        send_email("\n".join(daily_lines), "Agent Pulse Daily Productivity")
        return

    if weekly_below_target:
        weekly_lines = [
            f"Agent Pulse — Weekly New Listings Alert ({now:%d %b %Y})",
            "Weekly minimum target: 50 New Listings per project",
            f"Period checked: {weekly_below_target[0][2]:%d %b} to {weekly_below_target[0][3]:%d %b %Y}",
            "",
        ]
        for project_name, count, _start, _end in weekly_below_target:
            weekly_lines.append(f"• {project_name}: {count} New Listings — below target by {50 - count}.")
        send_email("\n".join(weekly_lines), "Agent Pulse Weekly Target Alert")
    elif project_errors:
        send_email(
            "Agent Pulse could not complete the weekly target check:\n" + "\n".join(project_errors),
            "Agent Pulse Weekly Check Error",
        )


if __name__ == "__main__":
    main()
