import json
from pathlib import Path
from types import SimpleNamespace

import geopandas as gpd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from shapely.geometry import Polygon, box, mapping
from sqlalchemy import event
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.api.v1.endpoints.analysis import get_analysis_usecase, router
from app.domain.models import AnalysisResult, Layer, UploadSession
from app.infrastructure.db.connection import get_sync_session
from app.infrastructure.db.repository import (
    SyncAnalysisResultRepository, SyncLayerRepository, SyncUploadSessionRepository,
)
from app.infrastructure.services.analysis_export import AnalysisExportService
from app.usecases.overlay_analysis import OverlayAnalysisUseCase


class Queue:
    def __init__(self):
        self.pending = []

    def enqueue(self, request, result_id, layer_id, analysis_result_id):
        self.pending.append((json.loads(json.dumps(request)), result_id, layer_id, analysis_result_id))
        return "test-task"


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        queue = Queue()
        uc = OverlayAnalysisUseCase(
            SyncLayerRepository(session), SyncAnalysisResultRepository(session),
            SyncUploadSessionRepository(session), lambda _: [],
            AnalysisExportService(Path("data/uploads")), queue,
        )
        app = FastAPI()
        app.include_router(router, prefix="/api/v1/analysis")
        app.dependency_overrides[get_analysis_usecase] = lambda: uc
        app.dependency_overrides[get_sync_session] = lambda: session

        def add_layer(side, geometries, codes):
            path = tmp_path / f"{side}.gpkg"
            gpd.GeoDataFrame({"code": codes, "name": [f"name-{c}" for c in codes]},
                             geometry=geometries, crs=6933).to_file(path, driver="GPKG")
            upload = UploadSession(id=f"upload-{side}", layer_id=side, filename=path.name,
                                   file_type="vector", total_size=path.stat().st_size, final_path=str(path))
            session.add(upload)
            session.commit()
            uc.layer_repo.create(Layer(id=side, upload_session_id=upload.id, filename=path.name,
                                       file_type="vector", layer_type="vector", tile_url_template=""))

        add_layer("a", [box(0, 0, 1000, 1000)], ["A"])
        add_layer("b", [box(800, 0, 1200, 1000)], ["B"])
        with TestClient(app) as client:
            yield client, uc, queue, session, add_layer
    engine.dispose()


def request(**overrides):
    return {
        "operation": "intersection", "input_layer_a_id": "a", "input_layer_b_id": "b",
        "calculate_area": True, "source_id_field_a": "code", "source_id_field_b": "code",
        "selected_attributes": {"layer_a": ["name"], "layer_b": []},
        **overrides,
    }


def assert_result(client, layer_id):
    preview = client.get(f"/api/v1/analysis/{layer_id}/preview")
    assert preview.status_code == 200, preview.text
    props = preview.json()["features"][0]["properties"]
    assert props["area_m2"] == pytest.approx(200_000)
    assert props["area_ha"] == pytest.approx(20)
    assert props["pct_a"] == pytest.approx(20)
    assert props["pct_b"] == pytest.approx(50)
    assert props["a_name"] == "name-A"
    assert "b_name" not in props
    sources = client.get(f"/api/v1/analysis/{layer_id}/sources")
    assert sources.status_code == 200
    snapshot = sources.json()
    for side in ("a", "b"):
        feature = snapshot[f"layer_{side}"]["features"][props[f"src_{side}_row"]]
        assert feature["id"] == props[f"src_{side}_id"]
        assert feature["properties"]["name"] == f"name-{side.upper()}"
    return props


