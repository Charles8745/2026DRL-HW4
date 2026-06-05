import re

# alias map: normalized-key -> list of raw key prefixes that mean it
_ALIASES = {
    "displacement_cc": ["總排氣量", "排氣量"],
    "horsepower": ["最高馬力", "最大馬力", "馬力"],
    "torque_nm": ["最大扭力", "扭力"],
    "seat_height_mm": ["座高"],
    "weight_kg": ["全重", "淨重", "車重"],
    "engine": ["引擎形式"],
}
_KEYS = {"displacement_cc": None, "horsepower": None, "torque_nm": None,
         "seat_height_mm": None, "weight_kg": None, "engine": None}

def _num(value: str):
    m = re.search(r"-?\d+(?:\.\d+)?", value.replace(",", ""))
    return m.group(0) if m else None

def parse_specs(description: str) -> dict:
    specs = dict(_KEYS)
    start = description.find("【規格】")
    block = description[start:] if start >= 0 else ""
    for line in block.splitlines():
        if ":" not in line and "：" not in line:
            continue
        raw_key, _, raw_val = re.split(r"([:：])", line, maxsplit=1)
        key = re.sub(r"\(.*?\)", "", raw_key).strip()      # drop "(m)"/"(mm)" units in key
        for norm, prefixes in _ALIASES.items():
            if any(key.startswith(p) for p in prefixes) and specs[norm] is None:
                if norm == "engine":
                    specs[norm] = raw_val.strip()
                else:
                    n = _num(raw_val)
                    if n is None:
                        continue
                    if norm == "torque_nm":
                        specs[norm] = float(n)
                    else:
                        specs[norm] = int(float(n))
                break
    return specs
