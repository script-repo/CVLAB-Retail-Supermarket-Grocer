/* Retail-Supermarket-Grocery CV — detailed use-case catalog (single source for the deployed library).
   Mirrors cv-portal/assets/data.js but bundled with the live app so the library
   is served from the same origin as the analyzer. */

const PATTERNS = {
  "people-tracking":     { label: "People Tracking / Path Analytics",          color: "#3b82f6" },
  "shelf-vision":        { label: "Shelf Vision / Retail Execution",           color: "#10b981" },
  "loss-prevention":     { label: "Loss Prevention / Anomaly Detection",       color: "#ef4444" },
  "task-ops":            { label: "Task / Operations Monitoring",              color: "#f59e0b" },
  "product-recognition": { label: "Product Recognition / OCR / Quality",       color: "#8b5cf6" },
  "privacy":             { label: "Privacy-Sensitive Inference",               color: "#14b8a6" }
};

/* Shared platform stack — shown in the library hero. */
const PLATFORM = [
  "Nutanix AHV + NKP (Kubernetes)",
  "FastAPI + Uvicorn (REST + WebSocket streaming)",
  "Ultralytics YOLOv8 (COCO + specialty weights)",
  "Supervision (ByteTrack, PolygonZone, annotators)",
  "OpenCV + NumPy (decode, heuristics, drawing)",
  "Nutanix Objects (S3) — video & clip storage",
  "Nutanix Volumes (CSI) — model & dependency cache",
  "Traefik ingress + MetalLB load balancing"
];

