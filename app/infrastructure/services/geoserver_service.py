import zipfile
import tempfile
import os
from pathlib import Path

from geo.Geoserver import Geoserver


class GeoServerService:
    def __init__(self, url: str, username: str, password: str, workspace: str):
        self.geo = Geoserver(url, username=username, password=password)
        self.workspace = workspace
        self._base_url = url.rstrip("/")

    def publish_shp(self, final_path: str, store_name: str) -> dict:
        """
        Publish a SHP file to GeoServer.
        final_path: path to .shp, .zip, or extracted directory containing .shp
        Returns dict with wms_url, wfs_url, layer_name.
        """
        self._ensure_workspace()

        zip_path = self._to_zip(final_path)
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

        layer_name = f"{self.workspace}:{store_name}"
        wms_url = f"{self._base_url}/{self.workspace}/wms"
        wfs_url = f"{self._base_url}/{self.workspace}/wfs"

        return {
            "layer_name": layer_name,
            "store_name": store_name,
            "workspace": self.workspace,
            "wms_url": wms_url,
            "wfs_url": wfs_url,
        }

    def _ensure_workspace(self) -> None:
        try:
            self.geo.create_workspace(workspace=self.workspace)
        except Exception:
            pass

    def _to_zip(self, path: str) -> str:
        """Return a zip file path usable by GeoServer REST API."""
        p = Path(path)

        if p.suffix.lower() == ".zip":
            return path

        tmp = tempfile.mktemp(suffix=".zip")

        if p.is_dir():
            with zipfile.ZipFile(tmp, "w") as zf:
                for f in p.iterdir():
                    if f.is_file():
                        zf.write(f, f.name)
        else:
            with zipfile.ZipFile(tmp, "w") as zf:
                for f in p.parent.glob(f"{p.stem}.*"):
                    if f.is_file():
                        zf.write(f, f.name)

        return tmp
