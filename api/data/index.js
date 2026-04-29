/**
 * Devon Energy – Asset Integrity Dashboard
 * /api/data  –  GET  –  returns all dashboard data from SQL Server
 *
 * Environment variables required (set in Azure SWA configuration):
 *   SQL_SERVER    e.g. AZUMSDBSQ070D
 *   SQL_DATABASE  e.g. XRayImageAnalysis
 *   SQL_USERNAME  e.g. xapidbread
 *   SQL_PASSWORD  e.g. XRayApi2026!Read
 */

const sql = require('mssql');

const getConfig = () => ({
  server:   process.env.SQL_SERVER,
  database: process.env.SQL_DATABASE,
  user:     process.env.SQL_USERNAME,
  password: process.env.SQL_PASSWORD,
  options: {
    encrypt:                true,
    trustServerCertificate: true,   // self-signed cert on dev DB
    enableArithAbort:       true,
  },
  connectionTimeout: 30000,
  requestTimeout:    30000,
});

// ── CORS helper ───────────────────────────────────────────────────────────────
const CORS = {
  'Access-Control-Allow-Origin':  '*',
  'Access-Control-Allow-Methods': 'GET, OPTIONS',
  'Access-Control-Allow-Headers': 'Content-Type',
  'Content-Type':                 'application/json',
};

