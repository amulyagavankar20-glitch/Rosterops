from app.frontend_helpers import build_brand_map, build_process_options


def test_brand_map_handles_empty_response():
    assert build_brand_map([]) == {}
    assert build_brand_map(None) == {}


def test_brand_map_and_process_options_use_api_records():
    brands = [
        {
            "id": 7,
            "name": "NovaWear",
            "processes": [{"id": 11, "name": "CS"}],
        }
    ]

    brand_map = build_brand_map(brands)

    assert brand_map["NovaWear"]["id"] == 7
    assert build_process_options(brand_map["NovaWear"]) == {"CS": 11}
