from unittest.mock import MagicMock, patch

from app.infrastructure.services.geoserver_service import GeoServerService


def test_publish_shp_url_sends_only_the_signed_source_url_and_returns_metadata():
    service = object.__new__(GeoServerService)
    service._base_url = "http://geoserver.internal/geoserver"
    service._wms_base_url = "https://maps.example/geoserver"
    service.workspace = "tileserver"
    service._auth = ("admin", "secret")
    response = MagicMock(status_code=201, text="created")

    with patch.object(service, "_ensure_workspace"), patch.object(
        service, "_recalculate_bbox", return_value=[1.0, 2.0, 3.0, 4.0]
    ), patch("app.infrastructure.services.geoserver_service.requests.put", return_value=response) as put:
        result = service.publish_shp_url("https://storage.example/artifact.zip?signature=secret", "roads")

    assert put.call_args.args[0].endswith("/rest/workspaces/tileserver/datastores/roads/url.shp")
    assert put.call_args.kwargs["data"] == b"https://storage.example/artifact.zip?signature=secret"
    assert put.call_args.kwargs["params"] == {"filename": "roads", "update": "overwrite"}
    assert result == {
        "layer_name": "tileserver:roads",
        "store_name": "roads",
        "workspace": "tileserver",
        "wms_url": "https://maps.example/geoserver/tileserver/wms",
        "wfs_url": "https://maps.example/geoserver/tileserver/wfs",
        "bbox": [1.0, 2.0, 3.0, 4.0],
    }
