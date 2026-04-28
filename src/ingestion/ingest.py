"""
Devon Energy — Asset Integrity X-Ray Image Analysis
Ingestion Script: reads extracted JSON files from data/processed/
and loads them into the XRayImageAnalysis SQL Server database.

Target DB:  AZUMSDBSQ070D
Database:   XRayImageAnalysis
Run on:     AZUMSAPSD101D
"""

import os
import json
import logging
import pyodbc
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# ── Setup logging ──────────────────────────────────────────────────────────
Path("logs").mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("logs/ingest.log"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)

# ── Config ─────────────────────────────────────────────────────────────────
SQL_SERVER   = os.getenv("SQL_SERVER",   "AZUMSDBSQ070D")
SQL_DATABASE = os.getenv("SQL_DATABASE", "XRayImageAnalysis")
SQL_USERNAME = os.getenv("SQL_USERNAME", "")
SQL_PASSWORD = os.getenv("SQL_PASSWORD", "")
SQL_DRIVER   = os.getenv("SQL_DRIVER",   "ODBC Driver 17 for SQL Server")
PROCESSED_FOLDER = Path(os.getenv("OUTPUT_FOLDER", "data/processed"))


# ── Database connection ────────────────────────────────────────────────────
def get_connection():
    """Connect using Windows Auth (Trusted) or SQL Auth depending on .env."""
    if SQL_USERNAME and SQL_USERNAME not in ("<pending>", "xsvcimageextract"):
        conn_str = (
            "DRIVER={{{}}};SERVER={};DATABASE={};UID={};PWD={}".format(
                SQL_DRIVER, SQL_SERVER, SQL_DATABASE, SQL_USERNAME, SQL_PASSWORD
            )
        )
    else:
        # Windows Authentication — uses the account running the script
        conn_str = (
            "DRIVER={{{}}};SERVER={};DATABASE={};Trusted_Connection=yes".format(
                SQL_DRIVER, SQL_SERVER, SQL_DATABASE
            )
        )
    return pyodbc.connect(conn_str)


# ── Helper: safe value conversion ─────────────────────────────────────────
def safe_int(val):
    """Convert value to int safely, return None if not possible."""
    if val is None:
        return None
    try:
        return int(str(val).replace(",", "").strip())
    except (ValueError, TypeError):
        return None


def safe_float(val):
    """Convert value to float safely, return None if not possible."""
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def safe_bit(val):
    """Convert value to bit (0/1) safely."""
    if val is None:
        return None
    if isinstance(val, bool):
        return 1 if val else 0
    if isinstance(val, (int, float)):
        return 1 if val else 0
    if isinstance(val, str):
        return 1 if val.upper() in ("TRUE", "YES", "1", "X") else 0
    return None


def safe_str(val, max_len=None):
    """Convert value to string safely, truncate if needed."""
    if val is None:
        return None
    s = str(val).strip()
    if max_len and len(s) > max_len:
        s = s[:max_len]
    return s if s else None


# ── Check for duplicate inspection ────────────────────────────────────────
def inspection_exists(cursor, source_file):
    """Check if this file has already been ingested."""
    cursor.execute(
        "SELECT InspectionID FROM Inspections WHERE SourceFile = ?",
        source_file
    )
    row = cursor.fetchone()
    return row[0] if row else None


