"""Pure helpers for building Streamlit selection data from API responses."""


def build_brand_map(brands):
    """Index valid brand records by their display name."""
    return {
        brand["name"]: brand
        for brand in (brands or [])
        if isinstance(brand, dict) and brand.get("name") and brand.get("id") is not None
    }


def build_process_options(brand):
    """Return a display-name to process-id mapping for one brand."""
    return {
        process["name"]: process["id"]
        for process in (brand or {}).get("processes", [])
        if isinstance(process, dict)
        and process.get("name")
        and process.get("id") is not None
    }
