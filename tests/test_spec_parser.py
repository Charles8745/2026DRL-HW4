from data.spec_parser import parse_specs

R9 = (
    "【規格】\n引擎形式: 水冷四行程三汽缸\n座高(m): 830mm\n全重: 195kg\n"
    "總排氣量: 889cc\n最高馬力: 117hp @10,000 rpm\n最大扭力: 93Nm @7000 rpm\n油箱容量: 14公升\n"
)
ZX10R = (
    "【規格】\n引擎形式: 水冷四行程四汽缸\n座高(mm): 835\n淨重: 207\n"
    "總排氣量: 998cc\n壓縮比: 13.0 : 1\n油箱容量: 17公升\n"
)

def test_parses_core_numeric_fields():
    s = parse_specs(R9)
    assert s["displacement_cc"] == 889
    assert s["horsepower"] == 117
    assert s["torque_nm"] == 93.0
    assert s["seat_height_mm"] == 830
    assert s["weight_kg"] == 195

def test_missing_horsepower_is_none_not_fabricated():
    s = parse_specs(ZX10R)
    assert s["displacement_cc"] == 998
    assert s["horsepower"] is None       # ZX-10R has no hp line -> sentinel handled at display

def test_no_block_returns_empty_specs():
    s = parse_specs("no spec block here")
    assert s["displacement_cc"] is None and s["horsepower"] is None
