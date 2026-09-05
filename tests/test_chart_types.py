"""Numerical charts use supplied observations and the real, isolated Manim path."""
import copy
import json
import subprocess
from pathlib import Path

import pytest
from PIL import Image
from manim import Arrow, Dot, Rectangle, Text, tempconfig

from h3_slides.chart_data import histogram_data, nice_axis, format_tick
from h3_slides.diagram_spec import Element, ManimSceneSpec, designed_scene_schema
from h3_slides.diagrams import ManimRenderer
from h3_slides.manim_scene import build_scene
from h3_slides.models import ProjectInput
from h3_slides.storage import Store


def chart(kind, **data):
    return {"id": "chart", "type": kind, "x": 6, "y": 4.15, "width": 10, "height": 5.8,
            "text": "Dati osservati", **data}


def scene(element):
    return {"title": "Lettura dei dati", "takeaway": "Le misure restano quelle fornite.",
            "elements": [element], "connections": []}


def test_histogram_counts_boundaries_and_does_not_mutate_observations():
    samples, edges = [-2, -1, 0, 0, 1, 2], [-2, 0, 1, 2]
    original = copy.deepcopy((samples, edges))
    data = histogram_data(samples, edges)
    assert data["counts"] == [2, 2, 2]
    assert data["density"] is True
    assert data["heights"] == [1, 2, 2]
    assert sum(height*(b-a) for height, a, b in zip(data["heights"], edges, edges[1:])) == len(samples)
    assert (samples, edges) == original
    uniform = histogram_data([0, .5, 1, 2, 3, 3], [0, 1, 2, 3])
    assert uniform["counts"] == [2, 1, 3]
    assert uniform["heights"] == uniform["counts"]
    assert uniform["density"] is False


@pytest.mark.parametrize("data", [
    {"samples": [], "bin_edges": [0, 1]},
    {"samples": [1], "bin_edges": []},
    {"samples": [1], "bin_edges": [0, 1, 1]},
    {"samples": [1], "bin_edges": [2, 0]},
    {"samples": [-1], "bin_edges": [0, 1]},
    {"samples": [2], "bin_edges": [0, 1]},
    {"samples": [True], "bin_edges": [0, 1]},
    {"samples": [float("nan")], "bin_edges": [0, 1]},
    {"samples": [1], "bin_edges": [0, float("inf")]},
    {"samples": [1], "bin_edges": [0, 1], "values": [5]},
    {"samples": [1], "bin_edges": [0, 1], "labels": ["Categoria"]},
])
def test_histogram_rejects_missing_invalid_or_invented_frequencies(data):
    with pytest.raises(ValueError):
        Element.model_validate(chart("histogram", **data))


@pytest.mark.parametrize("data", [
    {"x_values": [1], "values": [2]},
    {"x_values": [1, 2], "values": [2]},
    {"x_values": [1, 2], "values": [2, 3], "labels": ["A"]},
    {"x_values": [True, 2], "values": [2, 3]},
    {"x_values": [1, 2], "values": [float("inf"), 3]},
])
def test_scatter_requires_observed_numeric_pairs(data):
    with pytest.raises(ValueError):
        Element.model_validate(chart("scatter", **data))


def test_per_shape_generation_contract_requires_the_right_data():
    schema = designed_scene_schema()
    variants = schema["properties"]["elements"]["items"]["anyOf"]
    by_kind = {variant["properties"]["type"].get("const"): variant for variant in variants}
    histogram, scatter = by_kind["histogram"], by_kind["scatter"]
    assert {"samples", "bin_edges"} <= set(histogram["required"])
    assert "values" not in histogram["properties"] and "labels" not in histogram["properties"]
    assert {"x_values", "values"} <= set(scatter["required"])
    assert "samples" not in scatter["properties"]
    assert by_kind["network"]["properties"]["labels"]["minItems"] == 1
    assert by_kind["network"]["properties"]["values"]["minItems"] == 0
    assert "directed" in by_kind["network"]["properties"]
    assert by_kind["bars"]["properties"]["values"]["items"]["minimum"] < 0
    with pytest.raises(ValueError, match="appartengono"):
        Element.model_validate(chart("bars", labels=["A"], values=[1], samples=[1]))


