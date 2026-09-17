import io
import json
import zipfile
from datetime import timedelta
from pathlib import Path

import geopandas as gpd
import pytest
from fastapi import FastAPI, UploadFile
from fastapi.testclient import TestClient
from shapely.geometry import box, Point, LineString, MultiPoint, GeometryCollection
from sqlalchemy import event
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, Session, create_engine, select

from app.analysis.reference_intersection import intersect_reference, validate_frame, measure
from app.application.reference_analysis import ReferenceAnalysis, AnalysisError, now, guard_source_delete
from app.core.config import Settings
from app.domain.models import Layer, UploadSession, AnalysisUpload, AnalysisReference, ReferenceAnalysisJob, ActiveAnalysisSource
from app.infrastructure.services.analysis_reference_source import load_reference
from app.infrastructure.services.reference_analysis_files import read_shapefile_archive, export_results
from app.infrastructure.wiring import default_analysis_reference_source, default_analysis_storage
from app.presentation.router.api.v1.endpoints import reference_analysis as endpoints


def frame(geometries, **attrs):
    return gpd.GeoDataFrame(attrs, geometry=geometries, crs=4326)


def archive(tmp_path, geometries=None):
    source = tmp_path / 'shape'
    source.mkdir(exist_ok=True)
    frame(geometries or [box(0, 0, 2, 1)]).to_file(source / 'input.shp')
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w') as zipped:
        for path in source.iterdir():
            zipped.write(path, path.name)
    return stream.getvalue()


@pytest.fixture
def workflow(tmp_path):
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    @event.listens_for(engine, 'connect')
    def foreign_keys(connection, _):
        connection.execute('PRAGMA foreign_keys=ON')
    SQLModel.metadata.create_all(engine)
    settings = Settings(UPLOAD_DIR=tmp_path / 'uploads', ANALYSIS_MAX_ACTIVE_JOBS=2)
    session = Session(engine)
    source = tmp_path / 'reference.geojson'
    frame([box(0, 0, 1, 1), box(1, 0, 2, 1)], zone=['Housing', None], hidden=['private', 'private']).to_file(source)
    session.add(UploadSession(id='upload-ref', filename=source.name, file_type='vector', layer_id='ref', total_size=source.stat().st_size, final_path=str(source)))
    session.commit()
    session.add(Layer(id='ref', filename='Pola ruang', file_type='vector', layer_type='geojson', tile_url_template='/public', upload_session_id='upload-ref', is_active=True, is_visible=True))
    session.commit()
    queued = []
    svc = ReferenceAnalysis(
        session,
        settings,
        lambda *args: queued.append(args),
        source=default_analysis_reference_source(),
        storage=default_analysis_storage(),
    )
    svc.configure('ref', {'name': 'Pola ruang', 'category_field': 'zone', 'attributes': ['zone']})
    yield svc, session, tmp_path, queued
    session.close()


def uploaded(svc, path, owner='owner'):
    return svc.upload(UploadFile(filename='input.zip', file=io.BytesIO(archive(path))), owner)


def test_pair_metrics_and_union_summary():
    source = frame([box(0, 0, 4, 1)])
    ref = frame([box(0, 0, 2, 1), box(1, 0, 3, 1)], zone=['A', 'A'])
    result = intersect_reference(source, ref, 'zone', ['zone'], 'run')
    assert [f['properties']['pct'] for f in result['features']] == pytest.approx([50, 50])
    assert result['summary'][0]['area_m2'] == pytest.approx(measure(box(0, 0, 3, 1), 2))
    assert result['summary'][0]['object_count'] == 1
    assert result['summary'][0]['overlap']
    assert len({f['properties']['ref_id'] for f in result['features']}) == 2


def test_categories_and_objects_remain_independent():
    source = frame([box(0, 0, 1, 1), box(0, 0, 1, 1)])
    ref = frame([box(0, 0, 1, 1), box(0, 0, 1, 1)], zone=['A', 'B'])
    result = intersect_reference(source, ref, 'zone', [], 'run')
    assert len(result['summary']) == 2
    assert all(row['object_count'] == 2 for row in result['summary'])
    assert all(row['area_m2'] == pytest.approx(2 * measure(box(0, 0, 1, 1), 2)) for row in result['summary'])


