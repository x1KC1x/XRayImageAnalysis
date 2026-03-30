"""
XRayImageAnalysis - PDF Extraction Script
File: src/extraction/extractor.py
Description: Extracts header, chart, and image data from Asset Integrity
             Digital Radiography PDF reports and inserts into SQL Server.
"""

import os
import re
import json
import logging
import base64
from datetime import datetime
from pathlib import Path

import pdfplumber
import anthropic
import pyodbc
import pandas as pd
from dotenv import load_dotenv
from PIL import Image
import io

# ── Load environment variables ──────────────────────────────────────────────
load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
SQL_SERVER        = os.getenv("SQL_SERVER")
SQL_DATABASE      = os.getenv("SQL_DATABASE")
SQL_USERNAME      = os.getenv("SQL_USERNAME")
SQL_PASSWORD      = os.getenv("SQL_PASSWORD")
SQL_DRIVER        = os.getenv("SQL_DRIVER", "ODBC Driver 17 for SQL Server")
INPUT_FOLDER      = os.getenv("INPUT_FOLDER", "data/raw")
OUTPUT_FOLDER     = os.getenv("OUTPUT_FOLDER", "data/processed")
LOG_FOLDER        = os.getenv("LOG_FOLDER", "logs")
ENVIRONMENT       = os.getenv("ENVIRONMENT", "dev")

# ── Logging setup ────────────────────────────────────────────────────────────
os.makedirs(LOG_FOLDER, exist_ok=True)
log_file = os.path.join(LOG_FOLDER, f"extraction_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(log_file),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)

# ── Anthropic client ─────────────────────────────────────────────────────────
claude = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)


# ═══════════════════════════════════════════════════════════════════════════════
# DATABASE
# ═══════════════════════════════════════════════════════════════════════════════

def get_db_connection():
    """Create and return a SQL Server connection."""
    conn_str = (
        f"DRIVER={{{SQL_DRIVER}}};"
        f"SERVER={SQL_SERVER};"
        f"DATABASE={SQL_DATABASE};"
        f"UID={SQL_USERNAME};"
        f"PWD={SQL_PASSWORD};"
        f"TrustServerCertificate=yes;"
    )
    try:
        conn = pyodbc.connect(conn_str)
        log.info("Database connection established.")
        return conn
    except Exception as e:
        log.error(f"Database connection failed: {e}")
        return None


def insert_inspection(conn, data: dict) -> int:
    """Insert header data into Inspections table. Returns InspectionID."""
    sql = """
        INSERT INTO Inspections (
            OperationsRoute, WorkOrderNo, FacilityName, WellNo, FixedAsset,
            NonHeated, Heated, ManufactureDate, Manufacture, SerialNo,
            NBIC, NBICNo, PipingSystem, PipingCircuit, ExaminationDate,
            ServiceProvider, RTTechnicianName, UTTechnicianName, SourceType,
            ExposureCount, ExposureTime, FramesPerSecond, SourceToDDA,
            DMLCount, CriteriaSummary, CriteriaPercentage, DMLMonitorRecs,
            TimeInterval, ReviewerName, ReviewerDate
        )
        OUTPUT INSERTED.InspectionID
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """
    try:
        cursor = conn.cursor()
        cursor.execute(sql, (
            data.get("OperationsRoute"),
            data.get("WorkOrderNo"),
            data.get("FacilityName"),
            data.get("WellNo"),
            data.get("FixedAsset"),
            data.get("NonHeated", 0),
            data.get("Heated", 0),
            data.get("ManufactureDate"),
            data.get("Manufacture"),
            data.get("SerialNo"),
            data.get("NBIC"),
            data.get("NBICNo"),
            data.get("PipingSystem"),
            data.get("PipingCircuit"),
            data.get("ExaminationDate"),
            data.get("ServiceProvider"),
            data.get("RTTechnicianName"),
            data.get("UTTechnicianName"),
            data.get("SourceType"),
            data.get("ExposureCount"),
            data.get("ExposureTime"),
            data.get("FramesPerSecond"),
            data.get("SourceToDDA"),
            data.get("DMLCount"),
            data.get("CriteriaSummary"),
            data.get("CriteriaPercentage"),
            data.get("DMLMonitorRecs"),
            data.get("TimeInterval"),
            data.get("ReviewerName"),
            data.get("ReviewerDate"),
        ))
        inspection_id = cursor.fetchone()[0]
        conn.commit()
        log.info(f"Inserted Inspection ID: {inspection_id}")
        return inspection_id
    except Exception as e:
        log.error(f"Failed to insert inspection: {e}")
        conn.rollback()
        return None


