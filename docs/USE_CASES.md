# Use cases

Twenty retail / supermarket / grocery computer-vision scenarios. Each is a single
analyzer file in `cv-lab/backend/app/usecases/` and appears automatically in the
UI. Use cases marked **Zone** expect you to draw a region of interest on the
frame (the UI prompts you); they fall back to a sensible default region if you
don't.

| Pattern | Meaning |
|---|---|
| people-tracking | Detect + track people (YOLOv8 + ByteTrack) |
| shelf-vision | Analyze shelves/products (detection + OpenCV heuristics) |
| loss-prevention | Behavior/anomaly cues for shrink & fraud |
| product-recognition | Identify/inspect products or shipments |
| task-ops | Operational tasks, compliance, hazards |
| privacy | Privacy-preserving demographics/triggers (anonymous) |

---

### UC-1 — Autonomous / Cashierless Checkout · `people-tracking`
Tracks shoppers through the space to illustrate grab-and-go checkout flows
(entry, pick, exit) without a manned till.

### UC-2 — Real-Time Shelf Out-of-Stock Detection · `shelf-vision` · **Zone**
Watches a shelf region and flags when facings empty out, so staff can restock
before sales are lost. Optional custom model via `EMPTY_SHELF_MODEL`.

### UC-3 — Planogram Compliance Verification · `shelf-vision` · **Zone**
Compares what's on a shelf against the expected layout to surface
merchandising/compliance gaps.

### UC-4 — Shrink / Loss Prevention & Theft Detection · `loss-prevention`
Highlights suspicious behaviors (concealment, dwell near high-value goods) as
loss-prevention cues.

### UC-5 — Self-Checkout Fraud Detection · `loss-prevention` · **Zone**
Monitors the self-checkout area for scan-avoidance / mis-scan patterns.

### UC-6 — Queue Length & Wait-Time Monitoring · `people-tracking` · **Zone**
Counts people in a checkout zone, estimates wait time, and raises an "open
another lane" alert past a threshold. Tunables: service time, queue limit, open
lanes.

### UC-7 — Customer Traffic Heat Maps & Flow Analytics · `people-tracking`
Accumulates movement into a heatmap to reveal hot zones and traffic flow.

### UC-8 — Automated Product Expiry / Date Monitoring · `shelf-vision` · **Zone**
Flags products/areas for date checks to reduce out-of-date stock on shelf.

### UC-9 — Smart Shopping Cart CV Integration · `product-recognition`
Simulates cart-mounted product recognition as items are added/removed.

### UC-10 — Produce Quality & Freshness Assessment · `product-recognition`
Inspects produce appearance for freshness/quality grading cues.

### UC-11 — In-Store Aisle Scanning Robots · `task-ops`
Emulates an aisle-scanning robot's view, checking shelves as it passes.

### UC-12 — Dynamic / Electronic Shelf Label Verification · `shelf-vision` · **Zone**
Verifies electronic shelf labels are present and consistent.

### UC-13 — Staff Efficiency & Task Completion Monitoring · `task-ops` · **Zone**
Tracks task areas to estimate staff activity and task completion.

### UC-14 — Age Verification at Self-Checkout · `privacy`
Privacy-preserving age-estimation trigger for restricted items (anonymous, no
identity/biometric storage).

### UC-15 — Cold Chain / Refrigeration Door Compliance · `task-ops` · **Zone**
Watches fridge/freezer doors for open-too-long compliance events.

### UC-16 — Spill & Hazard Detection · `task-ops`
Detects spills/obstructions on the floor as safety hazards. Optional custom
model via `SPILL_MODEL`.

### UC-17 — Visual Product Search for Shoppers · `product-recognition`
Demonstrates "find similar products" visual search from a frame.

### UC-18 — Supply Chain & Receiving Dock Verification · `product-recognition`
Verifies pallets/cases at the receiving dock against expectations.

### UC-19 — Personalized In-Store Digital Signage · `privacy`
Anonymous audience cues (e.g. approximate group size/attention) to adapt signage
— no identification.

### UC-20 — Dwell-Time / Product Engagement Analysis · `people-tracking` · **Zone**
Measures how long shoppers dwell in a zone to gauge product engagement.

---

## Models used

- **YOLOv8** (Ultralytics, COCO weights) for people and common-object detection.
- **ByteTrack** (via `supervision`) for stable multi-object tracking and dwell.
- **OpenCV** heuristics for shelf/spill/heatmap analysis where a bespoke model
  isn't required.
- Optional **custom `.pt` models** for shelf and spill use cases.

> These analyzers are demonstrations of the patterns, not production-tuned
> detectors. For real deployments, train/fine-tune models on representative
> footage and validate accuracy for your environment.