@pytest.mark.parametrize('geom,expected', [(Point(1, .5), 2), (MultiPoint([(1, .5), (.5, .5)]), 3)])
def test_points_include_both_boundary_categories(geom, expected):
    result = intersect_reference(frame([geom]), frame([box(0, 0, 1, 1), box(1, 0, 2, 1)], zone=['A', 'B']), 'zone', [], 'run')
    assert sum(f['properties']['point_count'] for f in result['features']) == expected
    assert any(f['properties']['relation'] == 'boundary' for f in result['features'])


def test_line_boundary_length_and_polygon_zero_area_contact():
    ref = frame([box(0, 0, 1, 1)], zone=['A'])
    line = intersect_reference(frame([LineString([(0, 0), (1, 0)])]), ref, 'zone', [], 'run')
    assert line['features'][0]['properties']['relation'] == 'boundary'
    assert line['features'][0]['properties']['length_m'] == pytest.approx(111319.490793, abs=.001)
    assert line['features'][0]['properties']['pct'] == pytest.approx(100)
    polygon = intersect_reference(frame([box(1, 0, 2, 1)]), ref, 'zone', [], 'run')
    assert polygon['features'][0]['properties']['area_m2'] == 0
    assert polygon['features'][0]['properties']['pct'] == 0


def test_collection_components_keep_source_identity():
    geometry = GeometryCollection([Point(.5, .5), LineString([(0, .5), (1, .5)]), box(.1, .1, .2, .2)])
    result = intersect_reference(frame([geometry]), frame([box(0, 0, 1, 1)], zone=['A']), 'zone', [], 'run')
    assert {f['properties']['source_dimension'] for f in result['features']} == {0, 1, 2}
    assert {f['properties']['src_id'] for f in result['features']} == {'run:0'}


def test_missing_category_and_attribute_allowlist():
    result = intersect_reference(frame([Point(.5, .5)]), frame([box(0, 0, 1, 1)], zone=[None], hidden=['secret']), 'zone', ['zone'], 'run')
    assert result['features'][0]['properties']['category_label'] == 'Kategori belum diisi'
    assert result['features'][0]['properties']['reference_attributes'] == {'zone': None}
    assert 'secret' not in json.dumps(result)
    assert result['warnings']


def test_empty_intersection_is_success():
    result = intersect_reference(frame([Point(9, 9)]), frame([box(0, 0, 1, 1)], zone=['A']), 'zone', [], 'run')
    assert result['features'] == result['summary'] == []


def test_invalid_geometry_crs_limits():
    with pytest.raises(ValueError, match='5000|5,000'):
        validate_frame(frame([Point(0, 0)] * 5001), max_features=5000)
    with pytest.raises(ValueError, match='CRS'):
        validate_frame(gpd.GeoDataFrame(geometry=[Point(0, 0)]))
    with pytest.raises(ValueError, match='Objek 1'):
        validate_frame(frame([None]))
    with pytest.raises(ValueError, match='titik penyusun'):
        validate_frame(frame([box(0, 0, 1, 1)]), max_vertices=2)


def test_archive_rejects_multiple_datasets_and_traversal(tmp_path):
    settings = Settings()
    for names in [['a.shp', 'b.shp'], ['../a.shp']]:
        path = tmp_path / 'bad.zip'
        with zipfile.ZipFile(path, 'w') as zipped:
            for name in names:
                zipped.writestr(name, 'x')
        with pytest.raises(ValueError):
            read_shapefile_archive(path, tmp_path / 'extract', settings)