def insert_dml_measurement(conn, inspection_id: int, row: dict):
    """Insert a single chart row into DML_Measurements table."""
    sql = """
        INSERT INTO DML_Measurements (
            InspectionID, DMLNumber, DMNumber, PipeComponentDescription,
            Size, Schedule, ValveType, ValveMfg, Criteria, CriticalFlag,
            AnomalyWeld, UTThickness, RTThickness, MinWallThickness
        )
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """
    try:
        ut  = row.get("UTThickness")
        rt  = row.get("RTThickness")
        # Calculate minimum wall thickness excluding None values
        vals = [v for v in [ut, rt] if v is not None]
        min_wt = min(vals) if vals else None

        cursor = conn.cursor()
        cursor.execute(sql, (
            inspection_id,
            row.get("DMLNumber"),
            row.get("DMNumber"),
            row.get("PipeComponentDescription"),
            row.get("Size"),
            row.get("Schedule"),
            row.get("ValveType"),
            row.get("ValveMfg"),
            row.get("Criteria"),
            1 if str(row.get("Criteria", "")).upper() == "CRITICAL" else 0,
            row.get("AnomalyWeld"),
            ut,
            rt,
            min_wt,
        ))
        conn.commit()
        log.info(f"  Inserted DML {row.get('DMLNumber')} - {row.get('Criteria')}")
    except Exception as e:
        log.error(f"  Failed to insert DML {row.get('DMLNumber')}: {e}")
        conn.rollback()


def upsert_part(conn, inspection_id: int, row: dict, facility: str, well: str):
    """Insert into Parts table if part doesn't already exist."""
    sql_check = """
        SELECT PartID FROM Parts
        WHERE FacilityName=? AND WellNo=? AND DMLNumber=?
    """
    sql_insert = """
        INSERT INTO Parts (
            FacilityName, WellNo, DMLNumber, DMNumber,
            PartType, PipeComponentDescription, Size, Schedule
        )
        OUTPUT INSERTED.PartID
        VALUES (?,?,?,?,?,?,?,?)
    """
    try:
        cursor = conn.cursor()
        cursor.execute(sql_check, (facility, well, row.get("DMLNumber")))
        existing = cursor.fetchone()
        if existing:
            return existing[0]

        cursor.execute(sql_insert, (
            facility,
            well,
            row.get("DMLNumber"),
            row.get("DMNumber"),
            row.get("PartType"),
            row.get("PipeComponentDescription"),
            row.get("Size"),
            row.get("Schedule"),
        ))
        part_id = cursor.fetchone()[0]
        conn.commit()
        log.info(f"  Inserted Part ID: {part_id} for DML {row.get('DMLNumber')}")
        return part_id
    except Exception as e:
        log.error(f"  Failed to upsert part for DML {row.get('DMLNumber')}: {e}")
        conn.rollback()
        return None


