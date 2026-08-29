import logging
import zipfile
import tempfile
import os
from pathlib import Path

import requests
from geo.Geoserver import Geoserver

from app.core.style_utils import convert_sld_11_to_10

logger = logging.getLogger(__name__)


class GeoServerStyleError(Exception):
    """Style operation failed. http_status is the HTTP status our API should return."""

    def __init__(self, http_status: int, detail: str):
        super().__init__(detail)
        self.http_status = http_status
        self.detail = detail


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

    def upsert_style(self, style_name: str, sld_body: str) -> None:
        """Create or update a workspace SLD style (rendering truth lives in GeoServer).

        Existence is checked explicitly via GET first: GeoServer's PUT to a
        non-existent style resource does not reliably return 404 (observed as
        400 "Invalid style:null" on GeoServer 2.27.4), so a status-code-based
        fallback from PUT->POST is not safe.
        """
        headers = {"Content-Type": "application/vnd.ogc.sld+xml"}
        sld_body = convert_sld_11_to_10(sld_body)
        style_url = f"{self._base_url}/rest/workspaces/{self.workspace}/styles/{style_name}"
        try:
            exists_resp = requests.get(
                f"{style_url}.json", auth=self._auth, timeout=30,
            )
            style_exists = exists_resp.status_code == 200

            if style_exists:
                resp = requests.put(
                    style_url, data=sld_body.encode("utf-8"),
                    headers=headers, auth=self._auth, timeout=30,
                )
            else:
                resp = requests.post(
                    f"{self._base_url}/rest/workspaces/{self.workspace}/styles?name={style_name}",
                    data=sld_body.encode("utf-8"),
                    headers=headers, auth=self._auth, timeout=30,
                )

            if resp.status_code in (200, 201):
                return
            if resp.status_code == 400:
                raise GeoServerStyleError(422, f"GeoServer rejected SLD: {resp.text[:500]}")
            raise GeoServerStyleError(
                502, f"GeoServer style upload failed ({resp.status_code}): {resp.text[:300]}"
            )
        except requests.RequestException as exc:
            raise GeoServerStyleError(502, f"GeoServer unreachable: {exc}")

    def set_default_style(self, layer_name: str, style_name: str) -> None:
        """Set a workspace style as the layer's default. layer_name is 'workspace:store'."""
        url = f"{self._base_url}/rest/layers/{layer_name}.json"
        payload = {"layer": {"defaultStyle": {"name": f"{self.workspace}:{style_name}"}}}
        try:
            resp = requests.put(url, json=payload, auth=self._auth, timeout=30)
            if resp.status_code not in (200, 201):
                raise GeoServerStyleError(
                    502, f"Failed to set default style ({resp.status_code}): {resp.text[:300]}"
                )
        except requests.RequestException as exc:
            raise GeoServerStyleError(502, f"GeoServer unreachable: {exc}")

    def get_default_style(self, layer_name: str) -> str | None:
        """Return the default style name currently set for a layer, or None if
        the layer/style is unreachable. layer_name is 'workspace:store'."""
        url = f"{self._base_url}/rest/layers/{layer_name}.json"
        try:
            resp = requests.get(url, auth=self._auth, timeout=30)
            if resp.status_code != 200:
                return None
            return ((resp.json().get("layer") or {}).get("defaultStyle") or {}).get("name")
        except requests.RequestException:
            return None