def test_full_lifecycle_and_exports(workflow):
    svc, session, path, queued = workflow
    item = uploaded(svc, path)
    assert session.exec(select(Layer)).all()[0].is_visible
    assert len(session.exec(select(Layer)).all()) == 1
    job = svc.start(item['id'], 'ref', 'owner', operation='clip')
    assert queued and session.get(ActiveAnalysisSource, job['id'])
    with pytest.raises(AnalysisError) as error:
        svc.job(job['id'], 'another-browser')
    assert error.value.status == 404
    svc.execute(job['id'])
    finished = svc.job(job['id'], 'owner')
    assert finished['status'] == 'done', finished
    assert finished['operation'] == 'clip'
    assert not session.get(ActiveAnalysisSource, job['id'])
    assert finished['source_version']
    from datetime import datetime
    assert datetime.fromisoformat(finished['expires_at']) - datetime.fromisoformat(finished['completed_at']) == timedelta(hours=24)
    directory = svc.result(job['id'], 'owner')
    with zipfile.ZipFile(directory / 'shp.zip') as bundle:
        assert 'polygons.shp' in bundle.namelist()
        bundle.extractall(path / 'export')
    exported = gpd.read_file(path / 'export' / 'polygons.shp')
    assert 'area_ha' in exported.columns and 'src_id' in exported.columns
    with zipfile.ZipFile(directory / 'csv.zip') as bundle:
        assert set(bundle.namelist()) == {'details.csv', 'summary.csv'}
    saved = svc.save(job['id'], 'owner')
    assert saved['layer_id'] == f"reference-analysis-{job['id']}"
    assert svc.save(job['id'], 'owner')['layer_id'] == saved['layer_id']
    permanent = session.get(Layer, saved['layer_id'])
    assert permanent and permanent.is_active and permanent.is_visible
    saved_upload = session.get(UploadSession, permanent.upload_session_id)
    assert saved_upload and Path(saved_upload.final_path).is_file()
    svc.remove_reference('ref')
    layer = session.get(Layer, 'ref')
    guard_source_delete(session, layer.id)
    session.delete(layer)
    session.commit()
    assert svc.result(job['id'], 'owner').exists()
    record = session.get(AnalysisUpload, item['id'])
    record.expires_at = now() - timedelta(seconds=1)
    session.add(record)
    session.commit()
    assert svc.cleanup()['removed'] == 1
    assert not directory.exists()
    assert session.get(ReferenceAnalysisJob, job['id']) is None


def test_source_guards_survive_config_removal(workflow):
    svc, session, path, _ = workflow
    with pytest.raises(AnalysisError):
        guard_source_delete(session, 'ref')
    item = uploaded(svc, path)
    job = svc.start(item['id'], 'ref', 'owner')
    svc.remove_reference('ref')
    with pytest.raises(AnalysisError):
        guard_source_delete(session, 'ref')
    svc.fail(job['id'], 'test failure')
    guard_source_delete(session, 'ref')


def test_queue_failure_retains_input_until_failure_ttl(workflow):
    svc, session, path, _ = workflow
    item = uploaded(svc, path)
    def unavailable(*args):
        raise ConnectionError('broker unavailable')
    svc.enqueue = unavailable
    job = svc.start(item['id'], 'ref', 'owner')
    assert job['status'] == 'failed'
    assert job['expires_at']
    assert not session.get(ActiveAnalysisSource, job['id'])


def test_active_job_protects_expired_input_and_timeout_releases_pin(workflow):
    svc, session, path, _ = workflow
    item = uploaded(svc, path)
    job = svc.start(item['id'], 'ref', 'owner')
    upload = session.get(AnalysisUpload, item['id'])
    upload.expires_at = now() - timedelta(seconds=1)
    session.add(upload); session.commit()
    assert svc.cleanup()['removed'] == 0
    record = session.get(ReferenceAnalysisJob, job['id'])
    record.created_at = now() - timedelta(hours=2)
    session.add(record); session.commit()
    svc.cleanup()
    assert svc.job(job['id'], 'owner')['status'] == 'failed'
    assert not session.get(ActiveAnalysisSource, job['id'])


