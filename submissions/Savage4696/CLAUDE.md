# CLAUDE.md — Durable Engineering Invariants & Style Rules

> **Track 01: Inbound Receiving Manager · Candidate Savage4696**

---

## 1. Durable Engineering Constraints (Non-Negotiable)

### Rule 1: Tenancy Isolation Before Any Feature
Every database query and storage lookup must strictly scope to `organization_id` (e.g., `org_demo_alpha`, `org_demo_bravo`). No cross-tenant data leakage is permissible, even in test fixtures.

### Rule 2: Batch All Vision Model Calls
Never make one model call per check. A single inspection dispatch must submit all captured photographs (`P1`, `P2`, `P3`) in one multimodal payload carrying all candidate check targets.

### Rule 3: Fail Open Under Load
If a vision API times out, returns HTTP 429/500, or exceeds credit guards, the system must **fail open**: the physical capture is preserved, photo hashes are recorded, and the shipment record is marked `PENDING_REVIEW`. Warehouse line receivers must never be blocked by cloud outages.

### Rule 4: UNCERTAIN is a First-Class Verdict
`UNCERTAIN` is never a low-confidence `PASS`. When lighting is poor, labels are torn, or carton counts are obscured, the check and shipment must evaluate to `UNCERTAIN` and route to secondary verification.

### Rule 5: Look Authoritative Rules Up
Never let an LLM invent or infer compliance rules from training memory. Specifications must be looked up directly from the purchase order and catalog snapshot.

---

## 2. Engineering Honesty Rules (Assessed)

1. **Say what you built, not what it sounds like**:
   - We built a SHA-256 canonical digest sealing pipeline. Do not claim "blockchain-backed" or "quantum encryption".
2. **Overrides are data**:
   - When a human supervisor overrides an automated decision, capture the original verdict, new verdict, reason, operator ID, and timestamp in `overrides[]`. Never discard override events.
3. **"It works well" is not a result**:
   - Report exact quantitative metrics per check: True Positives (TP), False Positives (FP), True Negatives (TN), False Negatives (FN), and UNCERTAIN count on held-out datasets.
4. **Contradictions are findings**:
   - Document edge cases where vision findings diverge from ground truth.

---

## 3. Forbidden Terminology

The following phrases are banned across all documentation and interfaces:
- ❌ *"The AI decided to accept the shipment"* (AI only observes; the deterministic rules engine decides).
- ❌ *"100% accurate vision model"* (Vision is probabilistic; optical OCR degrades under blur and glare).
- ❌ *"Tamper-proof"* (Use *"Tamper-evident"* via SHA-256 content verification).
- ❌ *"Zero-cost AI"* (Every model invocation has measured token and latency cost).