# ── Insert Inspection (header) ─────────────────────────────────────────────
def insert_inspection(cursor, header, meta):
    """Insert header data into Inspections table. Returns new InspectionID."""
    sql = """
    INSERT INTO Inspections (
        OperationsRoute, WorkOrderNo, FacilityName, WellNo, FixedAsset,
        NonHeated, Heated, ManufactureDate, Manufacture, SerialNo,
        NBIC, NBICNo, PipingSystem, PipingCircuit, ExaminationDate,
        ServiceProvider, RTTechnicianName, UTTechnicianName, SourceType,
        ExposureCount, ExposureTime, FramesPerSecond, SourceToDDA,
        DMLCount, CriteriaSummary, CriteriaPercentage,
        DMLMonitorRecs, TimeInterval, ReviewerName, ReviewerDate,
        SourceFile, ExtractedAt
    ) VALUES (
        ?, ?, ?, ?, ?,
        ?, ?, ?, ?, ?,
        ?, ?, ?, ?, ?,
        ?, ?, ?, ?,
        ?, ?, ?, ?,
        ?, ?, ?,
        ?, ?, ?, ?,
        ?, ?
    )
    """

    extracted_at = None
    if meta.get("extracted_at"):
        try:
            extracted_at = datetime.fromisoformat(
                meta["extracted_at"].replace("Z", "+00:00")
            )
        except Exception:
            extracted_at = None

    params = (
        safe_str(header.get("operations_route"), 100),
        safe_str(header.get("work_order_no"), 50),
        safe_str(header.get("facility_name"), 150),
        safe_str(header.get("well_no"), 100),
        safe_str(header.get("fixed_asset"), 150),
        safe_bit(header.get("non_heated")),
        safe_bit(header.get("heated")),
        safe_str(header.get("manufacture_date"), 50),
        safe_str(header.get("manufacture"), 100),
        safe_str(header.get("serial_no"), 100),
        safe_str(header.get("nbic"), 50),
        safe_str(header.get("nbic_no"), 50),
        safe_str(header.get("piping_system"), 100),
        safe_str(header.get("piping_circuit"), 100),
        safe_str(header.get("examination_date"), 50),
        safe_str(header.get("service_provider"), 100),
        safe_str(header.get("rt_technician_name"), 100),
        safe_str(header.get("ut_technician_name"), 100),
        safe_str(header.get("source_type"), 50),
        safe_str(header.get("exposure_count"), 20),
        safe_str(header.get("exposure_time"), 50),
        safe_str(header.get("frames_per_second"), 50),
        safe_str(header.get("source_to_dda"), 50),
        safe_int(header.get("dml_count")),
        safe_str(header.get("criteria_summary"), 100),
        safe_str(header.get("criteria_percentage"), 20),
        safe_int(header.get("dml_monitor_recommendations")),
        safe_str(header.get("time_interval"), 50),
        safe_str(header.get("reviewer_name"), 100),
        safe_str(header.get("reviewer_date"), 20),
        safe_str(meta.get("source_file"), 500),
        extracted_at,
    )

    cursor.execute(sql, params)

    # Get the new InspectionID
    cursor.execute("SELECT @@IDENTITY")
    return int(cursor.fetchone()[0])


# ── Insert DML Measurements ────────────────────────────────────────────────
def insert_dmls(cursor, inspection_id, dmls):
    """Insert all DML rows for this inspection."""
    sql = """
    INSERT INTO DML_Measurements (
        InspectionID, DMLNumber, DMNumber, Circuit,
        PipeComponentDescription, Size, Schedule,
        ValveType, ValveMfg, Criteria, AnomalyWeld,
        CriticalFlag, UTThickness, RTThickness, MinWallThickness, PartType
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    count = 0
    for d in dmls:
        mwt = safe_float(d.get("min_wall_thickness"))
        critical = safe_bit(d.get("critical_flag"))

        # Override critical flag if min wall thickness is below threshold
        if mwt is not None and mwt < 0.100:
            critical = 1

        params = (
            inspection_id,
            safe_str(d.get("dml_number"), 20),
            safe_str(d.get("dm_number"), 20),
            safe_str(d.get("circuit"), 50),
            safe_str(d.get("pipe_component_description"), 255),
            safe_str(d.get("size"), 50),
            safe_str(d.get("schedule"), 50),
            safe_str(d.get("valve_type"), 100),
            safe_str(d.get("valve_mfg"), 100),
            safe_str(d.get("criteria"), 50),
            safe_str(d.get("anomaly_weld"), 100),
            critical,
            safe_float(d.get("ut_thickness")),
            safe_float(d.get("rt_thickness")),
            mwt,
            safe_str(d.get("part_type"), 100),
        )
        cursor.execute(sql, params)
        count += 1
    return count


# ── Insert or get Part ─────────────────────────────────────────────────────
def get_or_create_part(cursor, facility, well, dml_number, dm_number,
                       part_type, description, size, schedule):
    """Find existing part or create new one. Returns PartID."""
    cursor.execute(
        """SELECT PartID FROM Parts
           WHERE FacilityName = ? AND WellNo = ?
           AND DMLNumber = ? AND DMNumber = ?""",
        facility, well, dml_number, dm_number
    )
    row = cursor.fetchone()
    if row:
        return row[0]

    cursor.execute(
        """INSERT INTO Parts
           (FacilityName, WellNo, DMLNumber, DMNumber,
            PartType, PipeComponentDescription, Size, Schedule)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        safe_str(facility, 150),
        safe_str(well, 100),
        safe_str(dml_number, 20),
        safe_str(dm_number, 20),
        safe_str(part_type, 100),
        safe_str(description, 255),
        safe_str(size, 50),
        safe_str(schedule, 50),
    )
    cursor.execute("SELECT @@IDENTITY")
    return int(cursor.fetchone()[0])