def test_api_guest_isolation_admin_guard_and_extra_reference(workflow):
    svc, session, path, _ = workflow
    app = FastAPI()
    app.include_router(endpoints.router, prefix='/api/v1')
    app.dependency_overrides[endpoints.service] = lambda: svc
    with TestClient(app) as client:
        assert client.get('/api/v1/analysis-workspace/references').status_code == 200
        assert client.get('/api/v1/analysis-references/ref').status_code == 401
        assert client.post('/api/v1/analysis-workspace/inputs', files={'file': ('a.zip', archive(path))}).status_code == 401
        headers = {'X-Analysis-Session': 'a' * 64}
        response = client.post('/api/v1/analysis-workspace/inputs', headers=headers, files={'file': ('a.zip', archive(path))})
        assert response.status_code == 201, response.text
        body = {'input_id': response.json()['id'], 'reference_id': 'ref', 'operation': 'spatial_join'}
        assert client.post('/api/v1/analysis-workspace/jobs', headers=headers, json={**body, 'reference_ids': ['ref', 'second']}).status_code == 422
        response = client.post('/api/v1/analysis-workspace/jobs', headers=headers, json=body)
        assert response.status_code == 202, response.text
        job_id = response.json()['id']
        assert response.json()['operation'] == 'spatial_join'
        assert client.get(f'/api/v1/analysis-workspace/jobs/{job_id}', headers={'X-Analysis-Session': 'b' * 64}).status_code == 404
        svc.execute(job_id)
        assert client.get(f'/api/v1/analysis-workspace/jobs/{job_id}/rows', headers=headers).json()['total'] == 2
        saved = client.post(f'/api/v1/analysis-workspace/jobs/{job_id}/save', headers=headers)
        assert saved.status_code == 200, saved.text
        assert saved.json()['layer_id'] == f'reference-analysis-{job_id}'
        for kind in ['geojson', 'csv', 'shp']:
            assert client.get(f'/api/v1/analysis-workspace/jobs/{job_id}/download?format={kind}', headers=headers).status_code == 200


def test_empty_result_exports_valid_bundles(tmp_path):
    result = intersect_reference(frame([Point(9, 9)]), frame([box(0, 0, 1, 1)], zone=['A']), 'zone', [], 'empty')
    export_results(tmp_path, result)
    with zipfile.ZipFile(tmp_path / 'shp.zip') as bundle:
        assert {'fields.json', 'result.geojson'} <= set(bundle.namelist())


@pytest.mark.parametrize('geometry', [Point(0, .5), LineString([(0, .2), (0, .8)])])
def test_same_category_boundary_inside_neighbour_counts_once(geometry):
    result = intersect_reference(frame([geometry]), frame([box(0, 0, 1, 1), box(-1, 0, 1, 1)], zone=['A', 'A']), 'zone', [], 'run')
    assert len(result['features']) == 2
    assert len(result['summary']) == 1
    assert result['summary'][0]['relation'] == 'intersection'
    assert result['bbox'] == list(geometry.bounds)


def test_output_limits_reject_without_truncating():
    source, ref = frame([box(0, 0, 1, 1)]), frame([box(0, 0, 1, 1)], zone=['A'])
    for limits in [{'max_results': 0}, {'max_output_bytes': 1}, {'max_output_vertices': 1}]:
        with pytest.raises(ValueError, match='melebihi batas'):
            intersect_reference(source, ref, 'zone', [], 'run', **limits)


def test_cleanup_continues_after_one_filesystem_failure(workflow, monkeypatch):
    svc, session, path, _ = workflow
    items = [uploaded(svc, path) for _ in range(2)]
    for item in items:
        record = session.get(AnalysisUpload, item['id'])
        record.expires_at = now() - timedelta(seconds=1)
        session.add(record)
    session.commit()
    original = svc.remove_upload
    def remove(identity, owner):
        if identity == items[0]['id']:
            raise PermissionError('temporary permission failure')
        original(identity, owner)
    monkeypatch.setattr(svc, 'remove_upload', remove)
    assert svc.cleanup()['removed'] == 1
    assert session.get(AnalysisUpload, items[0]['id']) is not None
    assert session.get(AnalysisUpload, items[1]['id']) is None


