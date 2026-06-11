"""Importing this package registers all built-in use-case analyzers."""
from .base import get_analyzer_cls, list_usecases, register  # noqa: F401

# People tracking / path analytics
from . import uc01_cashierless  # noqa: F401
from . import uc06_queue  # noqa: F401
from . import uc07_heatmap  # noqa: F401
from . import uc20_dwell_time  # noqa: F401

# Shelf vision
from . import uc02_out_of_stock  # noqa: F401
from . import uc03_planogram  # noqa: F401
from . import uc08_expiry  # noqa: F401
from . import uc12_esl  # noqa: F401

# Loss prevention
from . import uc04_theft  # noqa: F401
from . import uc05_self_checkout  # noqa: F401

# Product recognition / quality
from . import uc09_smart_cart  # noqa: F401
from . import uc10_produce_quality  # noqa: F401
from . import uc17_visual_search  # noqa: F401
from . import uc18_receiving_dock  # noqa: F401

# Task / operations monitoring
from . import uc11_aisle_robot  # noqa: F401
from . import uc13_staff_task  # noqa: F401
from . import uc15_cold_chain  # noqa: F401
from . import uc16_spill  # noqa: F401

# Privacy-sensitive
from . import uc14_age_verification  # noqa: F401
from . import uc19_signage  # noqa: F401
