# Savage4696 · Receiving Manager (RCV)
> **CUBE Buildathon 2026 · Track 01 Submission Index**

Welcome to the official submission index for **Savage4696** (Track 01: Inbound Receiving Manager).

---

## Deliverables & Layout

```
submissions/Savage4696/
├── README.md               ← this index: candidate identity, links, verification guide
├── 01-customer-letter.md   ← customer perspective & ROI narrative
├── 02-prfaq.md             ← Amazon-style Working Backwards PR/FAQ with hard operational questions
├── 03-one-pager.md         ← metrics table, operational SLAs & kill condition
├── CLAUDE.md               ← durable constraints, engineering rules, forbidden language
├── build-brief.md          ← scope, problem understanding, 5-stage commerce chain
├── build-log.md            ← verified commit history, engineering iterations, audit notes
├── eval-report.md          ← 50-unit held-out evaluation report, dual-human Kappa, per-check FP/FN
└── contract/
    └── evidence-contract.json ← fixed CUBE evidence contract schema & sample sealed record
```

---

## Submission Status Matrix

| Phase | Deliverable | Location | Status |
|---|---|---|---|
| **Face 1** | Customer letter, PR/FAQ, One-pager | [`01-customer-letter.md`](01-customer-letter.md), [`02-prfaq.md`](02-prfaq.md), [`03-one-pager.md`](03-one-pager.md) | **Completed** |
| **Face 2** | Durable Engineering Guidelines | [`CLAUDE.md`](CLAUDE.md) | **Completed** |
| **Face 3** | Headless Agent & CLI on Fixtures | [`receiving_manager/`](../../receiving_manager/), CLI: `receiving-manager inspect` | **Completed** |
| **Face 4** | 50-Unit Held-Out Eval Report | [`eval-report.md`](eval-report.md), CLI: `receiving-manager evaluate` | **Completed** |
| **Face 5** | Live Evidence Dashboard | `receiving_manager/static/index.html` (Vercel & localhost:8000) | **Completed** |
| **Face 6** | Cross-Pod Evidence Contract | [`contract/evidence-contract.json`](contract/evidence-contract.json) | **Completed** |

---

## Kill Condition

> *"If an automated receiving verdict cannot cite cryptographic photo hashes and deterministically prove PO quantity/SKU compliance before dock staging, the shipment MUST yield UNCERTAIN and route to secondary laser verification; automated line pass without immutable evidence is forbidden."*

---

## Verification & Quick-Start

1. **Verify Held-Out Vision Evaluation (50 Units)**:
   ```bash
   receiving-manager evaluate
   ```
2. **Verify Deterministic Rules Regression Suite (24 Scenarios)**:
   ```bash
   receiving-manager scenarios
   ```
3. **Verify Cross-Pod Integrations (Prep, Returns, Recovery)**:
   ```bash
   receiving-manager integrate --pod status
   receiving-manager integrate --pod prep --unit UNIT-0005
   receiving-manager integrate --pod returns --unit UNIT-0010 --sku SKU-CANDLE-3
   receiving-manager integrate --pod recovery
   ```
4. **Run All Unit & Integration Tests**:
   ```bash
   pytest -v
   ```
5. **Launch Web Inspection Dashboard**:
   ```bash
   receiving-manager serve --port 8000
   ```
