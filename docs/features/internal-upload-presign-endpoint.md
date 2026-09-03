# Internal Upload Presign Endpoint

Related plan: [Internal Upload Presign Endpoint](../plans/internal-upload-presign-endpoint.md)  
Related progress: [Internal Upload Presign Endpoint Progress](../progress/internal-upload-presign-endpoint.md)

Tileserver marks calls to Upload API with `X-Upload-Internal-Client: true`. Upload API therefore redirects artifact downloads to its internal MinIO endpoint rather than the browser-only public endpoint.

Tileserver Compose now persists its membership in `usermanagement_api_usermanagement_network`. This lets the `minio` hostname resolve after normal container recreation.
