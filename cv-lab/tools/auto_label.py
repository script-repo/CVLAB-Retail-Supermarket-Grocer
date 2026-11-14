"""Bootstrap a training dataset from store footage (pre-labels for human review).

Samples frames from videos (or takes an image folder), proposes boxes with a
detector, optionally refines each box into a polygon with SAM, and writes a
YOLO-format dataset that CVAT / Label Studio / Roboflow can import for review.
After review, train with Ultralytics and point EMPTY_SHELF_MODEL / SPILL_MODEL
(or PERSON_MODEL) at the result. See docs/TRAINING.md.

Proposals come from one of:
  --examples examples.json               YOLOE visual prompts: boxed examples in a
                                         reference image (best for specific products),
  --prompts "salsa jar,tortilla chips"   YOLOE text prompts (generic objects), or
  --coco 0,39,46                         COCO class ids of the default detector.
examples.json: {"image": "ref.jpg", "boxes": [[x1,y1,x2,y2], ...], "names": ["salsa jar", ...]}
(pixel boxes; repeat a name for several examples of one product).
Text prompts are weak for amorphous things (spills, shelf gaps) and specific
SKUs; for spills/gaps, proposals are a starting point and most labels will be
drawn by hand.

Examples:
  python tools/auto_label.py --videos ../video-assets --out data/shelf \\
      --prompts "salsa jar,tortilla chips bag,cereal box" --frames-per-video 40
  python tools/auto_label.py --videos store.mp4 --out data/skus --examples examples.json
  python tools/auto_label.py --images my_frames/ --out data/people --coco 0 --sam sam2.1_t.pt
"""
from __future__ import annotations

import argparse
import random
from pathlib import Path

import cv2
import numpy as np
import yaml

COCO_DEFAULT = "yolo11n.pt"
YOLOE_DEFAULT = "yoloe-26n-seg.pt"


def sample_frames(videos: list[Path], per_video: int, out_dir: Path) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for v in videos:
        cap = cv2.VideoCapture(str(v))
        n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 1
        for k in range(per_video):
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(k * n / per_video))
            ok, frame = cap.read()
            if ok:
                p = out_dir / f"{v.stem}_{k:04d}.jpg"
                cv2.imwrite(str(p), frame)
                paths.append(p)
    return paths


def build_detector(args):
    if args.examples:
        import json

        from ultralytics import YOLOE

        spec = json.loads(args.examples.read_text())
        ref_path = Path(spec["image"])
        if not ref_path.is_absolute():
            ref_path = args.examples.parent / ref_path
        ref = cv2.imread(str(ref_path))
        if ref is None:
            raise SystemExit(f"cannot read reference image {ref_path}")
        names = list(dict.fromkeys(spec["names"]))
        model = YOLOE(args.model or YOLOE_DEFAULT)
        model.predict(ref, refer_image=ref, verbose=False, visual_prompts={
            "bboxes": np.asarray(spec["boxes"], np.float32),
            "cls": np.array([names.index(n) for n in spec["names"]])})
        return model, names, None
    if args.prompts:
        from ultralytics import YOLOE

        names = [p.strip() for p in args.prompts.split(",") if p.strip()]
        model = YOLOE(args.model or YOLOE_DEFAULT)
        model.set_classes(names)
        return model, names, None
    from ultralytics import YOLO

    model = YOLO(args.model or COCO_DEFAULT)
    ids = [int(c) for c in args.coco.split(",")]
    return model, [model.names[i] for i in ids], ids


