# XRayImageAnalysis

## Overview
An AI-powered asset integrity application for Devon Energy that analyzes digital radiography (X-ray) images of pipeline parts and equipment to:
- Identify pipeline component types (Elbows, Valves, Meters, PUPs, Tees, etc.)
- Extract wall thickness measurements from X-ray images and inspection documents
- Track wall thickness degradation over time
- Predict equipment and pipeline failure caused by corrosion and other damage
- Prevent spills and unwanted emissions through predictive maintenance
- Prioritize repairs based on rate of wall thickness decline

---

## Project Structure
```
XRayImageAnalysis/
├── data/
│   ├── raw/          # Original X-ray images and PDF inspection reports
│   ├── processed/    # Cleaned and normalized data
│   └── annotations/  # Labeled part types and measurements
├── models/           # AI/ML models for predictive analysis
├── src/
│   ├── ingestion/    # PDF and image upload/parsing scripts
│   ├── extraction/   # Wall thickness and metadata extraction
│   ├── analysis/     # Trend analysis and prediction logic
│   └── reporting/    # Output and dashboard generation
├── tests/            # Unit and integration tests
├── docs/             # Project documentation
├── .gitignore
└── README.md
```

---

## Tech Stack
- **Cloud:** Microsoft Azure
  - Azure Blob Storage — X-ray image and PDF storage
  - Azure SQL Server — azumsdbsq070p
- **Database:** SQL Server 2022
- **Languages & Frameworks:**
  - Python — image processing, AI/ML, data extraction
  - SQL — data querying and reporting
  - Node.js — backend API layer
  - React / Dash — frontend dashboard
- **Version Control:** GitHub (this repository)

---

## Document Type
**Asset Integrity Digital Radiography (X-Ray) Report**

Reports are structured in three sections:
1. **Header** — facility info, inspection metadata, technician details
2. **Key** — grading scale criteria
3. **Chart** — per-component measurements and grading

---

## Grading Scale
| Grade | Criteria |
|---|---|
| Critical 🔴 | Remaining wall thickness < 0.100 inch — Devon PIC notified ASAP |
| Severe 🟠 | 51% or greater wall loss |
| Moderate 🟡 | 26% to 50% wall loss |
| Minor 🟡 | 0% to 25% wall loss |
| Anomaly ⬜ | Weld indications suspected to fail weld quality exam |
| As-Examined ⬜ | All nominal wall thickness not meeting above criteria |

---

## Database Schema
Four core tables:
- **Inspections** — Header section data per report
- **DML_Measurements** — Chart section data per report
- **Parts** — Master registry of unique physical components
- **Thickness_History** — Time-series wall thickness data for predictive analysis

---

## Development Team
- Ken Chiba — Domain Expert / Project Owner (Devon Energy)
- Claude (Anthropic) — AI Developer / Analyst

---

## Status
🚧 **In Development** — Training and database provisioning in progress.

---

*Devon Energy Corporation — DBBU Operations*
