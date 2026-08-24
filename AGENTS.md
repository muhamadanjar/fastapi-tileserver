

## Codebase Navigation

This project has a knowledge graph at graphify-out/ with god nodes, community structure, and cross-file relationships.

## Rules:
- For codebase questions, first run `graphify query "<question>"` when graphify-out/graph.json exists. Use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"` for focused concepts. These return a scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep output.
- **codebase-memory-mcp:** As an alternative, use `search_graph`, `trace_path`, and `get_code_snippet` for structural queries and call-graph tracing.
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
- After modifying code, run `graphify update .` to keep the graph current (AST-only, no API cost).
- Fall back to grep/`rg`, `Glob`, or direct file reads when graphify/codebase-memory is unavailable or insufficient.

## Architecture

The codebase is organized into distinct layers:

- **Domain Layer** (`app/domain/`): Entity definitions and repository interfaces (abstraction, no implementation details)
- **Application Layer** (`app/application/`): Business logic, services, DTOs, and use cases
- **Infrastructure Layer** (`app/infrastructure/`): Database implementations, storage adapters, message brokers, external service integrations
- **Presentation Layer** (`app/presentation/`): API routers and response schemas
- **Core** (`app/core/`): Cross-cutting concerns (exceptions, middleware, security, utilities)
- **Config** (`app/config/`): Environment-driven settings using Pydantic BaseSettings with nested configuration

## Database schema and migrations

- Make every database-field addition or change in the SQLModel model first.
- After updating the SQLModel model, generate an Alembic migration from that model change. Do not write Alembic migrations manually.
- Manual migrations are allowed only when strictly necessary, such as resolving a migration conflict with the existing database.
- Manually editing or creating a migration revision is also allowed when unavoidable to repair migration ordering, revision naming, or other migration metadata that Alembic cannot resolve safely.
- Keep the migration history clean, ordered, and free from overlapping changes.


### Feature Planning & Progress Tracking
- **Planning Storage**: Every new feature planning or architectural design MUST be documented in a separate file under the `docs/plans/` directory (e.g., `docs/plans/[feature-name].md`).
- **Progress Tracking**: Execution and implementation progress MUST be recorded in a corresponding file under `docs/progress/` (e.g., `docs/progress/[feature-name].md`).
- **Bidirectional Correlation**: 
  - The progress file MUST contain a prominent link to its respective plan file at the very top (e.g., `Related Plan: [Plan Name](../plans/[feature-name].md)`).
  - The plan file SHOULD also be updated to link to its active progress file once execution begins.
- **Workflow Strictness**: Do not start writing code before both the plan and progress files are initialized and linked.
- **Final Documentation (Definition of Done)**:
  - Once all tasks in the progress file are completed, the agent MUST create a final user/developer documentation in `docs/features/[feature-name].md`.
  - This final documentation must focus on *how the feature works* and *how to use it*, rather than the historical development progress.
  - Link the final feature documentation back to the original plan and progress files for historical archive.


### Git Operations — STRICTLY FORBIDDEN

**NO git write operations allowed:**
- ❌ `git commit` — FORBIDDEN
- ❌ `git push` — FORBIDDEN
- ❌ `git add` — FORBIDDEN
- ❌ `git rm` — FORBIDDEN
- ❌ `git merge` — FORBIDDEN
- ❌ `git rebase` — FORBIDDEN
- ❌ `git reset` — FORBIDDEN
- ❌ `git checkout` — FORBIDDEN
- ❌ `--force`, `--no-verify`, `--amend` flags — FORBIDDEN
- ❌ Any submodule operations — FORBIDDEN

**Only read-only operations allowed:**
- ✅ `git log` — View commit history
- ✅ `git status` — Check working tree status
- ✅ `git diff` — View changes
- ✅ `git show` — View commit details
