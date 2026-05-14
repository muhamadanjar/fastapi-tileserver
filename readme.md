# FastAPI TileServer

## Getting Started

### Prerequisites
- Python 3.11+
- Docker (for RabbitMQ)

### Setup

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Start RabbitMQ (Docker):
```bash
docker run -d --name rabbitmq -p 5672:5672 -p 15672:15672 rabbitmq:3-management
```

3. Run FastAPI server (terminal 1):
```bash
uvicorn app.main:app --reload --port=8080
```

4. Run Celery worker (terminal 2):
```bash
celery -A app.workers.celery_app worker --loglevel=info
```

API docs available at `http://localhost:8080/docs`



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