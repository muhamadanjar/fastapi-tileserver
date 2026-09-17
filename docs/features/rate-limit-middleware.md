# Rate Limit Middleware

Related Plan: [Rate Limit Middleware Plan](../plans/rate-limit-middleware.md)  
Related Progress: [Rate Limit Middleware Progress](../progress/rate-limit-middleware.md)

TileServer membatasi request HTTP per alamat IP menggunakan counter fixed-window di Redis.
Konfigurasi default adalah 100 request per 60 detik. Ketika batas terlampaui, API
mengembalikan `429` dengan header `Retry-After`.

Setiap response yang dikenai limiter menyertakan:

- `X-RateLimit-Limit`
- `X-RateLimit-Remaining`
- `X-RateLimit-Reset` (Unix timestamp akhir window)

Konfigurasi melalui environment:

```dotenv
RATE_LIMIT_ENABLED=true
RATE_LIMIT_REQUESTS=100
RATE_LIMIT_WINDOW_SECONDS=60
RATE_LIMIT_KEY_PREFIX=tileserver:rate-limit
```

`/health`, `/docs`, `/redoc`, dan `/openapi.json` dikecualikan. Jika Redis tidak
tersedia, middleware mencatat warning lalu mengizinkan request (fail-open).