def insert_thickness_history(conn, part_id: int, inspection_id: int, row: dict, exam_date):
    """Insert wall thickness history record."""
    sql = """
        INSERT INTO Thickness_History (
            PartID, InspectionID, ExaminationDate,
            UTThickness, RTThickness, MinWallThickness, Criteria
        )
        VALUES (?,?,?,?,?,?,?)
    """
    try:
        ut   = row.get("UTThickness")
        rt   = row.get("RTThickness")
        vals = [v for v in [ut, rt] if v is not None]
        min_wt = min(vals) if vals else None

        cursor = conn.cursor()
        cursor.execute(sql, (
            part_id, inspection_id, exam_date, ut, rt, min_wt,
            row.get("Criteria")
        ))
        conn.commit()
    except Exception as e:
        log.error(f"  Failed to insert thickness history for DML {row.get('DMLNumber')}: {e}")
        conn.rollback()


# ═══════════════════════════════════════════════════════════════════════════════
# PDF TEXT EXTRACTION
# ═══════════════════════════════════════════════════════════════════════════════

def extract_text_from_pdf(pdf_path: str) -> list:
    """Extract text from all pages of a PDF. Returns list of page texts."""
    pages = []
    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages):
            text = page.extract_text() or ""
            pages.append({"page": i + 1, "text": text})
    log.info(f"Extracted text from {len(pages)} pages in {Path(pdf_path).name}")
    return pages


def extract_images_from_pdf(pdf_path: str) -> list:
    """Extract images from PDF pages. Returns list of base64 encoded images."""
    images = []
    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages):
            # Convert page to image
            img = page.to_image(resolution=150)
            img_byte_arr = io.BytesIO()
            img.original.save(img_byte_arr, format='PNG')
            img_byte_arr.seek(0)
            b64 = base64.standard_b64encode(img_byte_arr.read()).decode('utf-8')
            images.append({"page": i + 1, "base64": b64})
    log.info(f"Extracted {len(images)} page images from {Path(pdf_path).name}")
    return images


# ═══════════════════════════════════════════════════════════════════════════════
# CLAUDE AI EXTRACTION
# ═══════════════════════════════════════════════════════════════════════════════

def extract_header_with_claude(page_text: str) -> dict:
    """Use Claude to extract header fields from page 1 text."""
    prompt = f"""
You are an expert at reading Asset Integrity Digital Radiography (X-Ray) reports for Devon Energy.

Extract the following fields from the report header section below.
Return ONLY a valid JSON object with these exact keys. Use null for missing values.

Fields to extract:
- OperationsRoute
- WorkOrderNo
- FacilityName
- WellNo
- FixedAsset
- NonHeated (true/false)
- Heated (true/false)
- ManufactureDate
- Manufacture
- SerialNo
- NBIC
- NBICNo
- PipingSystem
- PipingCircuit
- ExaminationDate (format: YYYY-MM-DD if possible)
- ServiceProvider
- RTTechnicianName
- UTTechnicianName
- SourceType
- ExposureCount (integer)
- ExposureTime
- FramesPerSecond
- SourceToDDA
- DMLCount (integer)
- CriteriaSummary
- CriteriaPercentage (decimal number only, e.g. 34.0)
- DMLMonitorRecs (integer)
- TimeInterval
- ReviewerName
- ReviewerDate (format: YYYY-MM-DD if possible)

Report text:
{page_text}

Return ONLY the JSON object, no other text.
"""
    try:
        response = claude.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1000,
            messages=[{"role": "user", "content": prompt}]
        )
        raw = response.content[0].text.strip()
        # Strip markdown code fences if present
        raw = re.sub(r'^```json|^```|```$', '', raw, flags=re.MULTILINE).strip()
        return json.loads(raw)
    except Exception as e:
        log.error(f"Claude header extraction failed: {e}")
        return {}


