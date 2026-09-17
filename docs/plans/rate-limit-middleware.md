# Rate Limit Middleware Plan

Related Progress: [Rate Limit Middleware Progress](../progress/rate-limit-middleware.md)

Add a Redis-backed fixed-window rate-limit middleware for API requests.

## Scope

- Add environment-driven request and window limits.
- Identify clients by remote IP address.
- Return standard rate-limit headers and `429 Too Many Requests` when the limit is exceeded.
- Fail open when Redis is unavailable so infrastructure degradation does not take down the API.
- Exclude health and API documentation endpoints.
- Cover the middleware behavior with focused tests and document configuration.