def polygon_from_mask(mask: np.ndarray) -> np.ndarray | None:
    cnts, _ = cv2.findContours(mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not cnts:
        return None
    c = max(cnts, key=cv2.contourArea)
    c = cv2.approxPolyDP(c, 0.002 * cv2.arcLength(c, True), True)
    return c.reshape(-1, 2) if len(c) >= 3 else None


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--videos", type=Path, help="folder of .mp4 files (or a single video)")
    src.add_argument("--images", type=Path, help="folder of images")
    what = ap.add_mutually_exclusive_group(required=True)
    what.add_argument("--examples", type=Path, help="JSON with a reference image + boxed examples (visual prompts)")
    what.add_argument("--prompts", help="comma-separated YOLOE text prompts = class names")
    what.add_argument("--coco", help="comma-separated COCO class ids, e.g. 0 for person")
    ap.add_argument("--out", type=Path, required=True, help="output dataset folder")
    ap.add_argument("--model", help=f"detector weights (default {YOLOE_DEFAULT} / {COCO_DEFAULT})")
    ap.add_argument("--sam", help="SAM weights (e.g. sam2.1_t.pt) to write polygons instead of boxes")
    ap.add_argument("--conf", type=float, default=0.25)
    ap.add_argument("--frames-per-video", type=int, default=30)
    ap.add_argument("--val-frac", type=float, default=0.2)
    ap.add_argument("--device", default=None, help="cpu / 0 (default: auto)")
    args = ap.parse_args()

    staging = args.out / "_frames"
    if args.videos:
        vids = [args.videos] if args.videos.is_file() else sorted(args.videos.glob("*.mp4"))
        images = sample_frames(vids, args.frames_per_video, staging)
    else:
        images = sorted(p for p in args.images.iterdir() if p.suffix.lower() in (".jpg", ".jpeg", ".png"))
    if not images:
        raise SystemExit("no input frames found")

    det, names, coco_ids = build_detector(args)
    sam = None
    if args.sam:
        from ultralytics import SAM

        sam = SAM(args.sam)

    random.seed(0)
    random.shuffle(images)
    n_val = max(1, int(len(images) * args.val_frac)) if len(images) > 1 else 0
    counts = {n: 0 for n in names}
    for i, img_path in enumerate(images):
        split = "val" if i < n_val else "train"
        frame = cv2.imread(str(img_path))
        h, w = frame.shape[:2]
        r = det(frame, verbose=False, conf=args.conf, classes=coco_ids, device=args.device)[0]
        boxes = r.boxes.xyxy.cpu().numpy()
        cls = r.boxes.cls.cpu().numpy().astype(int)
        if coco_ids is not None:   # map COCO ids -> dataset ids 0..n-1
            cls = np.array([coco_ids.index(c) for c in cls], dtype=int)
        lines = []
        masks = None
        if sam is not None and len(boxes):
            masks = sam(frame, bboxes=boxes.tolist(), verbose=False, device=args.device)[0].masks
        for j, (b, c) in enumerate(zip(boxes, cls)):
            poly = polygon_from_mask(masks.data[j].cpu().numpy()) if masks is not None and j < len(masks.data) else None
            if poly is not None:
                coords = " ".join(f"{x / w:.6f} {y / h:.6f}" for x, y in poly)
            else:
                x1, y1, x2, y2 = b
                coords = f"{(x1 + x2) / 2 / w:.6f} {(y1 + y2) / 2 / h:.6f} {(x2 - x1) / w:.6f} {(y2 - y1) / h:.6f}"
            lines.append(f"{c} {coords}")
            counts[names[c]] += 1
        img_out = args.out / "images" / split / img_path.name
        lbl_out = args.out / "labels" / split / (img_path.stem + ".txt")
        img_out.parent.mkdir(parents=True, exist_ok=True)
        lbl_out.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(img_out), frame)
        lbl_out.write_text("\n".join(lines) + ("\n" if lines else ""))

    (args.out / "data.yaml").write_text(yaml.safe_dump({
        "path": str(args.out.resolve()), "train": "images/train", "val": "images/val",
        "names": dict(enumerate(names)),
    }, sort_keys=False))
    kind = "polygons (segment)" if sam else "boxes (detect)"
    print(f"wrote {len(images)} images ({n_val} val) with {kind} to {args.out}")
    print("pre-labels per class:", counts)
    print("next: review/correct in CVAT or Label Studio (YOLO format), then train - see docs/TRAINING.md")


if __name__ == "__main__":
    main()
