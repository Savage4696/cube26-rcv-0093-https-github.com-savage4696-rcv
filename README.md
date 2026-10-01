# RCV — AI Receiving Manager

> **AI-powered inbound inspection and evidence sealing for real-world receiving operations.**

[![Tests](https://img.shields.io/badge/tests-58%20passed-success)](tests/)
[![Python](https://img.shields.io/badge/python-3.9+-blue.svg)](pyproject.toml)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

RCV inspects inbound shipments from photographs, validates items against purchase orders and product catalogues, seals the result into a **tamper-evident evidence record**, and feeds downstream prep, packaging, and supplier recovery workflows.

---

## 1. Problem Understanding

### The Inbound Receiving Problem
In modern commerce operations (3PLs, cross-dock warehouses, and Amazon FBA prep centers), incoming pallets and cartons arrive daily from overseas factories and domestic distributors. Warehouse line operators face intense time pressure to unload trailers, perform quick visual counts, and move pallets into staging areas.

Today, inbound inspection is a **spot check at best**. Shortages, wrong SKUs, color/variant mismatches, and transit damage go unrecorded. When these defects finally surface weeks later — during individual item prep, packaging, or customer returns — it is too late:
1. **Unwinnable Supplier Disputes**: Without timestamped, photographic evidence captured at the dock, suppliers reject shortage and defect claims.
2. **Costly Downstream Penalties**: Amazon FBA charges steep inbound defect fees and unplanned prep fees for non-compliant labelling or damaged cartons.
3. **Inventory Distortions**: ERPs and WMS systems register phantom inventory, triggering stockouts and misallocated orders.

### The Five-Stage Commerce Chain
Inbound receiving is the foundational first link in the supply chain:

```text
 Supplier delivery      Inbound to Amazon     Outbound to buyer     Customer return        Money back
 ┌──────────────┐      ┌──────────────┐      ┌──────────────┐      ┌──────────────┐      ┌──────────────┐
 │ 01 Receiving │ ───▶ │ 02 Prep      │ ───▶ │ 03 Pack      │ ───▶ │ 04 Returns   │      │ 05 Recovery  │
 │ condition on │      │ compliance   │      │ contents at  │      │ condition &  │      │ reads all    │
 │ arrival      │      │ proof        │      │ seal         │      │ disposition  │      │ four → claim │
 └──────┬───────┘      └──────┬───────┘      └──────┬───────┘      └──────┬───────┘      └──────▲───────┘
        └─────────────────────┴─────────────────────┴─────────────────────┴─────────────────────┘
```

> **Why Receiving is Critical**: Receiving is the **only point in the chain where a supplier claim is still possible**. Every defect missed at receiving becomes exponentially more expensive downstream.

---

## 2. Solution Overview

### The Core Principle
> **"AI observes. Evidence supports. Rules decide."**

RCV decouples visual perception from decision authority. Large language models (LLMs) and vision transformers are prone to subtle hallucinations; letting an AI directly decide whether to accept or reject inventory exposes operations to uninsurable liability.

```text
Shipment Photos (1-3 photos)
      ↓
Vision Model (OpenAI / Anthropic / OpenRouter) — Observes only
      ↓
Structured Observations (Observed SKU, counts, damage, confidence)
      ↓
Deterministic Rules Engine (Python pure logic)
      ↓
Check Verdicts (PASS / FAIL / UNCERTAIN)
      ↓
Shipment Decision (ACCEPT / EXCEPTION / UNCERTAIN)
      ↓
Cryptographically Sealed Evidence Record (SHA-256)
      ↓
AI Reasoning Review (Audit, seller impact, claim feasibility)
```

### Decision Model

#### Check-Level Verdicts:
* **`PASS`**: Clear evidence proves the received goods match the PO/catalogue spec.
* **`FAIL`**: Evidence proves a discrepancy (shortage, wrong SKU, damage, missing item).
* **`UNCERTAIN`**: Evidence is missing, obscured, low-confidence (<0.70), or ambiguous. **`UNCERTAIN` is a first-class outcome, never a low-confidence pass.**
* **`NOT_APPLICABLE`**: The check does not apply to this shipment (e.g. carton count on loose units).

#### Shipment-Level Decisions:
* **`ACCEPT`**: All applicable checks evaluate to `PASS`.
* **`EXCEPTION`**: One or more checks evaluate to `FAIL`. Triggers immediate vendor claim or quarantine.
* **`UNCERTAIN`**: No check failed, but one or more checks could not be verified with high confidence. Routes to senior operator review.

### What RCV Verifies:
1. **SKU & Barcode Identity**: Direct label/UPC/FNSKU reading against PO line item and catalogue.
2. **Quantity & Carton Math**: Total units received vs. PO ordered count, factoring in carton counts and units-per-carton hierarchy.
3. **Packaging Integrity**: Tears, punctures, wet cartons, crushed corners, broken seals.
4. **Product Variant**: Exact color, size, material, or style specifications.
5. **Component Completeness**: Essential accessories (power adapters, cables, documentation).

### Cryptographic Evidence Chain
Every inspection produces an immutable JSON evidence record containing:
- **`photo_hashes`**: SHA-256 digests of all raw uploaded images.
- **`po_snapshot` & `catalog_snapshot`**: Frozen copies of the authoritative PO and spec at time of receipt.
- **`record_hash`**: Canonical SHA-256 signature calculated over the entire inspection record.
- **Tamper Verification**: Instant cryptographic check via `/api/inspections/{id}/verify`.

---

## 3. Setup Instructions

### Prerequisites
* Python 3.9+ (tested on Python 3.9, 3.10, 3.11, 3.12)
* `git`

### Installation

1. **Clone the Repository**:
   ```bash
   git clone https://github.com/Savage4696/cube26-rcv-0093-https-github.com-savage4696-rcv.git RCV
   cd RCV
   ```

2. **Create and Activate Virtual Environment**:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```

3. **Install Package & Dependencies**:
   ```bash
   pip install --upgrade pip
   pip install -e ".[dev]"
   ```

4. **Configure Environment Variables**:
   ```bash
   cp .env.example .env
   ```

   Edit `.env` with your preferred AI provider keys:
   ```ini
   # Vision & Reasoning Providers (Optional for offline demo/benchmark)
   OPENAI_API_KEY=sk-...
   ANTHROPIC_API_KEY=sk-ant-...
   OPENROUTER_API_KEY=sk-or-...

   # Model Selection
   VISION_PROVIDER=openai       # openai | anthropic | openrouter
   VISION_MODEL=gpt-4o
   REASONING_MODEL=gpt-4o-mini

   # Safety & Spend Limits
   MAX_SESSION_SPEND=5.00
   MIN_CREDIT_THRESHOLD=0.50
   ```

> **Running Without API Keys**: RCV is fully functional without any API keys! You can run the entire 24-scenario benchmark, inspect recorded observations, launch the web dashboard, and test all deterministic rules completely offline with zero API costs.

---

## 4. Usage Instructions

### Web Dashboard
Launch the unified inspection dashboard:
```bash
receiving-manager serve --port 8000
```
Open **`http://localhost:8000`** in your browser.

**Web Features**:
* **Live Inbound Inspector**: Upload shipment photos, select PO & catalogue items, and trigger vision + deterministic rule evaluation.
* **Scenario Benchmark Runner**: Run all 24 curated receiving scenarios with a single click and review the aggregate accuracy matrix.
* **Supplier Analytics**: Real-time supplier scorecards showing defect rates, damage frequency, and shortage counts.
* **Export Engine**: One-click download of all inspection records in structured JSON or CSV format for downstream Prep and Recovery pods.
* **Integrity Verifier**: Verify the cryptographic SHA-256 seal of any stored inspection.

### Command Line Interface (CLI)

1. **Run Full Benchmark**:
   ```bash
   receiving-manager scenarios
   ```

2. **Run a Specific Scenario**:
   ```bash
   receiving-manager scenarios 01_correct_shipment
   receiving-manager scenarios 03_damaged_carton
   receiving-manager scenarios 11_spec_example
   ```

3. **Inspect Custom PO & Photos**:
   ```bash
   receiving-manager inspect \
     --po scenarios/data/po_01.json \
     --catalog scenarios/data/catalog.json \
     photo1.jpg photo2.jpg
   ```

### REST API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/inspections` | Upload photos and run end-to-end inspection |
| `GET` | `/api/inspections` | List all historical inspections (scoped by org) |
| `GET` | `/api/inspections/{id}` | Retrieve complete sealed evidence record |
| `GET` | `/api/inspections/{id}/verify` | Cryptographically verify record integrity |
| `GET` | `/api/suppliers/stats` | Retrieve supplier performance scorecards |
| `GET` | `/api/inspections/export?fmt=json\|csv` | Export inspections for downstream managers |
| `GET` | `/api/benchmark` | Execute 24-scenario benchmark and return metrics |
| `GET` | `/api/definitions` | Retrieve authoritative check criteria and definitions |
| `GET` | `/api/budget` | Check current model spend and credit guard status |
| `GET` | `/api/health` | Health check and provider configuration |

### Running Tests
Execute the comprehensive test suite (unit tests, rules engine, reasoning guards, API endpoints):
```bash
PYTHONPATH=. pytest -v
```

---

## 5. Assumptions & Limitations

### Operational Assumptions
1. **Photo Quality & Coverage**: RCV assumes photos show outer carton shipping labels, box exterior condition, and open carton contents. A photo that does not capture the shipping label will legitimately yield an `UNCERTAIN` identity verdict.
2. **Deterministic Precedence**: Downstream systems agree that physical rule violations (`FAIL`) override any probabilistic AI speculation.
3. **Single PO Line per Capture**: Each inspection run currently evaluates one purchase order line item. Multi-line consolidation pallets are broken down into individual line inspection captures.

### Known Limitations & Failure Modes
1. **Concealed Internal Damage**: Non-invasive optical inspection cannot detect internal product defects inside factory-sealed blister packs without unboxing.
2. **Reflective Shrinkwrap**: Heavy industrial plastic wrap can cause specular glare that obscures 2D barcodes; RCV flags these as `UNCERTAIN` rather than guessing.
3. **Barcode Scanning vs. OCR**: In low-light environments, visual text OCR may degrade. In production, pairing RCV with a physical Bluetooth 1D/2D laser scanner provides defense-in-depth.
4. **Volumetric Pallet Stacks**: For multi-layer pallets (e.g. 5 layers of 10 cartons), camera views can only verify visible external cartons; intermediate interior counts rely on stated packing slips unless depalletized.

---

## 6. Architecture & System Design
For a deep dive into the component architecture, sequence flows, prompt engineering, and core design trade-offs, see [`ARCHITECTURE.md`](ARCHITECTURE.md).

---

*Cube Buildathon · Track 01: Receiving Manager*
