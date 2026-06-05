from data.catalog import load_catalog, USAGE_BY_TITLE

def test_loads_all_33_rows():
    cat = load_catalog()
    assert len(cat) == 33

def test_brand_parsed_from_categories():
    cat = {c["title"]: c for c in load_catalog()}
    assert cat["YZF-R9"]["brand"] == "Yamaha"
    assert cat["CB300R"]["brand"] == "Honda"
    assert cat["Z 900 (ZR900-F)"]["brand"] == "Kawasaki"

def test_usage_from_lookup_table():
    cat = {c["title"]: c for c in load_catalog()}
    assert cat["YZF-R9"]["usage"] == "sport"
    assert cat["MT-07"]["usage"] == "naked"
    assert cat["AFRICA TWIN ES"]["usage"] == "adventure"

def test_price_is_int_and_specs_present():
    cat = {c["title"]: c for c in load_catalog()}
    assert cat["YZF-R9"]["price"] == 588000
    assert cat["YZF-R9"]["specs"]["displacement_cc"] == 889

def test_every_title_has_a_usage_label():
    for c in load_catalog():
        assert c["usage"] in {"sport","naked","touring","adventure","scooter","cruiser"}

def test_no_title_falls_back_to_default():
    # every CSV title must be explicitly present in USAGE_BY_TITLE (no silent 'naked' fallback)
    import csv, os
    from data.catalog import CSV_PATH, USAGE_BY_TITLE
    titles = [r["Title"].strip() for r in csv.DictReader(open(CSV_PATH, encoding="utf-8"))]
    missing = [t for t in titles if t not in USAGE_BY_TITLE]
    assert missing == [], f"titles missing from USAGE_BY_TITLE: {missing}"
