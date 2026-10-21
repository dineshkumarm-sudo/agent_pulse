
def add_productivity_calculation(df):
    """Calculate productivity using Agent Pulse's established formula."""

    import pandas as pd

    result = df.copy()

    # Match column names without depending on capitalization.
    column_lookup = {
        str(column).strip().lower(): column
        for column in result.columns
    }

    completed_col = column_lookup.get("completed")
    hours_col = column_lookup.get("production hours")

    if completed_col is None or hours_col is None:
        return result, False

    completed = pd.to_numeric(
        result[completed_col], errors="coerce"
    )
    hours = pd.to_numeric(
        result[hours_col], errors="coerce"
    )

    expected_production = (hours * 75 / 8).round()

    result["Productivity (%)"] = (
        completed.div(expected_production.where(expected_production != 0))
        * 100
    )

    return result, True


def highlight_productivity(value):
    """Apply the requested productivity thresholds."""

    try:
        percentage = float(value)
    except (TypeError, ValueError):
        return ""

    if percentage < 95:
        return "background-color: #FDE2E2; color: #B91C1C; font-weight: bold;"

    if 95 <= percentage < 100:
        return "background-color: #FFEDD5; color: #9A3412; font-weight: bold;"

    return ""
