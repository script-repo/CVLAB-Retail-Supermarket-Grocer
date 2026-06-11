# Adding a use case

The pipeline is plug-in based: **one file = one use case**. Create an analyzer,
register it, import it, and it appears automatically in the API
(`GET /api/usecases`) and the UI.

## 1. Create the analyzer file

Add `cv-lab/backend/app/usecases/uc21_my_feature.py`:

```python
"""UC-21: My Feature — one-line description of what it detects."""
from __future__ import annotations

from typing import Any

import numpy as np

from app.schemas import AnalysisConfig
from .base import BRAND_GREEN, UseCaseAnalyzer, draw_banner, register


@register
class MyFeatureAnalyzer(UseCaseAnalyzer):
    id = "uc-21"                      # unique; UI sorts by this
    title = "My Feature"             # shown in the UI
    pattern = "task-ops"            # one of the UI pattern groups
    needs_zones = False              # True if you require a drawn polygon

    def setup(self, frame: np.ndarray, config: AnalysisConfig) -> None:
        # Called once with the first frame and the client config.
        self.h, self.w = frame.shape[:2]
        # Read tunables (exposed as UI sliders via params):
        self.threshold = float(config.params.get("threshold", 0.5))

    def process_frame(self, frame: np.ndarray, timestamp_s: float):
        # Called for every frame. Return (annotated_frame_bgr, metrics_dict).
        self.frame_index += 1

        # ... your detection / OpenCV logic, drawing onto `frame` ...
        alert = False
        headline = "All clear"

        draw_banner(frame, headline, alert=alert)
        return frame, {
            "status": "alert" if alert else "ok",
            "headline": headline,
            "values": {"example_metric": 0},
        }
```

### Contract

- `setup(frame, config)` — initialize models/zones/tunables once.
- `process_frame(frame, timestamp_s) -> (np.ndarray, dict)` — return the
  annotated **BGR** frame and a metrics dict with keys `status`
  (`"ok"`/`"alert"`), `headline` (str), and `values` (dict). These map onto the
  `MetricEvent` schema sent to the browser.
- Class attributes `id`, `title`, `pattern`, `needs_zones` drive discovery + UI.

## 2. Register the import

Add your module to `cv-lab/backend/app/usecases/__init__.py` so it gets imported
(importing the module runs the `@register` decorator):

```python
from . import uc21_my_feature  # noqa: F401
```

## 3. Reuse the building blocks

| Need | Use |
|---|---|
| Person/object detection | `from app.core.models import get_person_model` |
| Multi-object tracking + dwell | `from app.core.tracking import Tracker, detections_from_yolo` |
| Drawn zones (normalized → pixels) | `polygons_to_pixels(config, w, h)` in `base.py` |
| On-frame banner / chips / bars | `draw_banner`, `draw_chip`, `progress_bar` in `base.py` |
| Brand colors | `BRAND_GREEN`, `BRAND_FRESH`, `BRAND_RED`, ... in `base.py` |
| ASCII-safe overlay text | `ascii_safe(text)` in `base.py` |

See `usecases/uc06_queue.py` for a complete, well-commented reference (detection
+ tracking + zone + tunables + metrics).

## 4. Expose tunables

Anything you read from `config.params` (e.g. `config.params.get("threshold")`)
can be surfaced as a UI slider. Keep names stable — they persist per use case in
the browser.

## 5. Zones

If `needs_zones = True`, the UI prompts the user to draw one or more polygons.
Convert them with `polygons_to_pixels(config, w, h)`; always provide a sensible
default region when none is drawn (see UC-6).

## 6. Drive the agent (optional)

To feed the agentic-ops layer, emit detections/alerts that the event bus in
`core/agent.py` consumes (study how an existing alerting analyzer like UC-2 or
UC-6 reports `status: "alert"`). Sustained alerts become events → work orders.

## 7. Test it

```bash
cd cv-lab
python selftest.py          # imports + basic analyzer checks
uvicorn app.main:app --reload --port 8000   # then pick "UC-21" in the UI
```

## Checklist

- [ ] Unique `id`, clear `title`, valid `pattern`
- [ ] `setup` + `process_frame` implemented; returns `(frame, metrics)`
- [ ] Imported in `usecases/__init__.py`
- [ ] Sensible defaults when no zone/params are provided
- [ ] No secrets, no hard-coded internal hosts
- [ ] Appears in `GET /api/usecases` and runs in the UI
