
import os
import matplotlib
matplotlib.use('Agg') # Use non-interactive backend
import matplotlib.pyplot as plt
import geopandas as gpd
import mercantile
from shapely.geometry import box
from pathlib import Path
from typing import Union, Dict
import rasterio
from rasterio.warp import calculate_default_transform, reproject, Resampling, transform_bounds
from rasterio.transform import from_bounds
from PIL import Image
import numpy as np
import math

from app.core.config import settings
from app.core.exceptions import TilingProcessError

class VectorTiler:
    def __init__(self, source_path: str, output_dir: Path, min_zoom=0, max_zoom=None):
        self.source_path = source_path
        self.output_dir = output_dir
        self.min_zoom = min_zoom
        self.max_zoom = max_zoom or 18 # Default ke 18 untuk vector jika tidak diatur
        self.gdf = None
        self.sindex = None

    def load_data(self):
        try:
            print(f"Loading Vector Data from: {self.source_path}")
            self.gdf = gpd.read_file(self.source_path)
            
            if self.gdf.crs != "EPSG:3857":
                self.gdf = self.gdf.to_crs(epsg=3857)
                
            self.sindex = self.gdf.sindex
        except Exception as e:
            raise TilingProcessError(f"Failed to load vector data: {str(e)}")

    def generate(self):
        if self.gdf is None: self.load_data()
        
        print("Starting Vector Tile Generation...")
        
        # Optimization: Only process tiles within bounds
        # Note: mercantile.tiles expects bounds in lng/lat (4326).
        # We need to convert 3857 bounds to 4326 - use geopandas for safety
        minx, miny, maxx, maxy = self.gdf.total_bounds
        bounds_gdf = gpd.GeoSeries([box(minx, miny, maxx, maxy)], crs="EPSG:3857").to_crs("EPSG:4326")
        b = bounds_gdf.total_bounds # minx, miny, maxx, maxy (lng, lat)

        for z in range(self.min_zoom, self.max_zoom + 1):
            tiles_bounds = list(mercantile.tiles(b[0], b[1], b[2], b[3], [z]))
            
            if not tiles_bounds: continue
            
            print(f"Processing Zoom {z}: {len(tiles_bounds)} tiles estimated.")

            for tile in tiles_bounds:
                self._render_tile(tile.z, tile.x, tile.y)

    def _render_tile(self, z, x, y):
        wm_bounds = mercantile.xy_bounds(x, y, z)
        bbox_polygon = box(wm_bounds.left, wm_bounds.bottom, wm_bounds.right, wm_bounds.top)
        
        possible_matches = list(self.sindex.intersection(bbox_polygon.bounds))
        if not possible_matches: return
        
        gdf_tile = self.gdf.iloc[possible_matches]
        gdf_tile = gdf_tile[gdf_tile.intersects(bbox_polygon)]
        
        if gdf_tile.empty: return

        fig, ax = plt.subplots(figsize=(2.56, 2.56), dpi=100)
        ax.set_axis_off()
        ax.set_xlim(wm_bounds.left, wm_bounds.right)
        ax.set_ylim(wm_bounds.bottom, wm_bounds.top)
        
        # Simple red styling for now, can be parameterized later
        gdf_tile.plot(ax=ax, facecolor='red', edgecolor='black', linewidth=0.5)
        
        folder_path = self.output_dir / str(z) / str(x)
        folder_path.mkdir(parents=True, exist_ok=True)
        file_path = folder_path / f"{y}.png"
        
        plt.savefig(file_path, format='png', bbox_inches='tight', pad_inches=0, transparent=True)
        plt.close(fig)

class RasterTiler:
    def __init__(self, source_path: str, output_dir: Path, min_zoom=0, max_zoom=None):
        self.source_path = source_path
        self.output_dir = output_dir
        self.min_zoom = min_zoom
        self.max_zoom = max_zoom
        
    def _calculate_max_zoom(self, src):
        """Mendeteksi zoom optimal berdasarkan resolusi piksel (Ground Sampling Distance)."""
        # Resolusi pada zoom 0 adalah ~156543 meter per piksel di equator
        initial_resolution = 156543.03392
        # Ambil pixel size (transform[0] adalah width of pixel)
        res_x = abs(src.transform[0])
        
        if res_x <= 0: return 12
        
        # Formula: zoom = log2(initial_resolution / pixel_resolution)
        detected_zoom = math.ceil(math.log2(initial_resolution / res_x))
        # Jangan terlalu jauh (limit ke 20 agar tidak overload disk)
        return min(max(detected_zoom, 0), 20)

    def generate(self):
        try:
            with rasterio.open(self.source_path) as src:
                if self.max_zoom is None:
                    self.max_zoom = self._calculate_max_zoom(src)
                    print(f"Detected optimal Max Zoom for Raster: {self.max_zoom}")

                for z in range(self.min_zoom, self.max_zoom + 1):
                    # For optimization, we should calculate bounds in 4326 to get tiles list
                    # Use transform_bounds to convert src bounds to EPSG:4326
                    if src.crs != "EPSG:4326":
                        min_lon, min_lat, max_lon, max_lat = transform_bounds(src.crs, "EPSG:4326", *src.bounds)
                    else:
                        min_lon, min_lat, max_lon, max_lat = src.bounds.left, src.bounds.bottom, src.bounds.right, src.bounds.top

                    tiles = list(mercantile.tiles(min_lon, min_lat, max_lon, max_lat, [z]))
                    
                    for t in tiles:
                        self._render_tile(src, t.z, t.x, t.y)
        except Exception as e:
             raise TilingProcessError(f"Raster processing failed: {str(e)}")

    def _render_tile(self, src, z, x, y):
        dst_bounds = mercantile.xy_bounds(x, y, z)
        width, height = 256, 256
        dst_transform = from_bounds(dst_bounds.left, dst_bounds.bottom, 
                                    dst_bounds.right, dst_bounds.top, 
                                    width, height)
        
        count = src.count
        dst_arr = np.zeros((count, height, width), dtype=np.uint8)

        try:
            reproject(
                source=rasterio.band(src, list(range(1, count + 1))),
                destination=dst_arr,
                src_transform=src.transform,
                src_crs=src.crs,
                dst_transform=dst_transform,
                dst_crs="EPSG:3857",
                resampling=Resampling.bilinear
            )
        except Exception:
            return

        # Check if empty (all zeros) - simple optimization
        if not np.any(dst_arr):
            return

        img = Image.fromarray(np.moveaxis(dst_arr, 0, -1))
        
        folder_path = self.output_dir / str(z) / str(x)
        folder_path.mkdir(parents=True, exist_ok=True)
        file_path = folder_path / f"{y}.png"
        
        img.save(file_path)

class TilingService:
    @staticmethod
    def process_tiling(task_type: str, source_path: Path, layer_id: str):
        output_dir = settings.TILES_DIR / layer_id
        
        try:
            if task_type == 'vector':
                tiler = VectorTiler(str(source_path), output_dir)
                tiler.generate()
            elif task_type == 'raster':
                tiler = RasterTiler(str(source_path), output_dir)
                tiler.generate()
            else:
                raise ValueError("Unknown task type")
            
            print(f"Tiling complete for {layer_id}")
            
        except Exception as e:
            print(f"Error in tiling job {layer_id}: {e}")
            # In a real app, update job status in DB
            raise e
