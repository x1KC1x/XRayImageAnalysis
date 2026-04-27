"""
Devon Energy — Asset Integrity X-Ray Image Analysis
Extractor: reads PDFs from data/raw, calls Devon AI Gateway,
writes structured JSON to data/processed.

Devon AI Gateway endpoint: https://aigw.dev.dvn.com/anthropic/v1/chat/claude-sonnet-latest
Auth: X-API-KEY header (reads from DEVON_GATEWAY_KEY or ANTHROPIC_API_KEY in .env)
"""

import os
import re
import json
import logging
import requests
import urllib3
import pdfplumber
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ── Setup ──────────────────────────────────────────────────────────────────
load_dotenv()

Path("logs").mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("logs/extractor.log"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)

# ── Config ─────────────────────────────────────────────────────────────────
GATEWAY_URL   = "https://aigw.dev.dvn.com/anthropic/v1/chat/claude-sonnet-latest"
GATEWAY_KEY   = os.getenv("DEVON_GATEWAY_KEY") or os.getenv("ANTHROPIC_API_KEY")
INPUT_FOLDER  = Path(os.getenv("INPUT_FOLDER",  "data/raw"))
OUTPUT_FOLDER = Path(os.getenv("OUTPUT_FOLDER", "data/processed"))
MAX_TOKENS    = 24000

if not GATEWAY_KEY:
    raise EnvironmentError(
        "No gateway key found. Set DEVON_GATEWAY_KEY in your .env file."
    )

OUTPUT_FOLDER.mkdir(parents=True, exist_ok=True)