module.exports = async function (context, req) {
  if (req.method === 'OPTIONS') {
    context.res = { status: 200, headers: CORS, body: '' };
    return;
  }

  // Validate env vars
  if (!process.env.SQL_SERVER || !process.env.SQL_USERNAME) {
    context.res = {
      status: 500, headers: CORS,
      body: JSON.stringify({ error: 'Database not configured. Contact administrator.' }),
    };
    return;
  }

  let pool;
  try {
    pool = await sql.connect(getConfig());

    // ── 1. Summary metrics ──────────────────────────────────────────────────
    const metricsResult = await pool.request().query(`
      SELECT
        (SELECT COUNT(DISTINCT FacilityName) FROM Inspections)                          AS facilities,
        (SELECT COUNT(*)                     FROM Inspections)                          AS inspections,
        (SELECT COUNT(*)                     FROM DML_Measurements)                     AS totalDMLs,
        (SELECT COUNT(*)                     FROM DML_Measurements WHERE CriticalFlag=1) AS criticalCount,
        (SELECT COUNT(*)                     FROM DML_Measurements
           WHERE MinWallThickness >= 0.100 AND MinWallThickness < 0.110)                AS nearCriticalCount,
        (SELECT MAX(ExaminationDate)         FROM Inspections)                          AS lastInspection
    `);
    const metrics = metricsResult.recordset[0];

    // ── 2. Critical & near-critical DML alerts ──────────────────────────────
    const alertsResult = await pool.request().query(`
      SELECT TOP 100
        i.FacilityName,
        i.WellNo,
        i.WorkOrderNo,
        i.ExaminationDate,
        d.DMLNumber,
        d.PipeComponentDescription,
        d.MinWallThickness,
        d.UTThickness,
        d.RTThickness,
        d.Criteria,
        d.CriticalFlag,
        d.Circuit
      FROM DML_Measurements d
      JOIN Inspections i ON d.InspectionID = i.InspectionID
      WHERE d.MinWallThickness IS NOT NULL AND d.MinWallThickness < 0.130
      ORDER BY d.MinWallThickness ASC
    `);
    const alerts = alertsResult.recordset;

    // ── 3. Facility summaries ───────────────────────────────────────────────
    const facResult = await pool.request().query(`
      SELECT
        i.FacilityName,
        MAX(i.WorkOrderNo)     AS WorkOrderNo,
        MAX(i.ServiceProvider) AS ServiceProvider,
        MIN(i.ExaminationDate) AS FirstDate,
        MAX(i.ExaminationDate) AS LastDate,
        COUNT(DISTINCT i.WellNo)  AS WellCount,
        COUNT(d.DMLID)            AS TotalDMLs,
        MAX(CASE
          WHEN d.CriticalFlag = 1                                     THEN 5
          WHEN d.MinWallThickness < 0.110                             THEN 4
          WHEN d.Criteria = 'Severe'                                  THEN 3
          WHEN d.Criteria = 'Moderate'                                THEN 2
          WHEN d.Criteria IN ('Minor','Anomaly','As-Examined')        THEN 1
          ELSE 0 END)                                                 AS SeverityRank,
        MAX(CASE WHEN d.CriticalFlag = 1 THEN 1 ELSE 0 END)          AS HasCritical,
        MIN(d.MinWallThickness)                                        AS MinUT
      FROM Inspections i
      LEFT JOIN DML_Measurements d ON i.InspectionID = d.InspectionID
      GROUP BY i.FacilityName
      ORDER BY MAX(CASE WHEN d.CriticalFlag=1 THEN 1 ELSE 0 END) DESC,
               COUNT(d.DMLID) DESC
    `);
    const facilities = facResult.recordset.map(f => ({
      ...f,
      HighestCriteria: rankToCriteria(f.SeverityRank),
    }));

    // ── 4. Inspection records (for data table & charts) ─────────────────────
    const inspResult = await pool.request().query(`
      SELECT
        i.InspectionID,
        i.FacilityName,
        i.WellNo,
        i.WorkOrderNo,
        i.ExaminationDate,
        i.ServiceProvider,
        i.CriteriaSummary,
        i.PipingSystem,
        i.PipingCircuit,
        COUNT(d.DMLID)                                              AS DMLCount,
        MIN(d.MinWallThickness)                                     AS MinUT,
        MAX(CASE WHEN d.CriticalFlag=1 THEN 1 ELSE 0 END)          AS HasCritical,
        MAX(CASE
          WHEN d.CriticalFlag=1                              THEN 5
          WHEN d.MinWallThickness < 0.110                    THEN 4
          WHEN d.Criteria='Severe'                           THEN 3
          WHEN d.Criteria='Moderate'                         THEN 2
          WHEN d.Criteria IN ('Minor','Anomaly','As-Examined') THEN 1
          ELSE 0 END)                                               AS SeverityRank
      FROM Inspections i
      LEFT JOIN DML_Measurements d ON i.InspectionID = d.InspectionID
      GROUP BY
        i.InspectionID, i.FacilityName, i.WellNo, i.WorkOrderNo,
        i.ExaminationDate, i.ServiceProvider, i.CriteriaSummary,
        i.PipingSystem, i.PipingCircuit
      ORDER BY i.ExaminationDate DESC, i.FacilityName, i.WellNo
    `);
    const inspections = inspResult.recordset.map(r => ({
      ...r,
      HighestCriteria: rankToCriteria(r.SeverityRank),
    }));

    // ── 5. Thickness baseline (min UT per inspection for charts) ────────────
    const baseResult = await pool.request().query(`
      SELECT TOP 200
        i.FacilityName,
        i.WellNo,
        MIN(d.MinWallThickness) AS MinUT,
        MAX(CASE WHEN d.CriticalFlag=1 THEN 1 ELSE 0 END) AS HasCritical,
        MAX(CASE
          WHEN d.CriticalFlag=1              THEN 5
          WHEN d.MinWallThickness < 0.110    THEN 4
          WHEN d.Criteria='Severe'           THEN 3
          WHEN d.Criteria='Moderate'         THEN 2
          ELSE 1 END)                                      AS SeverityRank
      FROM Inspections i
      JOIN DML_Measurements d ON i.InspectionID = d.InspectionID
      WHERE d.MinWallThickness IS NOT NULL
      GROUP BY i.InspectionID, i.FacilityName, i.WellNo
      ORDER BY MIN(d.MinWallThickness) ASC
    `);
    const baseline = baseResult.recordset.map(r => ({
      ...r,
      HighestCriteria: rankToCriteria(r.SeverityRank),
    }));

    // ── Build response ──────────────────────────────────────────────────────
    context.res = {
      status:  200,
      headers: CORS,
      body: JSON.stringify({
        metrics:     { ...metrics, generatedAt: new Date().toISOString() },
        alerts,
        facilities,
        inspections,
        baseline,
      }),
    };

  } catch (err) {
    context.log.error('Data API error:', err.message);
    context.res = {
      status:  502,
      headers: CORS,
      body: JSON.stringify({ error: 'Database query failed: ' + err.message }),
    };
  } finally {
    if (pool) { try { await pool.close(); } catch (_) {} }
  }
};

function rankToCriteria(rank) {
  if (rank >= 5) return 'Critical';
  if (rank >= 4) return 'Near-Critical';
  if (rank >= 3) return 'Severe';
  if (rank >= 2) return 'Moderate';
  if (rank >= 1) return 'Minor';
  return 'Unknown';
}