def extract_chart_with_claude(page_text: str) -> list:
    """Use Claude to extract chart rows from report text."""
    prompt = f"""
You are an expert at reading Asset Integrity Digital Radiography (X-Ray) reports for Devon Energy.

Extract ALL rows from the chart/table section of the report below.
Each row represents a pipeline component (DML measurement).

Return ONLY a valid JSON array of objects. Each object must have these exact keys.
Use null for missing values. Do NOT include the 1.000 inch reference ball as a thickness value.

Keys for each row:
- DMLNumber (string, e.g. "001")
- DMNumber (string, e.g. "DM-01")
- PipeComponentDescription (full description as written)
- Size (pipe size, e.g. "3\"", "4\"")
- Schedule (e.g. "SCH80", "XH", "STD")
- ValveType (if applicable, else null)
- ValveMfg (valve manufacturer if mentioned, e.g. "BALON", "WCB", "WARREN", else null)
- PartType (classify as one of: "Elbow", "Valve", "Meter", "PUP", "Tee", "Reducer", 
           "Union", "Flange", "Pipe/Olet", "Clamp", "Other")
- Criteria (exactly as written: "CRITICAL", "SEVERE", "MODERATE", "MINOR", 
           "ANOMALY", "AS EXAMINED")
- AnomalyWeld (anomaly or weld description if applicable, else null)
- UTThickness (decimal number only, e.g. 0.292, else null)
- RTThickness (decimal number only, e.g. 0.287, else null)

Report text:
{page_text}

Return ONLY the JSON array, no other text.
"""
    try:
        response = claude.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1000,
            messages=[{"role": "user", "content": prompt}]
        )
        raw = response.content[0].text.strip()
        raw = re.sub(r'^```json|^```|```$', '', raw, flags=re.MULTILINE).strip()
        rows = json.loads(raw)
        log.info(f"  Claude extracted {len(rows)} chart rows")
        return rows
    except Exception as e:
        log.error(f"Claude chart extraction failed: {e}")
        return []


def analyze_xray_image_with_claude(b64_image: str, dml_label: str) -> dict:
    """Use Claude vision to analyze an X-ray image and extract measurements."""
    prompt = f"""
You are an expert at analyzing Asset Integrity Digital Radiography (X-Ray) images for Devon Energy.

Analyze this X-ray image labeled {dml_label} and extract the following.
Return ONLY a valid JSON object with these exact keys. Use null for missing values.

- DMLNumber (e.g. "001")
- PartType (one of: "Elbow", "Valve", "Meter", "PUP", "Tee", "Reducer", 
           "Union", "Flange", "Pipe/Olet", "Clamp", "Other")
- WallThicknessMeasurements (array of all numeric thickness values found, 
  EXCLUDING the 1.000 inch reference ball)
- MinWallThickness (the smallest value from WallThicknessMeasurements)
- FacilityName (from image header text if visible)
- WellName (from image header text if visible)
- InspectionDate (from image header text if visible)
- ConnectionType (best guess: "Welded", "Grooved", "Flanged", or "Unknown")
- Notes (any anomalies, ANOMALY labels, or other observations)

Return ONLY the JSON object, no other text.
"""
    try:
        response = claude.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1000,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": b64_image
                        }
                    },
                    {"type": "text", "text": prompt}
                ]
            }]
        )
        raw = response.content[0].text.strip()
        raw = re.sub(r'^```json|^```|```$', '', raw, flags=re.MULTILINE).strip()
        return json.loads(raw)
    except Exception as e:
        log.error(f"Claude image analysis failed for {dml_label}: {e}")
        return {}


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN PROCESSING
# ═══════════════════════════════════════════════════════════════════════════════