def test_schema_scopes_multiple_requested_families_and_removes_unused_definitions():
    def types(schema):
        result = set()
        for variant in schema["properties"]["elements"]["items"]["anyOf"]:
            shape = variant["properties"]["type"]
            result.update(shape.get("enum", [shape.get("const")]))
        return result
    full = designed_scene_schema()
    histogram = designed_scene_schema(("histogram",))
    assert types(histogram) == {"box", "decision", "circle", "database", "document", "text", "histogram"}
    assert "FunctionCurve" not in histogram["$defs"]
    assert len(json.dumps(histogram)) < len(json.dumps(full))*.6
    assert types(designed_scene_schema(("comparison",))) == types(full)
    assert types(designed_scene_schema(("flowchart",))) == {"box", "decision", "circle", "database", "document", "text"}
    combined = designed_scene_schema(("histogram", "function_plot", "comparison"))
    assert {"histogram", "function_plot"} <= types(combined)
    assert "scatter" not in types(combined) and "FunctionCurve" in combined["$defs"]


def test_explicit_plot_abscissae_preserve_spacing_and_require_increasing_order(tmp_path):
    for x_values in ([1, 1, 3], [1, 3, 2], [1, 3]):
        with pytest.raises(ValueError, match="crescente"):
            Element.model_validate(chart("plot", x_values=x_values, values=[1, 4, 2]))
    with tempconfig({"media_dir": str(tmp_path)}):
        _root, _header, _footer, stages, report = build_scene(scene(chart("plot", x_values=[0, 1, 10], values=[1, 4, 2])), {"theme": "paper"})
    points = [obj for obj in stages[0][1].get_family() if type(obj) is Dot]
    assert (points[2].get_x()-points[1].get_x())/(points[1].get_x()-points[0].get_x()) == pytest.approx(9)
    assert report["charts"][0]["points"] == [[0, 1], [1, 4], [10, 2]]
    assert report["plotted_curves"] == 1


def test_numeric_tick_format_does_not_merge_distinct_large_values():
    assert format_tick(999999999, 1) != format_tick(1000000000, 1)


@pytest.mark.parametrize("labels", [["A"], ["A", "B", "C"]])
def test_explicit_plot_rejects_point_label_count_before_rendering(labels):
    with pytest.raises(ValueError, match="etichetta per ogni punto"):
        Element.model_validate(chart("plot", x_values=[0, 1], values=[2, 3], labels=labels))
    for valid_labels in ([], ["A", "B"]):
        assert Element.model_validate(chart("plot", x_values=[0, 1], values=[2, 3], labels=valid_labels))


def test_subnormal_axis_returns_actionable_range_error_instead_of_stop_iteration():
    element = Element.model_validate(chart("scatter", x_values=[0, 2e-323], values=[1, 2]))
    with pytest.raises(ValueError, match="intervallo non rappresentabile"):
        nice_axis(element.x_values)


def test_subnormal_histogram_ticks_return_range_error_instead_of_overflow():
    element = Element.model_validate(chart("histogram", samples=[1e-6], bin_edges=[0, 5e-324, 1e-6]))
    step = min(b-a for a, b in zip(element.bin_edges, element.bin_edges[1:]))
    assert format_tick(0, step) == "0"
    with pytest.raises(ValueError, match="intervallo non rappresentabile"):
        format_tick(element.bin_edges[-1], step)


