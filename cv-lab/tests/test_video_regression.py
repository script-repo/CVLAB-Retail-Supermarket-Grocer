"""End-to-end regression tests: run analyzers over the bundled demo videos at
10 fps and check outcomes stay within tolerant ranges.

They catch behaviour changes from model, threshold or library upgrades. Ranges
are deliberately loose: they guard the story each demo tells, not exact numbers.
Mark: ``video`` (slow, downloads models on first run).
"""
from functools import lru_cache

import cv2
import pytest

from conftest import VIDEOS

pytestmark = pytest.mark.video
FPS = 10


@lru_cache(maxsize=None)
def run(usecase: str, video: str, params: tuple = ()) -> list[tuple[float, dict]]:
    """[(timestamp_s, metrics)] for every processed frame."""
    import app.usecases as U
    from app.schemas import AnalysisConfig

    path = VIDEOS / video
    if not path.exists():
        pytest.skip(f"missing {path}")
    cap = cv2.VideoCapture(str(path))
    src_fps = cap.get(cv2.CAP_PROP_FPS) or 24
    step = max(1, round(src_fps / FPS))
    analyzer = U.get_analyzer_cls(usecase)(fps=FPS)
    out, i = [], 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if i % step == 0:
            ts = i / src_fps
            if not out:
                analyzer.setup(frame.copy(), AnalysisConfig(video_id="t", usecase=usecase, params=dict(params)))
            _, metrics = analyzer.process_frame(frame, ts)
            out.append((ts, metrics))
        i += 1
    assert out, "no frames decoded"
    return out


def first(results, pred):
    return next((ts for ts, m in results if pred(m)), None)


SPILL = "uc-16-spill-hazard.mp4"
QUEUE = "uc-06-queue-length-monitoring.mp4"
DWELL = "uc-20-dwell-time-product-engagement.mp4"
SHELF = "uc-02-real-time-out-of-stock.mp4"
TRAFFIC = "uc-07-traffic-heat-map.mp4"


def test_uc16_spill_detected_then_cordoned():
    r = run("uc-16", SPILL)
    t_spill = first(r, lambda m: m["values"]["hazard"])
    t_cordon = first(r, lambda m: m["values"]["cordoned"])
    assert t_spill is not None and 0.3 <= t_spill <= 2.5, t_spill
    assert t_cordon is not None and 6.0 <= t_cordon <= 9.8, t_cordon
    assert r[-1][1]["status"] == "alert"          # still a hazard until cleaned up
    assert 5.0 <= r[-1][1]["values"]["response_s"] <= 9.5


def test_uc06_queue_alert_when_line_grows():
    r = run("uc-06", QUEUE)
    assert r[0][1]["status"] == "ok"
    t_alert = first(r, lambda m: m["status"] == "alert")
    assert t_alert is not None and 3.0 <= t_alert <= 8.0, t_alert
    assert 6 <= max(m["values"]["peak"] for _, m in r) <= 11


def test_uc20_engagement_and_reaches():
    v = run("uc-20", DWELL)[-1][1]["values"]
    assert 2 <= v["engagements"] <= 6
    assert v["pose"] and 1 <= v["product_reaches"] <= 6


def test_uc04_require_gesture_cuts_reviews():
    base = run("uc-04", QUEUE)[-1][1]["values"]
    strict = run("uc-04", QUEUE, (("require_gesture", True),))[-1][1]["values"]
    assert base["total_review_events"] >= 5
    assert strict["total_review_events"] <= 4
    assert strict["total_review_events"] < base["total_review_events"]


def test_uc04_no_reviews_while_browsing():
    v = run("uc-04", TRAFFIC)[-1][1]["values"]
    assert v["total_review_events"] <= 1 and v["shelf_to_bag_gestures"] <= 2


def test_uc02_flags_the_emptied_bay():
    r = run("uc-02", SHELF)
    assert r[0][1]["status"] == "ok"
    alerts = [m["values"]["low_zones"] for _, m in r if m["status"] == "alert"]
    assert alerts and all(zones == ["Bay 1"] for zones in alerts)


def test_uc07_counts_visitors():
    v = run("uc-07", TRAFFIC)[-1][1]["values"]
    assert 8 <= v["live_count"] <= 25
    assert v["unique_visitors"] >= v["live_count"]