def test_latest_source_at_execution_and_immutable_completed_result(workflow):
    svc, session, path, _ = workflow
    item = uploaded(svc, path)
    job = svc.start(item['id'], 'ref', 'owner')
    source = path / 'reference.geojson'
    frame([box(0, 0, 2, 1)], zone=['Updated'], hidden=['private']).to_file(source)
    svc.execute(job['id'])
    result_path = svc.result(job['id'], 'owner') / 'result.geojson'
    result = result_path.read_bytes()
    assert json.loads(result)['summary'][0]['category'] == 'Updated'
    source.unlink()
    assert result_path.read_bytes() == result


def test_admin_can_detach_unreadable_source(workflow):
    svc, session, path, _ = workflow
    (path / 'reference.geojson').unlink()
    app = FastAPI()
    app.include_router(endpoints.router, prefix='/api/v1')
    app.dependency_overrides[endpoints.service] = lambda: svc
    app.dependency_overrides[endpoints.require_admin] = lambda: None
    with TestClient(app) as client:
        response = client.get('/api/v1/analysis-references/ref')
        assert response.status_code == 200
        assert response.json()['source_error']
        assert response.json()['config']['layer_id'] == 'ref'
        assert client.delete('/api/v1/analysis-references/ref').status_code == 200
        assert session.get(AnalysisReference, 'ref') is None

def test_reference_operations_clip_difference_spatial_join(workflow):
    from app.analysis.reference_operations import run_reference_operation, OPERATIONS
    svc, session, path, _ = workflow
    reference, _ = load_reference(session, session.get(Layer, 'ref'), svc.settings)
    source = validate_frame(frame([box(0, 0, 2, 1)]))
    assert set(OPERATIONS) == {"intersect", "clip", "difference", "spatial_join"}

    clipped = run_reference_operation("clip", source, reference, "zone", ["zone"], "run")
    assert {f["properties"]["relation"] for f in clipped["features"]} == {"intersection"}
    assert {f["properties"]["category_label"] for f in clipped["features"]} == {"Housing", "Kategori belum diisi"}
    assert sum(s["area_m2"] for s in clipped["summary"]) == pytest.approx(measure(box(0, 0, 2, 1), 2), rel=1e-6)

    diff = run_reference_operation("difference", source, reference, "zone", ["zone"], "run")
    # Source is fully covered by the two reference polygons, so nothing is left outside.
    assert diff["features"] == [] and diff["summary"] == [] and diff["warnings"]

    uncovered = validate_frame(frame([box(0, 0, 3, 1)]))
    diff = run_reference_operation("difference", uncovered, reference, "zone", ["zone"], "run")
    assert [f["properties"]["relation"] for f in diff["features"]] == ["difference"]
    assert diff["features"][0]["properties"]["category_label"] == "Di luar acuan"
    assert diff["summary"][0]["area_m2"] == pytest.approx(measure(box(2, 0, 3, 1), 2), rel=1e-6)

    joined = run_reference_operation("spatial_join", source, reference, "zone", ["zone"], "run")
    housing = [f for f in joined["features"] if f["properties"]["category"] == "Housing"]
    assert housing and housing[0]["properties"]["reference_attributes"] == {"zone": "Housing"}
    # Whole source geometry is kept and duplicated per matching reference polygon.
    assert all(f["properties"]["area_m2"] == pytest.approx(measure(box(0, 0, 2, 1), 2), rel=1e-6) for f in joined["features"])
    assert sum(s["object_count"] for s in joined["summary"]) == len(joined["features"]) == 2

def test_reference_operation_rejects_unknown(workflow):
    from app.analysis.reference_operations import run_reference_operation
    svc, session, path, _ = workflow
    with pytest.raises(ValueError):
        run_reference_operation("union", gpd.GeoDataFrame(), gpd.GeoDataFrame(), "zone", [], "run")
