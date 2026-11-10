"""Area units. The vision service reports square feet; some customers
display square metres."""

SQM_PER_SQFT = 0.09290304
SQFT_PER_SQM = 1.0 / SQM_PER_SQFT

_SUPPORTED = ("sqft", "sqm")


def convert(area_sqft, units):
    if units == "sqft":
        return area_sqft
    if units == "sqm":
        return area_sqft * SQM_PER_SQFT
    raise ValueError("unsupported units {!r}; expected one of {}".format(units, _SUPPORTED))


def label(units):
    return {"sqft": "sq ft", "sqm": "sq m"}[units]
