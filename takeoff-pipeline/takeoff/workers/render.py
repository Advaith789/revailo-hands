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
    is the sheet's 1-based position within its series. Series A starts at
    page 1 (there is no page 0); every later series starts at a multiple of
    SHEETS_PER_SERIES, so B is pages 100-199 (B-01..B-100).

    The number used to be ``page_no % (SHEETS_PER_SERIES - 1)``: a modulus
    of 99 over series of 100 pages, which wraps once per series and gave two
    pages the same label (100 and 199 were both B-01; also 299, 399, 499).
    Same label means same bytes, so the second page got the first page's
    measurement.
    """
    series = page_no // SHEETS_PER_SERIES
    first_page = max(1, series * SHEETS_PER_SERIES)
    return "{}-{:02d}".format(chr(ord("A") + series), page_no - first_page + 1)
