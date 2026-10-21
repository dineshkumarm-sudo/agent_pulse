import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
import streamlit as st

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.readonly"
]

def get_gsheet_client():
    """Initializes gspread client using Streamlit secrets."""
    # Convert Streamlit secrets object to a standard dict
    creds_dict = dict(st.secrets["gservices"])
    
    # Ensure escaped newline characters in private_key are converted properly
    if "private_key" in creds_dict and isinstance(creds_dict["private_key"], str):
        creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")

    credentials = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    return gspread.authorize(credentials)

def fetch_daily_tracker_data(spreadsheet_url: str, sheet_name: str = "Daily_Tracker") -> pd.DataFrame:
    """Fetches raw tracking data from Google Sheets."""
    client = get_gsheet_client()
    sheet = client.open_by_url(spreadsheet_url)
    worksheet = sheet.worksheet(sheet_name)
    records = worksheet.get_all_records()
    return pd.DataFrame(records)

def calculate_row_productivity(row: pd.Series) -> str | float:
    """
    Calculates Productivity (%):
    [(New Listings ÷ 20) + (Listing Updates ÷ 25)] ÷ (Total Hours ÷ 4) * 100
    """
    hours_worked = row.get("SB Hrs Worked")
    new_listings = row.get("New Listings", 0)
    listing_updates = row.get("Listing Update", 0)

    try:
        hours_worked = float(hours_worked) if pd.notnull(hours_worked) else 0.0
        new_listings = float(new_listings) if pd.notnull(new_listings) else 0.0
        listing_updates = float(listing_updates) if pd.notnull(listing_updates) else 0.0
    except (ValueError, TypeError):
        return "N/A"

    if hours_worked <= 0:
        return "N/A"

    target_new = new_listings / 20.0
    target_updates = listing_updates / 25.0
    hours_factor = hours_worked / 4.0

    productivity = ((target_new + target_updates) / hours_factor) * 100.0
    return round(productivity, 2)

def analyze_project_productivity(df: pd.DataFrame, low_prod_threshold: float = 100.0) -> dict:
    """
    Applies productivity logic across daily logs and detects weekly threshold alerts.
    """
    df_clean = df.copy()
    
    # Ensure numeric fields are converted safely to float to prevent TypeError
    numeric_cols = ["SB Hrs Worked", "New Listings", "Listing Update"]
    for col in numeric_cols:
        if col in df_clean.columns:
            df_clean[col] = pd.to_numeric(df_clean[col], errors="coerce").fillna(0)

    df_clean["Productivity (%)"] = df_clean.apply(calculate_row_productivity, axis=1)

    # Flag low daily productivity (< 100%)
    def is_low(val):
        if isinstance(val, (int, float)):
            return val < low_prod_threshold
        return False

    df_clean["Low_Productivity_Flag"] = df_clean["Productivity (%)"].apply(is_low)

    # Group by Week to check total new listings (< 50 alert)
    if "Week" in df_clean.columns:
        # Cast 'Week' to string explicitly so integer week numbers don't break string formatting/concatenation
        df_clean["Week"] = df_clean["Week"].astype(str)
        weekly_summary = df_clean.groupby("Week")["New Listings"].sum().reset_index()
        weekly_alerts = weekly_summary[weekly_summary["New Listings"] < 50]
    else:
        weekly_alerts = pd.DataFrame(columns=["Week", "New Listings"])

    return {
        "processed_df": df_clean,
        "daily_alerts": df_clean[df_clean["Low_Productivity_Flag"] == True],
        "weekly_alerts": weekly_alerts
    }
