# Internal Upload Presign Endpoint

## Goal

Ensure Tileserver follows an S3 presigned artifact URL that is reachable from its Docker network.

## Design

Tileserver identifies its artifact-content request as internal. Upload API then signs the redirect with its internal MinIO endpoint while browser requests continue using the configured public endpoint.

Related progress: [Internal Upload Presign Endpoint Progress](../progress/internal-upload-presign-endpoint.md)