def process_pdf(pdf_path: str, conn=None):
    """
    Full pipeline for a single PDF:
    1. Extract text from all pages
    2. Extract header data (page 1)
    3. Extract chart data (page 1 and 2)
    4. Extract and analyze X-ray images
    5. Insert all data into SQL Server
    6. Save JSON output to processed folder
    """
    log.info(f"{'='*60}")
    log.info(f"Processing: {Path(pdf_path).name}")
    log.info(f"{'='*60}")

    result = {
        "pdf_file": Path(pdf_path).name,
        "processed_at": datetime.now().isoformat(),
        "header": {},
        "chart_rows": [],
        "image_analyses": [],
        "errors": []
    }

    # Step 1: Extract text
    pages = extract_text_from_pdf(pdf_path)
    if not pages:
        log.error("No text extracted from PDF.")
        return result

    # Step 2: Extract header (page 1)
    log.info("Extracting header data...")
    full_text_p1 = pages[0]["text"]
    # Include page 2 text if available for chart continuation
    full_text_p2 = pages[1]["text"] if len(pages) > 1 else ""
    combined_text = full_text_p1 + "\n" + full_text_p2

    header = extract_header_with_claude(full_text_p1)
    result["header"] = header
    log.info(f"  Facility: {header.get('FacilityName')} | Well: {header.get('WellNo')} | Date: {header.get('ExaminationDate')}")

    # Step 3: Extract chart rows
    log.info("Extracting chart data...")
    chart_rows = extract_chart_with_claude(combined_text)
    result["chart_rows"] = chart_rows

    # Step 4: Extract and analyze X-ray images
    log.info("Extracting and analyzing X-ray images...")
    images = extract_images_from_pdf(pdf_path)
    # Analyze pages 2+ (X-ray image pages)
    for img_data in images[1:]:
        label = f"page {img_data['page']}"
        analysis = analyze_xray_image_with_claude(img_data["base64"], label)
        if analysis:
            result["image_analyses"].append(analysis)
            log.info(f"  Page {img_data['page']}: {analysis.get('PartType')} | Min thickness: {analysis.get('MinWallThickness')}")

    # Step 5: Save JSON output
    os.makedirs(OUTPUT_FOLDER, exist_ok=True)
    out_file = os.path.join(
        OUTPUT_FOLDER,
        Path(pdf_path).stem + "_extracted.json"
    )
    with open(out_file, "w") as f:
        json.dump(result, f, indent=2, default=str)
    log.info(f"JSON output saved: {out_file}")

    # Step 6: Insert into database (if connection available)
    if conn:
        log.info("Inserting into database...")
        inspection_id = insert_inspection(conn, header)
        if inspection_id:
            exam_date = header.get("ExaminationDate")
            facility  = header.get("FacilityName")
            well      = header.get("WellNo")
            for row in chart_rows:
                insert_dml_measurement(conn, inspection_id, row)
                part_id = upsert_part(conn, inspection_id, row, facility, well)
                if part_id:
                    insert_thickness_history(conn, part_id, inspection_id, row, exam_date)
    else:
        log.warning("No database connection — data saved to JSON only.")

    log.info(f"Completed: {Path(pdf_path).name}")
    return result


def process_folder(folder_path: str, conn=None):
    """Process all PDFs in a folder (batch mode)."""
    pdf_files = list(Path(folder_path).glob("*.pdf"))
    if not pdf_files:
        log.warning(f"No PDF files found in {folder_path}")
        return

    log.info(f"Found {len(pdf_files)} PDF(s) to process in {folder_path}")
    results = []
    for pdf_file in pdf_files:
        result = process_pdf(str(pdf_file), conn)
        results.append(result)

    log.info(f"Batch complete. Processed {len(results)} PDFs.")
    return results


# ═══════════════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys

    # Attempt DB connection (will be None if DB not yet provisioned)
    conn = get_db_connection() if SQL_DATABASE and SQL_DATABASE != "your_database_name_here" else None
    if not conn:
        log.warning("Running in JSON-only mode (no database connection).")

    if len(sys.argv) < 2:
        # Default: process all PDFs in input folder
        log.info(f"No file specified. Processing all PDFs in {INPUT_FOLDER}...")
        process_folder(INPUT_FOLDER, conn)
    else:
        arg = sys.argv[1]
        if os.path.isdir(arg):
            # Batch mode: process all PDFs in specified folder
            process_folder(arg, conn)
        elif os.path.isfile(arg) and arg.endswith(".pdf"):
            # Single file mode
            process_pdf(arg, conn)
        else:
            log.error(f"Invalid argument: {arg}. Provide a PDF file or folder path.")

    if conn:
        conn.close()
        log.info("Database connection closed.")