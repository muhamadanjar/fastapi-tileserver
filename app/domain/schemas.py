from pydantic import BaseModel
from typing import Optional

class TilingJobRequest(BaseModel):
    file_type: str # 'vector' or 'raster'
    layer_id: str

class TilingJobResponse(BaseModel):
    message: str
    file_type: str
    layer_id: str
    tile_url_template: str

class LayerInfo(BaseModel):
    id: str
    name: str
    type: str # vector / raster
    path: str