# ── Insert Thickness History ───────────────────────────────────────────────
def insert_thickness_history(cursor, inspection_id, header, dmls):
    """Insert time-series thickness records for predictive analysis."""
    facility = safe_str(header.get("facility_name"), 150)
    well = safe_str(header.get("well_no"), 100)
    exam_date = safe_str(header.get("examination_date"), 50)

    count = 0
    for d in dmls:
        mwt = safe_float(d.get("min_wall_thickness"))
        if mwt is None:
            continue

        part_id = get_or_create_part(
            cursor,
            facility,
            well,
            safe_str(d.get("dml_number"), 20),
            safe_str(d.get("dm_number"), 20),
            safe_str(d.get("part_type"), 100),
            safe_str(d.get("pipe_component_description"), 255),
            safe_str(d.get("size"), 50),
            safe_str(d.get("schedule"), 50),
        )

        critical = 1 if mwt < 0.100 else 0

        cursor.execute(
            """INSERT INTO Thickness_History
               (PartID, InspectionID, ExaminationDate,
                UTThickness, RTThickness, MinWallThickness,
                Criteria, CriticalFlag)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            part_id,
            inspection_id,
            exam_date,
            safe_float(d.get("ut_thickness")),
            safe_float(d.get("rt_thickness")),
            mwt,
            safe_str(d.get("criteria"), 50),
            critical,
        )
        count += 1
    return count


# ── Process a single JSON file ─────────────────────────────────────────────
def process_json_file(conn, json_path):
    """Load one extracted JSON file into the database."""
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    header = data.get("header", {})
    dmls   = data.get("dmls", [])
    meta   = data.get("extraction_meta", {})

    source_file = meta.get("source_file") or json_path.name
    facility    = header.get("facility_name", "Unknown")
    well        = header.get("well_no", "Unknown")

    cursor = conn.cursor()

    # Check for duplicate
    existing_id = inspection_exists(cursor, source_file)
    if existing_id:
        log.warning("SKIP (already ingested): {} [InspectionID={}]".format(
            source_file, existing_id))
        return False

    # Insert header
    inspection_id = insert_inspection(cursor, header, meta)
    log.info("  Inserted Inspection ID {}: {} | {}".format(
        inspection_id, facility, well))

    # Insert DML measurements
    dml_count = insert_dmls(cursor, inspection_id, dmls)
    log.info("  Inserted {} DML measurements".format(dml_count))

    # Insert parts + thickness history
    hist_count = insert_thickness_history(cursor, inspection_id, header, dmls)
    log.info("  Inserted {} thickness history records".format(hist_count))

    # Flag critical alerts
    critical_dmls = [d for d in dmls
                     if (d.get("min_wall_thickness") or 9) < 0.100
                     or d.get("critical_flag")]
    if critical_dmls:
        log.warning("  CRITICAL ALERT: {} DML(s) below 0.100 inch!".format(
            len(critical_dmls)))
        for d in critical_dmls:
            log.warning("    -> DML-{} | UT: {} | RT: {}".format(
                d.get("dml_number"),
                d.get("ut_thickness"),
                d.get("rt_thickness")))

    conn.commit()
    return True


# ── Main ───────────────────────────────────────────────────────────────────
def run():
    json_files = sorted(PROCESSED_FOLDER.glob("*.json"))
    if not json_files:
        log.info("No JSON files found in {}".format(PROCESSED_FOLDER))
        return

    log.info("Found {} JSON file(s) to ingest".format(len(json_files)))
    log.info("Target: {}.{}".format(SQL_SERVER, SQL_DATABASE))
    log.info("=" * 60)

    try:
        conn = get_connection()
        log.info("Connected to {} successfully".format(SQL_SERVER))
    except Exception as e:
        log.error("Database connection failed: {}".format(e))
        return

    success = 0
    skipped = 0
    failed  = 0

    for json_path in json_files:
        log.info("Processing: {}".format(json_path.name))
        try:
            result = process_json_file(conn, json_path)
            if result:
                success += 1
            else:
                skipped += 1
        except Exception as e:
            log.error("FAILED: {} — {}".format(json_path.name, e))
            conn.rollback()
            failed += 1

    conn.close()

    log.info("=" * 60)
    log.info("Ingestion complete.")
    log.info("  Inserted: {}".format(success))
    log.info("  Skipped (duplicates): {}".format(skipped))
    log.info("  Failed: {}".format(failed))


if __name__ == "__main__":
    run()