# ── Devon AI Gateway call ──────────────────────────────────────────────────
def call_gateway(messages, system=""):
    """POST to Devon AI Gateway and return the assistant reply text."""
    headers = {
        "Content-Type": "application/json",
        "X-API-KEY": GATEWAY_KEY,
    }
    payload = {
        "max_tokens": MAX_TOKENS,
        "system": system,
        "messages": messages,
    }
    try:
        resp = requests.post(
            GATEWAY_URL, headers=headers, json=payload, timeout=120, verify=False
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("content"):
            return data["content"][0]["text"]
        elif data.get("choices"):
            return data["choices"][0]["message"]["content"]
        else:
            raise ValueError("Unexpected gateway response format: {}".format(data))
    except requests.exceptions.HTTPError as e:
        log.error("Gateway HTTP error {}: {}".format(resp.status_code, resp.text[:300]))
        raise
    except requests.exceptions.Timeout:
        log.error("Gateway request timed out after 120s")
        raise
    except Exception as e:
        log.error("Gateway call failed: {}".format(e))
        raise


# ── JSON parser ────────────────────────────────────────────────────────────
def parse_json_reply(raw):
    """Parse JSON from gateway reply, tolerant of common LLM formatting issues."""
    clean = raw.strip()
    if clean.startswith("```"):
        clean = clean.split("```")[1]
        if clean.startswith("json"):
            clean = clean[4:]
    clean = clean.strip()
    clean = re.sub(r',\s*([}\]])', r'\1', clean)
    clean = re.sub(r'//.*?\n', '\n', clean)
    return json.loads(clean)


# ── PDF text extraction ────────────────────────────────────────────────────
def extract_pdf_text(pdf_path):
    """Extract all text from a PDF using pdfplumber."""
    text = ""
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for i, page in enumerate(pdf.pages):
                page_text = page.extract_text()
                if page_text:
                    text += "\n--- Page {} ---\n{}".format(i + 1, page_text)
    except Exception as e:
        log.error("Failed to extract text from {}: {}".format(pdf_path.name, e))
        raise
    return text.strip()


# ── System prompt ──────────────────────────────────────────────────────────
SYSTEM_PROMPT = """You are an expert at extracting structured data from Devon Energy
Asset Integrity Digital Radiography (X-Ray) inspection reports.

These reports have three sections:
1. HEADER - facility and inspection metadata
2. KEY - grading scale (Critical/Severe/Moderate/Minor/Anomaly/As-Examined)
3. CHART - per-component DML measurements with wall thickness readings

Wall thickness rules:
- Always use the SMALLEST value across UT and RT readings
- EXCLUDE any 1.000 inch reference ball measurements (calibration marker)
- Critical threshold: < 0.100 inch remaining - Devon PIC must be notified immediately

You must respond ONLY with valid JSON. No preamble, no explanation, no markdown code fences."""


# ── Extraction prompts ─────────────────────────────────────────────────────
def build_header_prompt(pdf_text):
    return """Extract ONLY the header metadata from this Devon Energy inspection report.
Return ONLY this JSON object (use null for missing fields), nothing else:
{{
  "operations_route": null,
  "work_order_no": null,
  "facility_name": null,
  "well_no": null,
  "fixed_asset": null,
  "non_heated": null,
  "heated": null,
  "manufacture_date": null,
  "manufacture": null,
  "serial_no": null,
  "nbic": null,
  "nbic_no": null,
  "piping_system": null,
  "piping_circuit": null,
  "examination_date": null,
  "service_provider": null,
  "rt_technician_name": null,
  "ut_technician_name": null,
  "source_type": null,
  "exposure_count": null,
  "exposure_time": null,
  "frames_per_second": null,
  "source_to_dda": null,
  "dml_count": null,
  "criteria_summary": null,
  "criteria_percentage": null,
  "dml_monitor_recommendations": null,
  "time_interval": null,
  "reviewer_name": null,
  "reviewer_date": null
}}

REPORT TEXT:
{}""".format(pdf_text)


def build_dml_prompt(pdf_text):
    return """Extract ONLY the DML measurements table from this Devon Energy inspection report.
Return ONLY a JSON array of DML objects, nothing else. Example format:
[
  {{
    "dml_number": "001",
    "dm_number": "001",
    "circuit": "PW",
    "pipe_component_description": "4 STD Pipe",
    "size": "4",
    "schedule": "STD",
    "valve_type": null,
    "valve_mfg": null,
    "criteria": "Minor",
    "anomaly_weld": null,
    "critical_flag": false,
    "ut_thickness": 0.218,
    "rt_thickness": 0.224,
    "min_wall_thickness": 0.218,
    "part_type": "Pipe"
  }}
]

Rules:
- min_wall_thickness = smallest of ut_thickness and rt_thickness (exclude 1.000 ref ball)
- critical_flag = true if min_wall_thickness < 0.100
- part_type options: Elbow, Valve, Meter, PUP, Tee, Reducer, Pipe, Olet, Union, Clamp, Other
- Infer part_type from pipe_component_description

REPORT TEXT:
{}""".format(pdf_text)


# ── Process a single PDF ───────────────────────────────────────────────────
def process_pdf(pdf_path):
    """Extract structured data from one inspection report PDF."""
    log.info("Processing: {}".format(pdf_path.name))

    # Step 1 - extract raw text
    pdf_text = extract_pdf_text(pdf_path)
    if not pdf_text:
        raise ValueError("No text extracted from {}".format(pdf_path.name))

    # Step 2 - call Devon AI Gateway in two passes to avoid token limits
    log.info("Pass A: extracting header...")
    header_reply = call_gateway(
        [{"role": "user", "content": build_header_prompt(pdf_text)}],
        system=SYSTEM_PROMPT
    )

    log.info("Pass B: extracting DMLs...")
    dml_reply = call_gateway(
        [{"role": "user", "content": build_dml_prompt(pdf_text)}],
        system=SYSTEM_PROMPT
    )

    # Step 3 - parse header
    try:
        header_data = parse_json_reply(header_reply)
        if not isinstance(header_data, dict):
            header_data = {}
    except json.JSONDecodeError as e:
        log.error("Failed to parse header JSON: {}".format(e))
        log.debug("Header raw: {}".format(header_reply[:300]))
        raise

    # Step 4 - parse DMLs
    try:
        dml_data = parse_json_reply(dml_reply)
        if not isinstance(dml_data, list):
            dml_data = dml_data.get("dmls", [])
    except json.JSONDecodeError as e:
        log.error("Failed to parse DML JSON: {}".format(e))
        log.debug("DML raw: {}".format(dml_reply[:300]))
        raise

    # Step 5 - assemble result
    result = {
        "header": header_data,
        "dmls": dml_data,
        "extraction_meta": {
            "source_file": pdf_path.name,
            "extracted_at": datetime.utcnow().isoformat() + "Z",
            "critical_dml_count": 0,
            "near_critical_dml_count": 0
        }
    }

    # Step 6 - flag critical and near-critical alerts
    critical_dmls = []
    near_critical_dmls = []

    for d in result["dmls"]:
        mwt = d.get("min_wall_thickness")
        if mwt is not None:
            if mwt < 0.100:
                critical_dmls.append(d)
            elif mwt <= 0.110:
                near_critical_dmls.append(d)
        elif d.get("critical_flag"):
            critical_dmls.append(d)

    result["extraction_meta"]["critical_dml_count"] = len(critical_dmls)
    result["extraction_meta"]["near_critical_dml_count"] = len(near_critical_dmls)

    if critical_dmls:
        log.warning(
            "CRITICAL ALERT in {}: {} DML(s) below 0.100 inch — Devon PIC notification required!".format(
                pdf_path.name, len(critical_dmls)
            )
        )
        for d in critical_dmls:
            log.warning(
                "  -> DML-{} | UT: {} | RT: {}".format(
                    d.get("dml_number"), d.get("ut_thickness"), d.get("rt_thickness")
                )
            )

    if near_critical_dmls:
        log.warning(
            "NEAR-CRITICAL in {}: {} DML(s) between 0.100 and 0.110 inch".format(
                pdf_path.name, len(near_critical_dmls)
            )
        )

    return result


# ── Save output ────────────────────────────────────────────────────────────
def save_output(data, source_path):
    """Write extracted JSON to data/processed/<stem>.json"""
    out_path = OUTPUT_FOLDER / (source_path.stem + ".json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    log.info("Saved: {}".format(out_path))
    return out_path


# ── Main ───────────────────────────────────────────────────────────────────
def run():
    pdfs = sorted(INPUT_FOLDER.glob("*.pdf"))
    if not pdfs:
        log.info("No PDF files found in {}. Drop PDFs there and re-run.".format(INPUT_FOLDER))
        return

    log.info("Found {} PDF(s) to process".format(len(pdfs)))
    success = 0
    failed = 0

    for pdf_path in pdfs:
        try:
            data = process_pdf(pdf_path)
            save_output(data, pdf_path)
            success += 1
        except Exception as e:
            log.error("FAILED: {} — {}".format(pdf_path.name, e))
            failed += 1

    log.info("Done. {} succeeded, {} failed.".format(success, failed))


if __name__ == "__main__":
    run()