def test_sync_validate_preview_export_save_and_discard(api, tmp_path):
    client, uc, _, session, _ = api
    validation = client.post("/api/v1/analysis/validate", json=request())
    assert validation.status_code == 200 and validation.json()["valid"]
    operations = client.get("/api/v1/analysis/operations").json()["operations"]
    assert "calculate_area" in next(op for op in operations if op["name"] == "intersection")["optional_params"]
    response = client.post("/api/v1/analysis/run", json=request())
    assert response.status_code == 200, response.text
    layer_id = response.json()["result_layer_id"]
    props = assert_result(client, layer_id)
    assert props["src_a_id"] == "A" and props["src_b_id"] == "B"
    layer = uc.layer_repo.get_by_id(layer_id)
    assert layer.file_metadata["analysis"]["area_metrics"]["measurement_crs"] == "EPSG:6933"
    assert "area_ha" in layer.file_metadata["fields"]
    for export_format in ("geojson", "shp"):
        response = client.get(f"/api/v1/analysis/{layer_id}/download?format={export_format}")
        assert response.status_code == 200
        path = tmp_path / ("export.zip" if export_format == "shp" else "export.geojson")
        path.write_bytes(response.content)
        exported = gpd.read_file(path)
        assert exported.iloc[0].area_m2 == pytest.approx(200_000)
        assert exported.iloc[0].src_a_id == "A"
    assert client.post(f"/api/v1/analysis/{layer_id}/save").status_code == 200
    result = uc.analysis_repo.get_by_layer_id(layer_id)
    assert not result.ephemeral
    source_file = Path(result.result_file_path).with_name("sources.json")
    assert source_file.exists()
    assert client.delete(f"/api/v1/analysis/{layer_id}").status_code == 200
    assert not source_file.exists()
    assert client.get(f"/api/v1/analysis/{layer_id}/sources").status_code == 404


def test_async_worker_path_retains_options_generated_ids_and_metadata(api):
    client, uc, queue, _, _ = api
    response = client.post("/api/v1/analysis/run", json=request(
        async_run=True, source_id_field_a=None, source_id_field_b=None,
    ))
    assert response.status_code == 200, response.text
    assert response.json()["async_task_id"] == "test-task"
    public_status_url = f"/api/v1/analysis/status/{response.json()['result_layer_id']}"
    assert client.get(public_status_url).json()["status"] == "pending"
    queued = queue.pending.pop()
    result_id = queued[1]
    assert client.get(f"/api/v1/analysis/status/{result_id}").json()["status"] == "pending"
    uc.execute_pending_analysis(*queued)
    status = client.get(f"/api/v1/analysis/status/{result_id}").json()
    assert status["status"] == "done" and status["feature_count"] == 1
    assert client.get(public_status_url).json()["status"] == "done"
    props = assert_result(client, response.json()["result_layer_id"])
    assert props["src_a_id"] == f"{result_id}:a:0"
    assert props["src_b_id"] == f"{result_id}:b:0"
    layer = uc.layer_repo.get_by_id(response.json()["result_layer_id"])
    assert layer.file_metadata["analysis"]["area_metrics"]["id_scope"] == result_id


def test_invalid_geometry_preflight_and_sync_write_nothing(api):
    client, uc, _, session, add_layer = api
    add_layer("invalid", [Polygon([(0, 0), (10, 10), (0, 10), (10, 0), (0, 0)])], ["BROKEN"])
    body = request(input_layer_a_id="invalid")
    response = client.post("/api/v1/analysis/validate", json=body)
    assert not response.json()["valid"]
    assert "BROKEN" in str(response.json()["errors"])
    response = client.post("/api/v1/analysis/run", json=body)
    assert response.status_code == 400 and "Self-intersection" in response.text
    assert session.exec(select(AnalysisResult)).all() == []
    assert not list(Path("data/uploads").glob("*/result.geojson"))


def test_async_validation_failure_is_reported(api):
    client, uc, queue, _, add_layer = api
    add_layer("invalid", [Polygon([(0, 0), (10, 10), (0, 10), (10, 0), (0, 0)])], ["BROKEN"])
    response = client.post("/api/v1/analysis/run", json=request(input_layer_a_id="invalid", async_run=True))
    assert response.status_code == 200
    queued = queue.pending.pop()
    with pytest.raises(ValueError, match="BROKEN"):
        uc.execute_pending_analysis(*queued)
    status = client.get(f"/api/v1/analysis/status/{queued[1]}").json()
    assert status["status"] == "failed" and "BROKEN" in status["error_message"]