const USE_CASES = [
  {
    id: 1, slug: "cashierless-checkout", pattern: "people-tracking", live: "uc-01",
    title: "Autonomous / Cashierless Checkout",
    cameraAngle: "Ceiling-mounted overhead, 80–90° downward, covering aisle bay, cart/basket, and exit threshold.",
    framing: "Wide enough to show shopper entering, selecting item, placing it in basket, and walking toward exit.",
    action: "Actor enters frame, picks up one item, pauses, places it in basket, returns a second item to shelf, then exits through a visible boundary line.",
    cvOverlay: "Person ID track, hand-object interaction, product picked/returned, virtual cart update, exit event.",
    loopGoal: "Demonstrate “customer journey tracked without checkout lane.”",
    infra: [
      "NKP (Kubernetes) pod — FastAPI + Ultralytics inference (CPU now, GPU-ready)",
      "Nutanix Objects (S3) — source video and journey clips",
      "Nutanix Volumes (CSI PVC) — model weights & dependency cache"
    ],
    models: [
      { name: "YOLOv8 (COCO)", role: "Shopper + product/bag detection", why: "One fast model covers people and 80 everyday object classes, so a single pass detects shoppers, baskets and items at the edge." },
      { name: "ByteTrack (Supervision)", role: "Multi-object tracking / stable ID", why: "Training-free tracker keeps one consistent shopper ID through the whole journey for cart association." },
      { name: "LineZone (Supervision)", role: "Exit-line crossing event", why: "Converts a tracked path into a discrete 'left the store' checkout event." }
    ]
  },
  {
    id: 2, slug: "out-of-stock", pattern: "shelf-vision", live: "uc-02",
    title: "Real-Time Shelf Out-of-Stock Detection",
    cameraAngle: "Shelf-facing frontal, 0–10° off-axis, fixed at shelf height.",
    framing: "One 4–6 foot shelf section with multiple facings.",
    action: "Start with full shelf. Employee or shopper removes several units until one SKU has only one or zero facings.",
    cvOverlay: "SKU region boxes, facing count, threshold alert: “Replenish Aisle 3 / Cereal Bay.”",
    loopGoal: "Show facing-count degradation and automatic alert.",
    infra: [
      "NKP pod — inference service",
      "Nutanix Objects (S3) — video & evidence frames",
      "Nutanix Volumes (PVC) — model/deps cache",
      "NUS Files — planogram baseline reference"
    ],
    models: [
      { name: "Roboflow empty-shelf YOLOv8 (optional weights)", role: "Empty-facing / gap detection", why: "Purpose-trained on retail shelves; drops into the model registry for production-grade accuracy." },
      { name: "Edge-density heuristic (OpenCV)", role: "Per-zone occupancy fallback", why: "Texture/edge density inside each shelf zone estimates 'how full' with zero training when no shelf weights are present." }
    ]
  },
  {
    id: 3, slug: "planogram-compliance", pattern: "shelf-vision", live: "uc-03",
    title: "Planogram Compliance Verification",
    cameraAngle: "Straight-on shelf audit angle, tripod or robot-eye height, 4–5 feet from shelf.",
    framing: "Entire bay visible, including shelf edges and product rows.",
    action: "One product is intentionally misplaced, one facing is missing, and one SKU is over-faced. Actor briefly adjusts item incorrectly.",
    cvOverlay: "Green boxes for compliant products, red/yellow for misplaced SKU, missing facing, wrong shelf position.",
    loopGoal: "Show “actual shelf vs approved planogram.”",
    infra: [
      "NKP pod — inference service",
      "NUS Files — approved planogram image baselines",
      "Nutanix Objects (S3) — captured shelf states",
      "Nutanix Volumes (PVC) — model/deps cache"
    ],
    models: [
      { name: "HSV histogram baseline compare (OpenCV)", role: "Per-slot deviation vs approved layout", why: "The first frame is treated as the approved planogram; a drop in histogram correlation per slot flags misplaced/missing product with no model to train." },
      { name: "Roboflow SKU/shelf model (optional)", role: "SKU-level identity", why: "Upgrade path when true product-identity compliance (not just 'changed') is required." }
    ]
  },
  {
    id: 4, slug: "theft-detection", pattern: "loss-prevention", live: "uc-04",
    title: "Shrink / Loss Prevention and Theft Detection",
    cameraAngle: "Wide aisle oblique, 30–45° from corner, high-mounted at 8–10 feet.",
    framing: "Shopper, shelf, basket/cart, and exit direction visible.",
    action: "Actor picks up item, looks around, places it inside a coat/bag, then walks away. Keep behavior staged and non-instructional.",
    cvOverlay: "Anomaly marker, object-hand-body occlusion, “review event,” not “confirmed theft.”",
    loopGoal: "Demonstrate suspicious-behavior flagging, not identity tracking.",
    infra: [
      "NKP pod — inference service",
      "Nutanix Objects (S3) — only review-event clips retained",
      "Nutanix Volumes (PVC) — model/deps cache",
      "Privacy: behaviour-only — no facial recognition / no identity store"
    ],
    models: [
      { name: "YOLOv8 (COCO)", role: "Person + bag (backpack/handbag/suitcase) detection", why: "Detects the actors and the bags involved without any biometric model." },
      { name: "ByteTrack (Supervision)", role: "Per-person dwell timing", why: "Sustained loitering near a shelf is a key behavioural signal; the tracker measures it per anonymous ID." },
      { name: "Behaviour heuristic", role: "Dwell + bag-proximity → review event", why: "Combines signals into a staff 'review event' — flags behaviour for a human to judge, never a 'confirmed theft'." }
    ]
  },
  {
    id: 5, slug: "self-checkout-fraud", pattern: "loss-prevention", live: "uc-05",
    title: "Self-Checkout Fraud Detection",
    cameraAngle: "Overhead self-checkout camera, 70–85° downward, showing scanner, product staging area, and bagging area.",
    framing: "Hands, products, barcode scanner area, bagging platform. Avoid face capture.",
    action: "Actor scans a low-cost item, then places a different higher-value item into the bagging area. In second motion, actor moves an item directly to bag without scanning.",
    cvOverlay: "“Scanned SKU: Item A,” “Detected item: Item B,” mismatch alert, skipped-scan alert.",
    loopGoal: "Demonstrate item-substitution and non-scan detection.",
    infra: [
      "NKP pod — inference service",
      "Nutanix Objects (S3) — exception clips",
      "Nutanix Volumes (PVC) — model/deps cache"
    ],
    models: [
      { name: "YOLOv8 (COCO)", role: "Item detection entering the bagging zone", why: "Counts items physically bagged independent of what the scanner saw." },
      { name: "PolygonZone (Supervision)", role: "Bagging-area gating", why: "Restricts counting to the bag platform so only relevant items are reconciled." },
      { name: "POS reconciliation logic", role: "Bagged-vs-scanned mismatch", why: "Compares the vision item count to the POS scan stream and raises skipped-scan alerts." }
    ]
  },
  {
    id: 6, slug: "queue-monitoring", pattern: "people-tracking", live: "uc-06",
    title: "Queue Length & Wait-Time Monitoring",
    cameraAngle: "Ceiling or high-wall overhead, 70–90° downward over checkout lanes.",
    framing: "2–3 checkout lanes with floor queue zones visible.",
    action: "Actors join a line one by one. One cashier lane remains closed. Queue grows past marked threshold.",
    cvOverlay: "Person count, queue length, estimated wait time, “open lane recommended.”",
    loopGoal: "Show real-time queue thresholding and staffing trigger.",
    infra: [
      "NKP pod — inference service",
      "Nutanix Objects (S3) — source video",
      "Nutanix Volumes (PVC) — model/deps cache"
    ],
    models: [
      { name: "YOLOv8 (COCO person)", role: "Shopper detection", why: "Fast, accurate person detector suitable for top-down crowd views at the edge." },
      { name: "ByteTrack (Supervision)", role: "Per-shopper dwell", why: "Gives each queuer a stable ID so dwell/wait can be measured." },
      { name: "PolygonZone + queueing estimate", role: "Count in zone → wait time", why: "Counts people inside the drawn queue polygon and converts to wait via service-time × count ÷ lanes." }
    ]
  },
  {
    id: 7, slug: "heat-maps", pattern: "people-tracking", live: "uc-07",
    title: "Customer Traffic Heat Maps & Flow Analytics",
    cameraAngle: "High overhead wide shot, ideally from store corner or ceiling.",
    framing: "Cross-aisle intersection, promotional island, and two aisle entrances.",
    action: "Multiple actors walk different paths; two pause at promo display; one bypasses.",
    cvOverlay: "Anonymous tracks, flow arrows, heat-map accumulation, dwell zones.",
    loopGoal: "Show movement analytics for store layout and merchandising.",
    infra: [
      "NKP pod — inference service",
      "Nutanix Objects (S3) — heat-map exports & video",
      "Nutanix Volumes (PVC) — model/deps cache",
      "Privacy: anonymous tracks only, no identity"
    ],
    models: [
      { name: "YOLOv8 (COCO person)", role: "Shopper detection", why: "Detects every shopper for accumulation into the heat map." },
      { name: "ByteTrack (Supervision)", role: "Anonymous path tracking", why: "Builds movement traces without storing who anyone is." },
      { name: "HeatMapAnnotator + TraceAnnotator", role: "Density & flow visualization", why: "Accumulates occupancy over time and draws flow paths for layout/merchandising decisions." }
    ]
  },
  {
    id: 8, slug: "expiry-date-monitoring", pattern: "shelf-vision", live: "uc-08",
    title: "Automated Product Expiry / Date Monitoring",
    cameraAngle: "Close shelf-facing macro/OCR angle, 12–24 inches from product label/date area.",
    framing: "Dairy, prepared food, meat, or packaged salad labels with visible expiry dates.",
    action: "Employee rotates items. One near-expiry item remains at the front. Camera lingers on visible date labels.",
    cvOverlay: "OCR bounding box around date, “expires soon,” “rotate/remove” alert.",
    loopGoal: "Demonstrate date extraction and exception flagging.",
    infra: [
      "NKP pod — inference service",
      "NAI / GPU node pool — OCR acceleration (production)",
      "Nutanix Objects (S3) — flagged-label images",
      "Nutanix Volumes (PVC) — model/deps cache"
    ],
    models: [
      { name: "OCR — PaddleOCR / EasyOCR (optional)", role: "Read & parse printed dates", why: "Real deployment reads the date string and parses it to compare against today; runs best on the GPU pool." },
      { name: "Text-region proposer (OpenCV)", role: "Locate date-label candidates (fallback)", why: "Gradient/morphology proposes label regions so the workflow demonstrates end-to-end even with no OCR model loaded." }
    ]
  },
  {
    id: 9, slug: "smart-cart", pattern: "product-recognition", live: "uc-09",
    title: "Smart Shopping Cart CV Integration",
    cameraAngle: "Cart-mounted downward camera, 60–80° into basket. Secondary optional side shot of cart moving.",
    framing: "Interior of cart/basket with enough view to see item entering.",
    action: "Actor places three items into cart, removes one, then adds produce bag.",
    cvOverlay: "Product detection, running cart list, add/remove events, subtotal animation.",
    loopGoal: "Show item recognition inside cart.",
    infra: [
      "NKP pod — central inference / catalog service",
      "Nutanix Objects (S3) — model & catalog assets",
      "Nutanix Volumes (PVC) — model/deps cache"
    ],
    models: [
      { name: "YOLOv8 (COCO)", role: "In-basket product detection", why: "Recognizes grocery items/containers placed in the cart; production swaps in a SKU-trained head." },
      { name: "PolygonZone (Supervision)", role: "Cart/basket region gating", why: "Only items inside the basket polygon count toward the cart." },
      { name: "Catalog price map", role: "Running cart + subtotal", why: "Maps detected classes to prices to maintain a live cart total." }
    ]
  },
  {
    id: 10, slug: "produce-quality", pattern: "product-recognition", live: "uc-10",
    title: "Produce Quality & Freshness Assessment",
    cameraAngle: "Close oblique produce-table angle, 30–45° from above.",
    framing: "Produce pile with good and poor-quality examples visible.",
    action: "Actor picks up one bruised apple/tomato/banana, compares with good item, places poor item in removal bin.",
    cvOverlay: "Surface-defect boxes, freshness score, “remove from display” recommendation.",
    loopGoal: "Show visual grading of quality and defects.",
    infra: [
      "NKP pod — inference service",
      "Nutanix Objects (S3) — defect images / audit trail",
      "Nutanix Volumes (PVC) — model/deps cache",
      "NAI / GPU node pool — specialized defect model (production)"
    ],
    models: [
      { name: "YOLOv8 (COCO produce)", role: "Detect apples/bananas/oranges/etc.", why: "Locates individual produce items so each can be scored separately." },
      { name: "Brown/HSV defect heuristic (OpenCV)", role: "Spoilage / bruise scoring", why: "Fraction of brown/dark pixels per item is a fast freshness proxy needing no training." },
      { name: "Roboflow produce-defect model (optional)", role: "Fine-grained grading", why: "Drop-in upgrade for true defect classification when accuracy matters." }
    ]
  },
  {
    id: 11, slug: "aisle-robots", pattern: "task-ops", live: "uc-11",
    title: "In-Store Aisle Scanning Robots",
    cameraAngle: "Low robot POV or aisle-level tracking shot, 3–4 feet high, centered down aisle.",
    framing: "Robot or rolling camera passes shelves on both sides.",
    action: "Robot/camera moves slowly down aisle, passing missing items, misplaced items, and price labels.",
    cvOverlay: "Shelf scan progress, anomaly markers, aisle map, inventory sync status.",
    loopGoal: "Show autonomous shelf-audit pass.",
    infra: [
      "NKP pod — inventory reconciliation service",
      "Nutanix Objects (S3) — scan imagery",
      "Nutanix Volumes (PVC) — model/deps cache"
    ],
    models: [
      { name: "Edge-density gap audit (OpenCV)", role: "Section-by-section stock-gap detection", why: "As the simulated scan sweep passes each shelf section, low edge-density marks an empty facing — no training required." },
      { name: "Sweep scheduler", role: "Models the robot's scanning pass", why: "Drives progress and per-section auditing to mimic an autonomous shelf-audit run." },
      { name: "YOLOv8 (optional)", role: "Product/label detection", why: "Adds SKU/label recognition when on-robot GPU is available." }
    ]
  },
  {
    id: 12, slug: "esl-verification", pattern: "shelf-vision", live: "uc-12",
    title: "Dynamic / Electronic Shelf Label Verification",
    cameraAngle: "Shelf-edge close-up, straight-on or slight downward angle.",
    framing: "Product, electronic shelf label, and price area together.",
    action: "Show ESL price beside product. Actor updates price on tablet or signage changes. One label intentionally mismatches product/system price.",
    cvOverlay: "OCR price read, SKU-price match, mismatch alert.",
    loopGoal: "Show automated price-label verification.",
    infra: [
      "NKP pod — inference + pricing reconciliation",
      "NAI / GPU node pool — OCR acceleration (production)",
      "Nutanix Objects (S3) — mismatch evidence",
      "Nutanix Volumes (PVC) — model/deps cache"
    ],
    models: [
      { name: "OCR — PaddleOCR / EasyOCR (optional)", role: "Read displayed price", why: "Reads each label price for reconciliation against the pricing system." },
      { name: "Text-region proposer (OpenCV)", role: "Locate price-label regions (fallback)", why: "Finds label regions along the shelf-edge band so verification demonstrates without a loaded OCR model." }
    ]
  },
  {
    id: 13, slug: "staff-task-completion", pattern: "task-ops", live: "uc-13",
    title: "Staff Efficiency & Task Completion Monitoring",
    cameraAngle: "High aisle corner angle, 45° oblique, showing task zone.",
    framing: "End-cap, shelf section, or spill-cleaning area with employee movement visible.",
    action: "Employee arrives, stocks shelf or cleans zone, places completed marker/sign, exits.",
    cvOverlay: "Task assigned, employee/zone presence, task-state transition: “pending → in progress → complete.”",
    loopGoal: "Show non-invasive task verification.",
    infra: [
      "NKP pod — inference service",
      "Nutanix Objects (S3) — source video",
      "Nutanix Volumes (PVC) — model/deps cache",
      "Privacy: presence-only, worker not identified"
    ],
    models: [
      { name: "YOLOv8 (COCO person)", role: "Staff presence in the task zone", why: "Detects that someone is working the zone without identifying who." },
      { name: "PolygonZone (Supervision)", role: "Task-area gating", why: "Restricts presence detection to the assigned task polygon." },
      { name: "State machine (pending→in-progress→complete)", role: "Task lifecycle + time-on-task", why: "Turns presence + dwell into an objective completion signal." }
    ]
  },
  {
    id: 14, slug: "age-verification", pattern: "privacy", live: "uc-14",
    title: "Age Verification at Self-Checkout",
    cameraAngle: "Self-checkout front/side angle, chest-up but privacy-preserving; use actor consent.",
    framing: "Product scan area, attendant light, and customer silhouette/profile.",
    action: "Actor scans age-restricted mock item. System pauses transaction and calls associate. Associate approves after manual check.",
    cvOverlay: "“Age check required,” “staff assist,” no identity shown.",
    loopGoal: "Show assisted verification workflow, not biometric identification.",
    infra: [
      "NKP pod — workflow service",
      "Nutanix Volumes (PVC) — model/deps cache",
      "Privacy: NO facial recognition, NO age estimation — biometrics never used"
    ],
    models: [
      { name: "YOLOv8 (COCO person)", role: "Shopper-present detection only", why: "Confirms a shopper is at the terminal to drive the workflow; deliberately no age or identity inference." },
      { name: "Workflow state machine", role: "Age-check → staff assist → approved", why: "Camera handles presence and hand-off; the human associate makes the age decision." }
    ]
  },
  {
    id: 15, slug: "cold-chain-door", pattern: "task-ops", live: "uc-15",
    title: "Cold Chain / Refrigeration Door Compliance",
    cameraAngle: "Wide cooler/freezer aisle angle, 30–45° oblique from aisle end.",
    framing: "Multiple refrigerator doors, one shopper, door status visible.",
    action: "Actor opens freezer door, removes item, walks away leaving door ajar. Door remains open for several seconds.",
    cvOverlay: "Door-open timer, temperature-risk indicator, “door ajar alert.”",
    loopGoal: "Show open-door detection and response timer.",
    infra: [
      "NKP pod — inference service",
      "Nutanix Objects (S3) — event clips",
      "Nutanix Volumes (PVC) — model/deps cache"
    ],
    models: [
      { name: "Frame-diff door-state heuristic (OpenCV)", role: "Open vs closed detection", why: "Change against a rolling baseline in the door region detects an open door with no training and is robust to lighting drift." },
      { name: "Open-time tracker", role: "Door-ajar timer + threshold alert", why: "Times how long the door stays open and alerts past the allowed limit (energy / cold-chain risk)." }
    ]
  },
  {
    id: 16, slug: "spill-hazard", pattern: "task-ops", live: "uc-16",
    title: "Spill & Hazard Detection",
    cameraAngle: "High aisle oblique, 45° from corner, floor clearly visible.",
    framing: "Aisle floor, shelf base, shopper path.",
    action: "A bottle or produce item falls; visible liquid or scattered items appear; shopper steps around it; employee enters with caution sign.",
    cvOverlay: "Hazard region segmentation, blocked path marker, alert to nearest associate.",
    loopGoal: "Show safety event detection and mitigation.",
    infra: [
      "NKP pod — inference service",
      "Nutanix Objects (S3) — incident clips",
      "Nutanix Volumes (PVC) — model/deps cache"
    ],
    models: [
      { name: "Roboflow spill / wet-floor YOLOv8 (optional weights)", role: "Spill region detection", why: "Trained on wet-floor/spill imagery; drops into the registry for accurate hazard segmentation." },
      { name: "Background-subtraction heuristic (OpenCV)", role: "New-on-floor region + persistence", why: "Detects a new persistent region on the floor and only alerts once it stays put, reducing false positives — works with no weights." }
    ]
  },
  {
    id: 17, slug: "visual-product-search", pattern: "product-recognition", live: "uc-17",
    title: "Visual Product Search for Shoppers",
    cameraAngle: "Over-the-shoulder mobile/kiosk shot, 30–45° behind shopper.",
    framing: "Phone/kiosk screen, product in hand or shelf item, aisle signage in background.",
    action: "Shopper photographs item. App returns product match, aisle location, allergen/nutrition card.",
    cvOverlay: "Product match box, catalog result, “Aisle 5 / Bay 2.”",
    loopGoal: "Show image-to-product lookup.",
    infra: [
      "Kiosk / mobile camera — shopper-facing capture",
      "NKP pod — recognition + catalog lookup service",
      "NAI / GPU node pool — open-vocabulary model (production)",
      "Nutanix Objects (S3) — product image embeddings / catalog",
      "Nutanix Volumes (PVC) — model/deps cache"
    ],
    models: [
      { name: "YOLOv8 (COCO)", role: "Identify the held / prominent product", why: "Detects the largest object presented to the camera as the search subject." },
      { name: "Grounding DINO (optional, open-vocab)", role: "Arbitrary-SKU / text-prompted match", why: "Open-vocabulary detection or an embedding index handles SKUs beyond the COCO classes." },
      { name: "Catalog → aisle map", role: "Locate the matched product", why: "Maps the recognized product to its aisle/bay for shopper directions." }
    ]
  },
  {
    id: 18, slug: "receiving-dock", pattern: "product-recognition", live: "uc-18",
    title: "Supply Chain & Receiving Dock Verification",
    cameraAngle: "Receiving-dock wide shot, 30–45° from side, plus optional close-up of pallet labels.",
    framing: "Pallet, boxes, barcode labels, dock door, associate with tablet.",
    action: "Pallet arrives. Associate walks around it. Camera sees labels and carton count. One box is missing or wrong SKU is visible.",
    cvOverlay: "Pallet count, case count, label OCR/barcode read, PO mismatch alert.",
    loopGoal: "Show inbound shipment verification before shelf stocking.",
    infra: [
      "NKP pod — counting + reconciliation service",
      "Nutanix Objects (S3) — receiving evidence",
      "Nutanix Volumes (PVC) — model/deps cache"
    ],
    models: [
      { name: "Rectangular-contour carton counter (OpenCV)", role: "Count cartons/cases in the dock zone", why: "Edge + polygon-approximation counts box-like shapes with no training to demonstrate the count-and-reconcile loop." },
      { name: "OCR / barcode reader (optional)", role: "Read carton labels", why: "Production reads each label/barcode to validate SKU and lot, not just count." },
      { name: "PO reconciliation logic", role: "Counted vs expected", why: "Compares the live count to the purchase-order quantity and raises shortage/excess alerts." }
    ]
  },
  {
    id: 19, slug: "personalized-signage", pattern: "privacy", live: "uc-19",
    title: "Personalized In-Store Digital Signage",
    cameraAngle: "End-cap display angle, 30° side view showing shopper and digital sign.",
    framing: "Shopper approaches display; signage visible but not face-dominant.",
    action: "Shopper pauses near end-cap. Digital sign changes from generic promotion to contextual promotion based on dwell/zone.",
    cvOverlay: "Anonymous dwell timer, audience segment placeholder, promotion triggered.",
    loopGoal: "Show proximity/dwell-driven signage without identifying the person.",
    infra: [
      "NKP pod — dwell analytics service",
      "Nutanix Volumes (PVC) — model/deps cache",
      "Privacy: anonymous counts only, no demographics / no identity"
    ],
    models: [
      { name: "YOLOv8 (COCO person)", role: "Anonymous audience presence", why: "Counts shoppers near the display without any identity or demographic inference." },
      { name: "ByteTrack (Supervision)", role: "Anonymous dwell timing", why: "Measures how long an anonymous track lingers to decide when to trigger a promotion." },
      { name: "Dwell trigger", role: "Proximity/dwell → contextual promo", why: "Fires the signage change purely on dwell, keeping the experience privacy-safe." }
    ]
  },
  {
    id: 20, slug: "dwell-time-engagement", pattern: "people-tracking", live: "uc-20",
    title: "Dwell-Time / Product Engagement Analysis",
    cameraAngle: "Shelf/end-cap oblique, 30–45° from side, high enough to see shopper body position and product zone.",
    framing: "Product display, shopper, and surrounding aisle.",
    action: "Shopper walks by, stops, picks up product, compares two items, returns one, leaves with one.",
    cvOverlay: "Dwell timer, engagement event, pickup/return event, conversion indicator.",
    loopGoal: "Show engagement analytics for merchandising decisions.",
    infra: [
      "NKP pod — inference service",
      "Nutanix Objects (S3) — source video",
      "Nutanix Volumes (PVC) — model/deps cache",
      "Privacy: anonymous tracks only"
    ],
    models: [
      { name: "YOLOv8 (COCO person)", role: "Shopper detection at the display", why: "Detects shoppers entering the product zone for engagement measurement." },
      { name: "ByteTrack (Supervision)", role: "Per-shopper dwell", why: "Tracks each anonymous shopper to time their dwell at the display." },
      { name: "PolygonZone + dwell threshold", role: "Engagement vs pass-by", why: "Sustained dwell inside the display polygon counts as an engagement (conversion proxy); a brief pass does not." }
    ]
  }
];