def test_chart_editor_roundtrips_specific_fields_in_a_headless_dom():
    root = Path(__file__).resolve().parents[1]
    script = r'''
import './tests/browser-env.mjs';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {chromium} from 'playwright-chromium';
const source=await readFile('static/app.mjs','utf8');
const editor=source.slice(source.indexOf('const elementTypes='),source.indexOf("$('edit-diagram-kind').onchange=showSceneEditor"));
assert.ok(editor.includes('function sceneFromEditor()'));
const browser=await chromium.launch({headless:true});
try{
  const page=await browser.newPage();
  await page.route('**/*',route=>{throw new Error('No network in editor fixture')});
  await page.setContent('<style>[hidden]{display:none!important}</style><input id="scene-title"><input id="scene-takeaway"><div id="scene-elements"></div><div id="scene-connections"></div>');
  await page.evaluate(code=>{eval('const $=id=>document.getElementById(id);'+code+';window.editor={fillSceneEditor,sceneFromEditor}')},editor);
  const cases=[
    {id:'hist',type:'histogram',x:6,y:4.15,width:10,height:5.8,samples:[0,1,1,3],bin_edges:[0,1,3],x_label:'Misura'},
    {id:'scatter',type:'scatter',x:6,y:4.15,width:10,height:5.8,x_values:[2,1,3],values:[4,-2,0],labels:['A','B','C'],y_label:'Risultato'},
    {id:'line',type:'plot',x:6,y:4.15,width:10,height:5.8,x_values:[0,1,10],values:[2,3,-1]},
    {id:'network',type:'network',x:6,y:4.15,width:10,height:5.8,labels:['A','B'],values:[0,1],directed:true},
  ];
  for(const element of cases){
    const result=await page.evaluate(element=>{
      window.editor.fillSceneEditor({title:'Dati',elements:[element],connections:[]});
      const row=document.querySelector('.scene-item');
      return {element:window.editor.sceneFromEditor().elements[0],histogramHidden:row.querySelector('.histogram-fields').hidden,
        scatterHidden:row.querySelector('.scatter-fields').hidden,networkHidden:row.querySelector('.network-fields').hidden};
    },element);
    for(const [key,value] of Object.entries(element))assert.deepEqual(result.element[key],value,key+' roundtrip');
    assert.equal(result.histogramHidden,element.type!=='histogram');
    assert.equal(result.scatterHidden,!['scatter','plot'].includes(element.type));
    assert.equal(result.networkHidden,element.type!=='network');
  }
  const converted=await page.evaluate(()=>{
    window.editor.fillSceneEditor({title:'Dati',elements:[{id:'old',type:'histogram',x:6,y:4.15,width:10,height:5.8,samples:[1,2],bin_edges:[1,2]}],connections:[]});
    const type=document.querySelector('[data-scene="type"]');type.value='scatter';type.dispatchEvent(new Event('change'));
    document.querySelector('[data-scene="x_values"]').value='1, 4';document.querySelector('[data-scene="values"]').value='-2, 3';
    return window.editor.sceneFromEditor().elements[0];
  });
  assert.deepEqual(converted.samples,[]);assert.deepEqual(converted.bin_edges,[]);
  assert.deepEqual(converted.x_values,[1,4]);assert.deepEqual(converted.values,[-2,3]);
}finally{await browser.close()}
'''
    node = root / "runtime" / "node" / "node.exe"
    subprocess.run([str(node), "--input-type=module", "-e", script], cwd=root, check=True,
                   capture_output=True, text=True, timeout=40)


@pytest.mark.parametrize("observations", [[0, 0], [-2, -2], [1e-6, 3e-6], [-1e9, 1e9]])
def test_axis_ranges_include_constant_negative_and_small_observations(observations):
    axis = nice_axis(observations)
    assert axis["min"] < axis["max"]
    assert all(axis["min"] <= value <= axis["max"] for value in observations)
    assert 2 <= len(axis["ticks"]) <= 8


