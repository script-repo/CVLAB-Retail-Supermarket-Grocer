# Training your own models

Pretrained and zero-shot models cover people, poses, common objects, wet-floor
signs and products shown by example. They do **not** reliably find empty shelf
gaps or liquid spills: text prompts and SAM were tried on the bundled videos
and fell short. Those tasks, and production-grade SKU recognition, need a
model trained on footage from your stores. This is the shortest path.

## 1. Pre-label frames

`cv-lab/tools/auto_label.py` samples frames from videos, proposes labels and
writes a YOLO-format dataset:

```bash
cd cv-lab
# Specific products: draw a few example boxes in one reference frame.
#   examples.json: {"image": "ref.jpg", "boxes": [[x1,y1,x2,y2], ...], "names": ["salsa jar", ...]}
python tools/auto_label.py --videos /path/to/store-videos --out data/skus \
    --examples examples.json --frames-per-video 40

# Generic objects by text prompt, or COCO classes (0 = person).
python tools/auto_label.py --videos /path/to/videos --out data/signs --prompts "wet floor sign"
python tools/auto_label.py --images frames/ --out data/people --coco 0

# Add --sam sam2.1_t.pt to turn each box into a polygon (for -seg models).
```

On the bundled shelf video, one example each of two products gave 122
pre-labels from 10 frames. Text prompts for the same products gave 1.

For **spills and shelf gaps** there's no good proposal source. Sample frames
with `--prompts` (or any class), then draw most labels yourself in the review
step. A few hundred labelled frames from your own cameras go a long way.

## 2. Review

Import the output folder into CVAT, Label Studio or Roboflow as a YOLO
dataset, fix wrong boxes, add missed ones, and export it back in YOLO format.
Pre-labels are proposals, not ground truth: don't skip this step.

## 3. Train

```bash
yolo detect train data=data/skus/data.yaml model=yolo11n.pt epochs=100 imgsz=640
# segmentation labels (from --sam): yolo segment train ... model=yolo11n-seg.pt
```

A GPU is strongly recommended. Training on CPU works for a smoke test only.

## 4. Use it

Copy `runs/detect/train/weights/best.pt` into `MODELS_DIR` and point the role
at it. The runtime layer then exports it to TensorRT or OpenVINO like the
built-in models:

| Task | Setting | Used by |
|---|---|---|
| Empty-shelf gaps | `EMPTY_SHELF_MODEL=empty-shelf.pt` | UC-2, UC-3 |
| Spills / wet floor | `SPILL_MODEL=spill.pt` | UC-16 |
| Better people detector | `PERSON_MODEL=people.pt` | all people use cases |

Add the new behaviour to `cv-lab/tests/test_video_regression.py` with a clip
from your store, so later upgrades can't silently regress it.
