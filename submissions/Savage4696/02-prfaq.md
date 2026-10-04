# PR/FAQ: RCV — Inbound Receiving Manager

> **Product Press Release & Frequently Asked Questions (Including the Hard Questions)**

---

## Press Release

### SEATTLE & BENGALURU — October 2026
Today, Savage4696 announces **RCV (Receiving Manager)**, the first production-grade, multimodal AI receiving and evidence sealing system built for modern cross-dock and e-commerce distribution centers.

Inbound receiving has long been the weakest operational link in commerce: warehouse receivers are expected to unload pallets in minutes, verify hundreds of SKUs by eye, and sign bills of lading without a verifiable audit trail. When shortages, damaged packaging, or wrong color variants are discovered weeks later during prep or customer fulfillment, warehouses lose millions in rejected supplier claims.

RCV changes this dynamic forever. By combining batch multimodal vision inference with a deterministic, zero-hallucination rules engine, RCV inspects incoming shipments in under 12 seconds, verifies every carton against authoritative purchase orders, and seals the result into a cryptographically signed SHA-256 evidence record.

*"In operations, AI must never make the decision,"* said the Lead Systems Architect. *"LLMs hallucinate under pressure. We decoupled perception from authority: the vision model observes what is in the photograph, but our deterministic Python engine decides whether the shipment passes. If evidence is ambiguous, the system outputs UNCERTAIN rather than guessing. It is built for real warehouse truth."*

---

## Frequently Asked Questions (FAQ)

### Operational & Technical Questions

#### Q1: What happens if warehouse lighting is terrible or a camera photo is blurry?
**A**: Unlike naive classifiers that guess, RCV adheres to **Engineering Rule 4: UNCERTAIN is a valid verdict**. The vision model assigns calibrated confidence scores to label OCR, counts, and packaging condition. If camera shake, glare, or darkness drops confidence below the configured threshold (default 0.70), the affected check returns `UNCERTAIN`. The shipment decision becomes `UNCERTAIN` and routes to a secondary laser scan queue.

#### Q2: Can the AI reasoning reviewer overrule a rejected shipment and pass it?
**A**: **No. Asymmetric escalation is a non-negotiable architectural invariant.** The reasoning auditor can downgrade an `ACCEPT` to `UNCERTAIN` if it detects subtle contextual anomalies, but it is mathematically and logically barred from turning an `EXCEPTION` or `UNCERTAIN` into an `ACCEPT`.

#### Q3: How does RCV prevent runaway API costs?
**A**: RCV implements a hard **Credit Budget Guard** and **Single-Batch Processing (Engineering Rule 2)**:
1. Every inspection dispatches a single multimodal API call carrying all photos simultaneously.
2. The client checks key balances and per-session spend ceilings before dispatch. If limits are reached, the call is refused and the system fails open to manual processing without stalling dock workers.
3. Identical requests are cached on disk by SHA-256 hash, making regression testing completely free.

---

## The Hard Questions (The Ones We'd Rather Not Answer)

#### Q4: Why don't you do 100% automated decisioning directly from the vision LLM?
**A**: Because putting financial liability on a probabilistic neural network is irresponsible engineering. In arbitration, a vendor's legal counsel will challenge an AI decision. With RCV, we produce a deterministic mathematical proof: "The PO mandated 24 units; the carton label specified 12 units/carton; 1 carton arrived; 24 != 12; therefore check failed." The rules are transparent, reproducible, and legally defensible.

#### Q5: Can RCV detect internal item damage inside a factory-sealed brown master carton without opening it?
**A**: **No, and anyone who claims their vision model can is lying.** Optical cameras cannot see through corrugated cardboard. RCV explicitly models sealed master cartons: if a carton is sealed with tamper tape, it derives unit count from the verified carton label and marks internal unit inspection as `DERIVED_SEALED`. To check internal units, line receivers must cut the tape and photograph the open box.

#### Q6: How do you handle multi-layer pallets where the inner cartons are completely hidden?
**A**: When cartons are stacked in dense blocks, interior boxes are occluded. RCV's vision prompt strictly forbids assuming hidden units exist: `all_visible` evaluates to `false`. The rules engine evaluates total quantity as `UNCERTAIN` unless all sides or depalletized layers are photographed.

#### Q7: What stops a warehouse operator from doctoring the photo or editing the decision after the fact?
**A**: The **Cryptographic Evidence Seal**. The moment an inspection completes, RCV calculates a SHA-256 signature across the raw photo bytes, PO snapshot, catalog spec, and check verdicts. Any subsequent tampering with numbers or images produces a signature mismatch when verified via `/api/inspections/{id}/verify`.
