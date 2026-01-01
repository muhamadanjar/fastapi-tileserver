# FastAPI TileServer

## Getting Started

1. Install the required dependencies:
```bash
pip install -r requirements.txt
```

2. Run the FastAPI server:
```bash
uvicorn app.main:app --reload
```



### Contoh ini jika Anda ingin generate tile dari data yang sudah ada di database
```python
postgis_config = {
    'type': 'postgis',
    'con': 'postgresql://user:password@localhost/dbname',
    'sql': 'SELECT geom, nama_jalan FROM jalan_besar'
}
```
### Panggil tiler (bisa dijadikan endpoint /trigger-tile-db)
```python
process_tiling(
    task_type='vector',
    source_input=postgis_config,
    layer_id='layer_postgis_jalan',
    min_zoom=10,
    max_zoom=16
)
```