@pytest.mark.parametrize("kind,data", [
    ("histogram", {"samples": [0, .5, 1, 1.5, 2, 2.5, 3], "bin_edges": [0, 1, 2, 3]}),
    ("histogram", {"samples": [0, 1, 1, 2, 4], "bin_edges": [0, 1, 4]}),
    ("scatter", {"x_values": [-3, 0, 1, 4], "values": [2, -2, 3, 1]}),
    ("scatter", {"x_values": [2, 2, 2], "values": [0, 0, 0]}),
    ("scatter", {"x_values": [2, 2, 2], "values": [0, 0, 0], "labels": ["A", "B", "C"]}),
    ("histogram", {"width": 5, "height": 3.5, "samples": [0, 0, 0, 1, 2, 2, 3], "bin_edges": [0, 1, 2, 3]}),
    ("scatter", {"width": 5, "height": 3.5, "x_values": [-3, 0, 1, 4], "values": [2, -2, 3, 1]}),
    ("bars", {"labels": ["Prima", "Dopo", "Saldo"], "values": [-3, 5, 0]}),
    ("bars", {"labels": ["Prima", "Dopo"], "values": [0, 0]}),
])
def test_native_chart_geometry_is_bounded_and_preserves_data(kind, data, tmp_path):
    value = scene(chart(kind, **data))
    original = copy.deepcopy(value)
    with tempconfig({"media_dir": str(tmp_path)}):
        root, _header, _footer, stages, report = build_scene(value, {"theme": "paper", "font": "Arial"})
    assert value == original
    assert report["bounds_checked"] and report["min_font_size"] >= 20
    assert root.width <= 12 and root.height <= 8
    result = report["charts"][0]
    objects = stages[0][1].get_family()
    labels = [obj for obj in objects if type(obj) is Text]
    for index, first in enumerate(labels):
        for second in labels[index+1:]:
            width = min(first.get_right()[0], second.get_right()[0])-max(first.get_left()[0], second.get_left()[0])
            height = min(first.get_top()[1], second.get_top()[1])-max(first.get_bottom()[1], second.get_bottom()[1])
            assert width <= .005 or height <= .005, f"Overlapping text: {first.text!r}, {second.text!r}"
    if kind == "histogram":
        bars = [obj for obj in objects if type(obj) is Rectangle]
        assert len(bars) == sum(count > 0 for count in result["counts"])
        for left, right in zip(bars, bars[1:]):
            assert left.get_right()[0] == pytest.approx(right.get_left()[0])
        assert sum(result["counts"]) == len(data["samples"])
        if result["density"]:
            assert bars[1].width / bars[0].width == pytest.approx(3)
    elif kind == "scatter":
        assert len([obj for obj in objects if type(obj) is Dot]) == len(data["values"])
        assert result["points"] == [list(pair) for pair in zip(data["x_values"], data["values"])]
        assert report["plotted_curves"] == 0
    else:
        assert result["values"] == data["values"]
        assert result["y_range"][0] <= 0 <= result["y_range"][1]


@pytest.mark.parametrize("labels,values,directed", [(["A"], [], False), (["A", "B"], [], False),
                                                     (["A", "B"], [0, 1], True)])
def test_network_supports_isolated_nodes_and_declared_directions(labels, values, directed, tmp_path):
    with tempconfig({"media_dir": str(tmp_path)}):
        root, _header, _footer, stages, report = build_scene(scene(chart("network", labels=labels, values=values,
                                                          directed=directed)), {"theme": "paper"})
    arrows = [obj for obj in stages[0][1].get_family() if type(obj) is Arrow]
    assert len(arrows) == (len(values)//2 if directed else 0)
    assert report["types"] == ["network"] and root.width <= 12


@pytest.mark.asyncio
@pytest.mark.parametrize("kind,data", [
    ("histogram", {"samples": [-1, 0, 0, 1, 2, 4], "bin_edges": [-1, 0, 2, 4], "x_label": "Valore"}),
    ("scatter", {"x_values": [-3, 0, 1, 4], "values": [2, -2, 3, 1], "x_label": "Tempo", "y_label": "Misura"}),
    ("plot", {"x_values": [0, 1, 10], "values": [1, 4, 2], "x_label": "Tempo", "y_label": "Misura"}),
])
async def test_real_headless_chart_render_and_cache(kind, data, tmp_path):
    store = Store(tmp_path / "data")
    try:
        project = store.create(ProjectInput(prompt="Fixture numerica", theme="paper", use_manim_diagrams=True).model_dump())
        diagram = {"kind": "manim", "labels": [], "brief": "Dati di prova", "scene": scene(chart(kind, **data))}
        renderer = ManimRenderer(store)
        rendered = await renderer.render(project["id"], diagram, project)
        assert rendered["report"]["ok"] and rendered["report"]["bounds_checked"]
        assert rendered["report"]["types"] == [kind]
        with Image.open(store.asset_path(project["id"], rendered["asset"])) as image:
            assert image.size == (1800, 1200)
        stored = json.loads(store.asset_path(project["id"], rendered["asset"].removesuffix(".png")+".json").read_text(encoding="utf-8"))
        assert stored["report"]["charts"][0]["type"] == kind
        cached = await renderer.render(project["id"], diagram, project)
        assert cached["cached"] is True
    finally:
        store.db.close()
