from app.core.style_utils import merge_style_state

SIMPLE = {"Polygon": {"fillColor": "#ff0000"}}
GENERATED_SLD = "<sld>simple</sld>"
CUSTOM_SLD = "<sld>custom</sld>"


def test_first_simple_save_stores_style_and_generated_sld():
    state = merge_style_state(None, mode="simple", style_name="layer_x",
                              sld_body=GENERATED_SLD, style=SIMPLE)
    assert state == {"mode": "simple", "style_name": "layer_x",
                     "style": SIMPLE, "sld_body": GENERATED_SLD}


def test_sld_save_keeps_previous_simple_settings():
    prev = merge_style_state(None, mode="simple", style_name="layer_x",
                             sld_body=GENERATED_SLD, style=SIMPLE)
    state = merge_style_state(prev, mode="sld", style_name="layer_x",
                              sld_body=CUSTOM_SLD)
    assert state["mode"] == "sld"
    assert state["sld_body"] == CUSTOM_SLD
    assert state["style"] == SIMPLE  # not discarded


def test_simple_save_after_sld_overwrites_sld_with_generated():
    prev = merge_style_state(None, mode="sld", style_name="layer_x",
                             sld_body=CUSTOM_SLD)
    state = merge_style_state(prev, mode="simple", style_name="layer_x",
                              sld_body=GENERATED_SLD, style=SIMPLE)
    assert state["mode"] == "simple"
    assert state["sld_body"] == GENERATED_SLD
    assert state["style"] == SIMPLE


def test_previous_dict_not_mutated():
    prev = {"mode": "simple", "style": SIMPLE, "sld_body": GENERATED_SLD,
            "style_name": "layer_x"}
    snapshot = dict(prev)
    merge_style_state(prev, mode="sld", style_name="layer_x", sld_body=CUSTOM_SLD)
    assert prev == snapshot