@pytest.mark.parametrize("body", [request(operation="union"), request(calculate_area=False)])
def test_invalid_option_combinations_rejected_sync_and_async(api, body):
    client, _, queue, _, _ = api
    assert not client.post("/api/v1/analysis/validate", json=body).json()["valid"]
    for asynchronous in (False, True):
        response = client.post("/api/v1/analysis/run", json={**body, "async_run": asynchronous})
        assert response.status_code == 400
    assert not queue.pending


def test_empty_enhanced_result_and_legacy_compatibility(api):
    client, uc, _, _, add_layer = api
    add_layer("touch", [box(1000, 0, 2000, 1000)], ["T"])
    response = client.post("/api/v1/analysis/run", json=request(input_layer_b_id="touch"))
    assert response.status_code == 200, response.text
    assert response.json()["feature_count"] == 0 and response.json()["warning"]
    layer_id = response.json()["result_layer_id"]
    assert client.get(f"/api/v1/analysis/{layer_id}/preview").json()["features"] == []
    assert "area_m2" in uc.layer_repo.get_by_id(layer_id).file_metadata["fields"]
    assert client.get(f"/api/v1/analysis/{layer_id}/sources").status_code == 200

    legacy = {"operation": "intersection", "input_layer_a_id": "a", "input_layer_b_id": "b"}
    response = client.post("/api/v1/analysis/run", json=legacy)
    assert response.status_code == 200
    layer_id = response.json()["result_layer_id"]
    properties = client.get(f"/api/v1/analysis/{layer_id}/preview").json()["features"][0]["properties"]
    assert "code_1" in properties and "area_m2" not in properties
    assert client.get(f"/api/v1/analysis/{layer_id}/sources").status_code == 404


def test_result_layers_can_be_used_as_input_and_custom_export_path_is_previewed(api, tmp_path):
    client, uc, _, _, _ = api
    uc.export_service.upload_dir = tmp_path / "custom-results"
    response = client.post("/api/v1/analysis/run", json=request())
    assert response.status_code == 200, response.text
    layer_id = response.json()["result_layer_id"]
    assert_result(client, layer_id)
    second = client.post("/api/v1/analysis/run", json=request(
        input_layer_a_id=layer_id, source_id_field_a="src_a_id", selected_attributes=None,
    ))
    assert second.status_code == 200, second.text
    props = client.get(second.json()["geojson_url"]).json()["features"][0]["properties"]
    assert props["pct_a"] == pytest.approx(100, rel=1e-6)
    assert props["area_ha"] == pytest.approx(20, rel=1e-6)


def test_survey_layer_geojson_geometries_and_feature_ids(api):
    client, uc, _, _, _ = api
    geometry = gpd.GeoSeries([box(0, 0, 1000, 1000)], crs=6933).to_crs(4326).iloc[0]
    uc.layer_repo.create(Layer(
        id="survey", filename="survey", file_type="vector", layer_type="geojson",
        tile_url_template="", file_metadata={"project_id": "project"},
    ))
    uc.get_project_features_fn = lambda _: [SimpleNamespace(
        id="survey-feature", geometry=mapping(geometry),
        attributes={"name": "survey", "geometry": "attribute must not override spatial geometry"},
    )]
    response = client.post("/api/v1/analysis/run", json=request(
        input_layer_a_id="survey", source_id_field_a="_feature_id",
    ))
    assert response.status_code == 200, response.text
    props = client.get(response.json()["geojson_url"]).json()["features"][0]["properties"]
    assert props["src_a_id"] == "survey-feature"
    assert props["area_ha"] == pytest.approx(20, rel=1e-6)
