# This is a Data Engineering project that ETL oil and gas frac stages

This repository contains a complete, Data Lakehouse implementation build on Databricks, including SQL datasets, notebooks on SQL and Python, pipelines and PowerBI. This is an End-to-End project, From data ingestion and transformation to analytics-ready data products.

# Architecture

## Bronze Layer



CLOUD STORAGE (ADLS / S3)                       │
Raw JSON / CSV / Parquet landing zone                  │

│ Auto Loader (cloudFiles)
│ Schema evolution + checkpoint
▼

BRONZE LAYER
- Raw data preserved as-is (append-only) 
- Metadata columns: _ingested_at, _source_file, _batch_id
- Delta table with OPTIMIZE WRITE + AUTO COMPACT
catalog.bronze.{entity}

│ ForeachBatch streaming merge
│ Cleanse → Dedup → SCD2 MERGE INTO
▼

SILVER LAYER
- Validated, deduplicated, standardised records
- SCD Type 2: effective_date / end_date / is_current
-  Full change history preserved
- Late-arriving data handled via watermark

catalog.silver.{entity}

│  Batch aggregation
│  OPTIMIZE + ZORDER BY BI filter columns
▼


GOLD LAYER
- Business-level fact & dimension tables
- Partitioned + Z-Ordered for Power BI / Tableau direct query
- daily_sales_summary, customer_360, 
catalog.gold.{aggregation}

│
▼

UNITY CATALOG GOVERNANCE LAYER                        │
- Catalog per environment: medallion_dev / staging / prod
- Role-based access: data_engineer / analyst / viewer
- Column-level security & row filters (configurable)
- Data lineage tracked automatically

│
▼

DATA QUALITY & MONITORING
- Cross-layer row count reconciliation
- Null checks on critical columns
- Business rule SQL predicates
- Schema drift detection
- Pipeline metrics written to monitoring. pipeline_metrics 
- Critical failures halt the Databricks Job via exception
