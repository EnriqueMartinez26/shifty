from typing import Literal

BusinessType = Literal[
    "generic", "beauty", "medical", "wellness", "professional_services"
]

DEFAULT_BUSINESS_TYPE: BusinessType = "generic"
BUSINESS_TYPES: set[str] = {
    "generic",
    "beauty",
    "medical",
    "wellness",
    "professional_services",
}


def normalize_business_type(value: str | None) -> BusinessType:
    if value in BUSINESS_TYPES:
        return value  # type: ignore[return-value]
    return DEFAULT_BUSINESS_TYPE
