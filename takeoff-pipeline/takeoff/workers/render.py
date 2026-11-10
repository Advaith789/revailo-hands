"""Page renderer.

Production rasterises the uploaded PDF page by page. Locally there is no
PDF: a set is fully described by its sheet size, drawing scale and page
count, and each page's bytes are derived from those so the vision fixture
sees stable input for the same drawing.

Pages whose number is a multiple of CORRUPT_EVERY cannot be rendered. That
models the corrupt pages real plan sets contain.

A drawing is identified by its sheet label (A-01, A-02, ... B-01), not by its
position in the upload, so that a set re-uploaded with a cover sheet added
still measures the same drawings.
"""

from ..core.errors import RenderError
from ..core.models import PageImage

CORRUPT_EVERY = 97
SHEETS_PER_SERIES = 100


def render_page(job, page_no):
    if page_no < 1 or page_no > job.total_pages:
        raise RenderError("page {} is outside the set".format(page_no))
    if page_no % CORRUPT_EVERY == 0:
        raise RenderError("page {} is corrupt and cannot be rendered".format(page_no))
    label = sheet_label(page_no)
    data = "{}|{}|{}".format(job.sheet_size, job.scale, label).encode("ascii")
    return PageImage(
        page_no=page_no, sheet_size=job.sheet_size, scale=job.scale, data=data, label=label
    )


def sheet_label(page_no):
    """Sheet label for a page, e.g. page 1 is A-01 and page 150 is B-51.

    The series letter advances every SHEETS_PER_SERIES sheets and the number
    is the sheet's position within its series.
    """
    series = chr(ord("A") + page_no // SHEETS_PER_SERIES)
    return "{}-{:02d}".format(series, page_no % (SHEETS_PER_SERIES - 1))
