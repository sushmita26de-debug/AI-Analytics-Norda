# NORDA Monthly Sales Analytics: AI-Assisted Pipeline

An AI-assisted workflow (built with Claude Code) that turns the monthly shop-system export into checked numbers, a data model and stakeholder reports. NORDA sells electronics across Europe through its own shop, its app and marketplaces.

**Goal:** speed up the monthly analysis without losing trust. Every number is checked before it reaches a stakeholder.

## How it works

Each step is a Claude Code skill. `/pipeline` runs them in this order:

| Step | Skill | What it does |
|---|---|---|
| 1 | `/profile` | Checks the new raw delivery for known data issues and changes from history |
| 2 | `/clean` | Fixes data issues and standardises formats, then appends to the combined history |
| 3 | `/mart` | Builds a star schema (2 facts, 4 dimensions) for reporting |
| 4 | `/quality-gate` | Computes every number twice (SQL and pandas) and traces sample orders from raw to model |
| 5 | `/html-dashboard` | Builds an offline interactive HTML dashboard |
| 6 | `/ppt-review` | Builds the monthly PowerPoint review deck |
| 7 | `/powerbi` | Refreshes the Power BI report and checks it against SQL |

The quality gate always runs before any report. If a step fails, the pipeline stops and restores the last good version.

## Folder structure

```
data/raw/        monthly exports (never modified)
data/clean/      cleaned data, per month plus combined history
data/mart/       star schema for reporting
knowledge/       business context, metadata, metrics, quality rules
reports/         html dashboard, ppt deck, Power BI project
runs/<month>/    logs and check results for every run
.claude/skills/  the pipeline steps
```

## Usage

1. Put the new export in `data/raw/<YYYY-MM>/`
2. In Claude Code, run `/pipeline`
3. Review the check results in `runs/<YYYY-MM>/`

## Tech

Claude Code · SQL · Python (pandas) · Power BI · PowerPoint · HTML
