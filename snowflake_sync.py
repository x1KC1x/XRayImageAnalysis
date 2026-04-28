"""
Devon Energy — Asset Integrity X-Ray Image Analysis
Snowflake → SQL Server Sync: pulls facility install/activation dates from
SiteView (via Snowflake) and updates the Inspections table.

PLACEHOLDER VERSION — to be completed once these are confirmed:
  1. Snowflake connection details (account, warehouse, database, schema)
  2. SiteView source table name
  3. Field name mappings (facility_name <-> SiteView ID column)
  4. Snowflake auth method (SSO, key-pair, password)

Run on:    AZUMSAPSD101D (or scheduled nightly)
Source:    Devon Snowflake instance (SiteView mirror)
Target:    AZUMSDBSQ070D.XRayImageAnalysis.Inspections

NOTE: Snowflake driver requires:
  pip install snowflake-connector-python
"""

import os
import logging
import pyodbc
from pathlib import Path
from dotenv import load_dotenv

# Snowflake connector — install when ready: pip install snowflake-connector-python
# import snowflake.connector

load_dotenv()

# ── Setup logging ──────────────────────────────────────────────────────────
Path("logs").mkdir(exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("logs/snowflake_sync.log"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)

# ── Config (placeholders) ──────────────────────────────────────────────────
# Snowflake — populate from .env once available
SNOWFLAKE_ACCOUNT   = os.getenv("SNOWFLAKE_ACCOUNT",   "<TBD>")
SNOWFLAKE_USER      = os.getenv("SNOWFLAKE_USER",      "<TBD>")
SNOWFLAKE_PASSWORD  = os.getenv("SNOWFLAKE_PASSWORD",  "<TBD>")
SNOWFLAKE_WAREHOUSE = os.getenv("SNOWFLAKE_WAREHOUSE", "<TBD>")
SNOWFLAKE_DATABASE  = os.getenv("SNOWFLAKE_DATABASE",  "<TBD>")
SNOWFLAKE_SCHEMA    = os.getenv("SNOWFLAKE_SCHEMA",    "<TBD>")

# SQL Server — already configured in .env
SQL_SERVER   = os.getenv("SQL_SERVER",   "AZUMSDBSQ070D")
SQL_DATABASE = os.getenv("SQL_DATABASE", "XRayImageAnalysis")
SQL_DRIVER   = os.getenv("SQL_DRIVER",   "ODBC Driver 17 for SQL Server")


# ── PLACEHOLDER: replace with actual SiteView table & column names ────────
SNOWFLAKE_QUERY = """
SELECT
    FACILITY_NAME,           -- map to Inspections.FacilityName
    INSTALL_DATE,            -- map to Inspections.FacilityInstallDate
    ACTIVATION_DATE          -- map to Inspections.FacilityActivationDate
FROM {db}.{schema}.SITEVIEW_FACILITY_DIM   -- ← actual table TBD
WHERE INSTALL_DATE IS NOT NULL
   OR ACTIVATION_DATE IS NOT NULL
""".strip()


def get_snowflake_connection():
    """Connect to Snowflake. Uncomment imports above once driver is installed."""
    log.warning("Snowflake connection not yet configured — this is a placeholder.")
    return None
    # Real implementation once details are confirmed:
    # return snowflake.connector.connect(
    #     account=SNOWFLAKE_ACCOUNT,
    #     user=SNOWFLAKE_USER,
    #     password=SNOWFLAKE_PASSWORD,
    #     warehouse=SNOWFLAKE_WAREHOUSE,
    #     database=SNOWFLAKE_DATABASE,
    #     schema=SNOWFLAKE_SCHEMA,
    # )


def get_sql_connection():
    """Connect to local SQL Server using Windows Auth."""
    conn_str = (
        "DRIVER={{{}}};SERVER={};DATABASE={};Trusted_Connection=yes".format(
            SQL_DRIVER, SQL_SERVER, SQL_DATABASE
        )
    )
    return pyodbc.connect(conn_str)


def fetch_facility_dates_from_snowflake(sf_conn):
    """Query Snowflake for facility install/activation dates."""
    query = SNOWFLAKE_QUERY.format(
        db=SNOWFLAKE_DATABASE, schema=SNOWFLAKE_SCHEMA
    )
    cursor = sf_conn.cursor()
    cursor.execute(query)
    rows = cursor.fetchall()
    cursor.close()

    facility_data = {}
    for facility_name, install_date, activation_date in rows:
        facility_data[facility_name] = {
            "install_date":    install_date,
            "activation_date": activation_date,
        }
    return facility_data


def update_sql_facility_dates(sql_conn, facility_data):
    """Update Inspections records with facility dates."""
    cursor = sql_conn.cursor()

    sql = """
        UPDATE Inspections
        SET FacilityInstallDate    = ?,
            FacilityActivationDate = ?,
            ModifiedDate           = GETDATE()
        WHERE FacilityName = ?
    """

    updated = 0
    for facility_name, dates in facility_data.items():
        cursor.execute(
            sql,
            dates["install_date"],
            dates["activation_date"],
            facility_name
        )
        updated += cursor.rowcount

    sql_conn.commit()
    cursor.close()
    return updated


def run():
    log.info("=" * 60)
    log.info("Snowflake → SQL Server facility-date sync")
    log.info("=" * 60)

    sf_conn = get_snowflake_connection()
    if sf_conn is None:
        log.error("Cannot proceed: Snowflake connection not configured.")
        log.error("Please update .env with SNOWFLAKE_* variables and install:")
        log.error("  pip install snowflake-connector-python")
        return

    try:
        log.info("Fetching facility dates from Snowflake...")
        facility_data = fetch_facility_dates_from_snowflake(sf_conn)
        log.info("  Retrieved dates for {} facilities".format(len(facility_data)))

        log.info("Updating SQL Server Inspections records...")
        sql_conn = get_sql_connection()
        rows_updated = update_sql_facility_dates(sql_conn, facility_data)
        log.info("  Updated {} inspection records".format(rows_updated))
        sql_conn.close()

    except Exception as e:
        log.error("Sync failed: {}".format(e))
    finally:
        if sf_conn:
            sf_conn.close()

    log.info("Sync complete.")


if __name__ == "__main__":
    run()
