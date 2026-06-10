import logging
import zipfile
import tempfile
import os
from pathlib import Path

import requests
from geo.Geoserver import Geoserver

logger = logging.getLogger(__name__)


class GeoServerService:
    def __init__(self, url: str, username: str, password: str, workspace: str):
        self.geo = Geoserver(url, username=username, password=password)
        self.workspace = workspace
        self._base_url = url.rstrip("/")
        self._auth = (username, password)

    def publish_shp(self, final_path: str, store_name: str) -> dict:
        """
        Publish a SHP file to GeoServer.
        final_path: path to .shp, .zip, or extracted directory containing .shp
        store_name: name for datastore and feature type (shapefiles will be renamed to match)
        Returns dict with wms_url, wfs_url, layer_name, bbox (or None).
        """
        self._ensure_workspace()

        zip_path = self._to_zip(final_path, rename_to=store_name)
        try:
            self.geo.create_shp_datastore(
                path=zip_path,
                store_name=store_name,
                workspace=self.workspace,
            )
        finally:
            # Clean up temp zip if we created one
            if zip_path != final_path and os.path.exists(zip_path):
                os.remove(zip_path)

        bbox = self._recalculate_bbox(store_name)

        layer_name = f"{self.workspace}:{store_name}"
        wms_url = f"{self._base_url}/{self.workspace}/wms"
        wfs_url = f"{self._base_url}/{self.workspace}/wfs"

        return {
            "layer_name": layer_name,
            "store_name": store_name,
            "workspace": self.workspace,
            "wms_url": wms_url,
            "wfs_url": wfs_url,
            "bbox": bbox,
        }

    def _recalculate_bbox(self, store_name: str) -> list | None:
        """Force GeoServer menghitung ulang native/latlon bbox featuretype, lalu return
        latLonBoundingBox sebagai [west, south, east, north]. None jika gagal."""
        ft_url = (
            f"{self._base_url}/rest/workspaces/{self.workspace}"
            f"/datastores/{store_name}/featuretypes/{store_name}.json"
        )
        try:
            resp = requests.put(
                f"{ft_url}?recalculate=nativebbox,latlonbbox",
                json={"featureType": {"name": store_name, "enabled": True}},
                auth=self._auth,
                timeout=30,
            )
            if resp.status_code not in (200, 201):
                logger.warning(
                    "geoserver_bbox_recalculate_failed",
                    extra={"store": store_name, "status": resp.status_code, "body": resp.text[:300]},
                )

            resp = requests.get(ft_url, auth=self._auth, timeout=15)
            resp.raise_for_status()
            ll = (resp.json().get("featureType") or {}).get("latLonBoundingBox") or {}
            if all(k in ll for k in ("minx", "miny", "maxx", "maxy")):
                return [float(ll["minx"]), float(ll["miny"]), float(ll["maxx"]), float(ll["maxy"])]
        except Exception as exc:
            logger.warning(
                "geoserver_bbox_fetch_failed",
                extra={"store": store_name, "error": str(exc)},
            )
        return None

    def _ensure_workspace(self) -> None:
        try:
            self.geo.create_workspace(workspace=self.workspace)
        except Exception:
            pass

    def _to_zip(self, path: str, rename_to: str = None) -> str:
        """Return a zip file path usable by GeoServer REST API.

        If rename_to is provided, rename .shp, .dbf, .shx, .prj files to match.
        """
        p = Path(path)

        if p.suffix.lower() == ".zip":
            # If rename_to provided, need to repackage the zip with renamed files
            if rename_to:
                tmp = tempfile.mktemp(suffix=".zip")
                with zipfile.ZipFile(path, "r") as zf_in:
                    with zipfile.ZipFile(tmp, "w") as zf_out:
                        for item in zf_in.infolist():
                            data = zf_in.read(item.filename)
                            # Rename shapefiles (.shp, .dbf, .shx, .prj) to match store_name
                            ext = Path(item.filename).suffix.lower()
                            if ext in {'.shp', '.dbf', '.shx', '.prj'}:
                                new_name = f"{rename_to}{ext}"
                                zf_out.writestr(new_name, data)
                            else:
                                zf_out.writestr(item.filename, data)
                return tmp
            return path

        tmp = tempfile.mktemp(suffix=".zip")

        if p.is_dir():
            with zipfile.ZipFile(tmp, "w") as zf:
                for f in p.iterdir():
                    if f.is_file():
                        ext = f.suffix.lower()
                        if rename_to and ext in {'.shp', '.dbf', '.shx', '.prj'}:
                            zf.write(f, f"{rename_to}{ext}")
                        else:
                            zf.write(f, f.name)
        else:
            with zipfile.ZipFile(tmp, "w") as zf:
                for f in p.parent.glob(f"{p.stem}.*"):
                    if f.is_file():
                        ext = f.suffix.lower()
                        if rename_to and ext in {'.shp', '.dbf', '.shx', '.prj'}:
                            zf.write(f, f"{rename_to}{ext}")
                        else:
                            zf.write(f, f.name)

        return tmp
