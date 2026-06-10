# Cancel Task Feature Design for Tileserver API

## Executive Summary

This document outlines the recommended approach for implementing task cancellation in the tileserver_api tiling workflow. The design prioritizes **state consistency**, **safe resource cleanup**, and **clear user semantics** while working within the constraints of Celery + RabbitMQ + PostgreSQL.

---

## Current State Analysis

### Existing Tiling Flow

```
1. User: POST /uploads/{upload_id}/tile
   ↓
2. Endpoint: Set status=processing → Queue Celery task
   ↓
3. Celery Worker: Consume task from RabbitMQ
   ↓
4. process_tiling_task(): 
   - Create placeholder Layer with tile_process progress
   - Call TilingService.process_tiling() (long-running, GPU/CPU bound)
   - Update Layer.file_metadata.tile_process on progress callbacks
   - On completion: Set status=done, update Layer with tile_url_template
   - On failure: Set status=failed, update error_message
   ↓
5. Database State: UploadSession + Layer record finalized
```

### Critical Constraints

1. **No task_id tracking** — `UploadSession` model does NOT store celery task IDs currently
2. **Async repository pattern** — FastAPI endpoints use `UploadSessionRepository` (async); workers use `SyncUploadSessionRepository` (sync)
3. **Long-running process** — `TilingService.process_tiling()` is not checkpointed; no mid-process pause/resume mechanism exists
4. **RabbitMQ broker** — No persistent task store; tasks only live in broker queue + worker memory
5. **No graceful shutdown signal** — Workers accept tasks via SIGTERM but don't listen for per-task cancellation signals

---

## Recommended Design: Option A (Preferred)

### Why This Approach?

This design is recommended because it:
- ✓ Requires **minimal schema changes** (one column addition)
- ✓ Works **within Celery's native patterns** (revoke + signal handling)
- ✓ Provides **clean state semantics** (cancelled status is unambiguous)
- ✓ Enables **safe cleanup** (identifies what to rollback)
- ✓ **Survives worker crashes** (database state is source of truth, not Celery state)
- ✓ **Supports audit trails** (status history shows intent, not just outcome)

**Trade-off:** Partial tile cleanup requires manual detection (not automatic sweep); tasks already executing cannot be killed instantly.

---

## Detailed Design

### 1. Data Model Changes

#### Add to `UploadSession` (Schema Migration Required)

```python
# File: app/domain/models.py

class UploadSession(SQLModel, table=True):
    __tablename__ = "upload_sessions"
    
    # ... existing fields ...
    
    # NEW FIELDS:
    celery_task_id: Optional[str] = Field(default=None)
    # Stores Celery task UUID when task is queued.
    # Cleared when task completes/fails/is cancelled.
    # Enables reliable task revocation.
    
    cancel_requested_at: Optional[datetime] = Field(
        default=None, 
        sa_column=Column(DateTime(timezone=True))
    )
    # Timestamp when cancellation was requested.
    # Non-null only if status='cancelled'.
    # Useful for audit trail and detecting stale cancellation requests.
```

#### New JobStatus Enum Value

```python
class JobStatus(str, enum.Enum):
    pending = "pending"
    uploaded = "uploaded"
    uploading = "uploading"
    paused = "paused"
    processing = "processing"
    done = "done"
    failed = "failed"
    expired = "expired"
    cancelled = "cancelled"  # NEW: User explicitly cancelled
```

### 2. Endpoint Design

#### POST or DELETE?

**Recommendation: `DELETE /uploads/{upload_id}/tile`**

**Rationale:**
- DELETE semantics express "remove this operation" better than POST `/cancel`
- REST principle: DELETE = destruction of a resource (the running task is the resource)
- Aligns with HTTP method semantics: idempotent, clear intent
- Reduces cognitive load: users don't ask "what's the difference between POST /tile/cancel and POST /tile?"

**Alternative:** `POST /uploads/{upload_id}/tile/cancel` if your API strictly forbids DELETE for non-resource endpoints. Functionally equivalent; DELETE is preferred.

#### Endpoint Implementation

```python
# File: app/api/v1/endpoints/upload.py

@router.delete("/{upload_id}/tile", response_model=dict)
async def cancel_tiling(
    upload_id: str,
    repo: UploadSessionRepository = Depends(_get_repo),
):
    """
    Cancel an in-progress or queued tiling task.
    
    - If task is queued: revoke immediately, set status=cancelled
    - If task is executing: revoke (send SIGTERM), let worker catch signal
    - If task is done/failed/cancelled: idempotent, return 200 with explanation
    
    Returns:
        {
            "upload_id": "...",
            "message": "Tiling cancelled",
            "previous_status": "processing",
            "new_status": "cancelled",
            "celery_task_id": "...",  # for debugging
        }
    """
    session = await repo.get_by_id(upload_id)
    if not session:
        raise HTTPException(status_code=404, detail="Upload session not found")
    
    # Allowed transitions to cancelled
    allowed_from = {JobStatus.processing, JobStatus.pending}
    
    if session.status not in allowed_from:
        # Idempotent: if already cancelled, return 200
        if session.status == JobStatus.cancelled:
            return {
                "upload_id": upload_id,
                "message": "Task was already cancelled",
                "previous_status": session.status,
                "new_status": session.status,
                "celery_task_id": session.celery_task_id,
            }
        # Otherwise, reject (can't cancel from uploaded, done, failed, etc)
        raise HTTPException(
            status_code=409,
            detail=f"Cannot cancel task in status '{session.status}'. Must be 'processing' or 'pending'.",
        )
    
    # Revoke task from Celery
    previous_status = session.status
    task_id = session.celery_task_id
    
    if task_id:
        try:
            from app.workers.celery_app import celery_app
            celery_app.control.revoke(task_id, terminate=True, signal='SIGTERM')
            # terminate=True: If task is executing, send SIGTERM to worker process
            # signal='SIGTERM': Graceful termination (worker can catch and cleanup)
        except Exception as exc:
            # Log but don't fail — DB state update is more important than revoke
            print(f"[cancel] Failed to revoke task {task_id}: {exc}")
    
    # Update DB: status=cancelled, clear task_id, record cancel timestamp
    await repo.set_status(upload_id, JobStatus.cancelled)
    session = await repo.get_by_id(upload_id)
    if session:
        session.cancel_requested_at = datetime.now(timezone.utc)
        session.celery_task_id = None  # Clear task_id since task is no longer tracked
        await repo.session.commit()
    
    return {
        "upload_id": upload_id,
        "message": "Tiling cancelled",
        "previous_status": previous_status,
        "new_status": JobStatus.cancelled,
        "celery_task_id": task_id,
    }
```

### 3. Worker-Side Cancellation Handling

#### Update `process_tiling_task` to Store & Detect Cancellation

```python
# File: app/workers/tasks.py

@celery_app.task(bind=True, max_retries=3)
def process_tiling_task(
    self, 
    upload_id: str, 
    layer_id: str, 
    file_type: str, 
    source_path: str, 
    output_format: str = "raster", 
    max_zoom: int = None
):
    """
    Celery task for tiling. 
    
    Handles graceful cancellation via SIGTERM signal handler.
    """
    task_id = self.request.id  # Celery task ID
    
    # Store task ID in database IMMEDIATELY
    with db.get_session() as session:
        repo = SyncUploadSessionRepository(session)
        session_obj = repo.get_by_id(upload_id)
        if session_obj:
            session_obj.celery_task_id = task_id
            session.add(session_obj)
            session.commit()
        repo.set_status(upload_id, JobStatus.processing)
        print(f"[tiling] Task {task_id} queued for {upload_id}, status=processing")
    
    # Set up signal handler for graceful cancellation
    cancel_event = threading.Event()
    
    def handle_cancel_signal(signum, frame):
        print(f"[tiling] Received SIGTERM for task {task_id}, initiating graceful shutdown")
        cancel_event.set()
    
    original_handler = signal.signal(signal.SIGTERM, handle_cancel_signal)
    
    try:
        # [Existing placeholder layer creation code...]
        with db.get_session() as session:
            repo = SyncUploadSessionRepository(session)
            layer_repo = SyncLayerRepository(session)
            try:
                if not layer_repo.get_by_id(layer_id):
                    upload_session = repo.get_by_id(upload_id)
                    if upload_session:
                        placeholder = Layer(
                            id=layer_id,
                            upload_session_id=upload_id,
                            code=slugify(upload_session.filename),
                            filename=upload_session.filename,
                            file_type=file_type,
                            layer_type="tile",
                            tile_url_template="",
                            file_metadata={
                                "tile_process": {"percent": 0, "status": "processing"},
                                "source_file": {
                                    "filename": upload_session.filename,
                                    "upload_id": upload_id,
                                    "file_type": file_type,
                                    "uploaded_at": datetime.now().isoformat(),
                                }
                            },
                        )
                        layer_repo.create(placeholder)
                        print(f"[tiling] Created placeholder layer {layer_id}")
            except Exception as exc:
                print(f"[tiling] Failed to create placeholder layer {layer_id}: {exc}")
        
        # Setup progress callback with cancellation check
        def make_cancellable_progress_callback(layer_id: str):
            state = {"last": None}
            
            def callback(progress: dict) -> None:
                # Check if cancellation was signalled
                if cancel_event.is_set():
                    print(f"[tiling] Cancellation detected, raising CancelledError")
                    raise CancelledError("Task was cancelled by user")
                
                payload = {**progress, "status": "processing"}
                state["last"] = payload
                try:
                    with db.get_session() as session:
                        SyncLayerRepository(session).update_progress(layer_id, payload)
                        print(f"[progress] Updated {layer_id}: {payload.get('percent', 0)}%")
                except Exception as exc:
                    print(f"[progress] Failed to write progress for {layer_id}: {exc}")
            
            def finalize() -> None:
                last = state["last"]
                if last:
                    try:
                        with db.get_session() as session:
                            SyncLayerRepository(session).update_progress(
                                layer_id, {**last, "percent": 100, "status": "done"}
                            )
                    except Exception as exc:
                        print(f"[progress] Failed to finalize progress for {layer_id}: {exc}")
            
            return callback, finalize
        
        style = None
        with db.get_session() as session:
            layer_repo = SyncLayerRepository(session)
            existing = layer_repo.get_by_id(layer_id)
            if existing and existing.file_metadata:
                style = existing.file_metadata.get("style")
        
        progress_cb, finalize_progress = make_cancellable_progress_callback(layer_id)
        
        # Call TilingService with cancellation awareness
        bounds = TilingService.process_tiling(
            file_type, 
            Path(source_path), 
            layer_id, 
            output_format=output_format, 
            style=style, 
            progress_callback=progress_cb, 
            max_zoom=max_zoom,
            cancel_event=cancel_event  # NEW: pass cancellation event
        )
        finalize_progress()
        
        # [Existing success: Set status=done...]
        with db.get_session() as session:
            upload_repo = SyncUploadSessionRepository(session)
            upload_repo.set_status(upload_id, JobStatus.done)
            # ... rest of success path ...
    
    except CancelledError as exc:
        # User cancelled the task
        print(f"[tiling] Task {task_id} cancelled by user: {exc}")
        with db.get_session() as session:
            repo = SyncUploadSessionRepository(session)
            repo.set_status(upload_id, JobStatus.cancelled)
            session_obj = repo.get_by_id(upload_id)
            if session_obj:
                session_obj.celery_task_id = None
                session.add(session_obj)
                session.commit()
        
        # Trigger cleanup of partial tiles (see section 4 below)
        try:
            _cleanup_partial_tiles(layer_id)
        except Exception as cleanup_exc:
            print(f"[cleanup] Failed to cleanup partial tiles for {layer_id}: {cleanup_exc}")
        
        # Don't retry, just return (cancel is intentional)
        return
    
    except Exception as exc:
        # [Existing failure handling...]
        print(f"[tiling] Task {task_id} failed: {exc}")
        try:
            with db.get_session() as session:
                SyncLayerRepository(session).update_progress(
                    layer_id, {"percent": 0, "status": "failed"}
                )
        except Exception:
            pass
        
        with db.get_session() as session:
            repo = SyncUploadSessionRepository(session)
            repo.set_status(upload_id, JobStatus.failed, error_message=str(exc))
            session_obj = repo.get_by_id(upload_id)
            if session_obj:
                session_obj.celery_task_id = None
                session.add(session_obj)
                session.commit()
        
        raise self.retry(exc=exc, countdown=5)
    
    finally:
        # Restore original signal handler
        signal.signal(signal.SIGTERM, original_handler)
        # Clear task_id when done (regardless of outcome)
        if task_id:
            with db.get_session() as session:
                repo = SyncUploadSessionRepository(session)
                session_obj = repo.get_by_id(upload_id)
                if session_obj and session_obj.status in (JobStatus.done, JobStatus.failed):
                    session_obj.celery_task_id = None
                    session.add(session_obj)
                    session.commit()
```

**Key additions:**
- Store task ID immediately in DB
- Setup SIGTERM handler to gracefully catch cancellation signal
- Pass `cancel_event` to TilingService (allows mid-process detection)
- Clear task_id when task completes to maintain clean state
- Handle CancelledError separately (don't retry)

### 4. Storage Cleanup

#### Partial Tile Cleanup Function

```python
# File: app/infrastructure/services/tiling_service.py or new cleanup_service.py

from pathlib import Path
from app.core.config import settings

def _cleanup_partial_tiles(layer_id: str) -> None:
    """
    Delete partial/incomplete tile files for a cancelled tiling job.
    
    Called when task is cancelled during execution.
    Safe to call even if no tiles were generated (directory may not exist).
    """
    tiles_dir = Path(settings.TILES_DIR) / layer_id
    
    if not tiles_dir.exists():
        print(f"[cleanup] Tiles directory {tiles_dir} does not exist, skipping")
        return
    
    # Option A: Delete entire layer directory (cleaner, but unforgiving)
    try:
        shutil.rmtree(tiles_dir)
        print(f"[cleanup] Deleted partial tiles directory: {tiles_dir}")
    except Exception as exc:
        print(f"[cleanup] Failed to delete tiles directory {tiles_dir}: {exc}")
        # Continue — directory will be overwritten on retry anyway
    
    # Option B: Delete only incomplete zoom levels (more granular, but complex)
    # Not recommended for first iteration; Option A is safer

def cleanup_partial_tiles(layer_id: str) -> None:
    """Public wrapper for cleanup, suitable for calling from endpoints."""
    try:
        _cleanup_partial_tiles(layer_id)
    except Exception as exc:
        print(f"[cleanup] Exception during tile cleanup: {exc}")
        # Don't raise — cleanup failures shouldn't fail the cancellation
```

#### Should Cleanup be Automatic or Manual?

**Recommendation: Automatic on cancellation (worker-side)**

In `process_tiling_task` exception handler:
```python
except CancelledError as exc:
    # ... status update ...
    try:
        _cleanup_partial_tiles(layer_id)
    except Exception:
        pass  # Log but don't fail
```

**Rationale:**
- Worker has direct file system access
- Cleanup happens immediately while layer_id context is fresh
- No race condition: DB status is already `cancelled`, so no retry will pick up those tiles
- Optional manual cleanup endpoint can be added later if needed (for forensics, not normal flow)

---

## Response Design

### Cancel Request Response (DELETE /uploads/{upload_id}/tile)

```json
{
    "upload_id": "sess_1234567890",
    "message": "Tiling cancelled",
    "previous_status": "processing",
    "new_status": "cancelled",
    "celery_task_id": "abcd-1234-efgh-5678"
}
```

**HTTP Status:**
- `200 OK` — Cancellation accepted (task was queued or executing, now terminated)
- `200 OK` — Idempotent: task was already cancelled (return same response)
- `404 Not Found` — Upload session doesn't exist
- `409 Conflict` — Cannot cancel from current status (e.g., already done, uploaded, failed)

### Status Response (GET /uploads/{upload_id}/status) — No Changes Required

Response already includes `status: "cancelled"`. No schema changes needed.

```json
{
    "upload_id": "sess_1234567890",
    "layer_id": "layer_abc",
    "status": "cancelled",
    "received_bytes": 52428800,
    "total_size": 52428800,
    "uploaded_chunks": 100,
    "total_chunks": 100,
    "progress_percent": 100.0,
    "chunk_map": null,
    "error_message": null,
    "tile_url_template": null,
    "bbox": null
}
```

---

## Migration & Rollout

### Schema Migration (Alembic)

Create migration file: `alembic/versions/000X_add_celery_task_tracking.py`

```python
from alembic import op
import sqlalchemy as sa
from datetime import datetime

def upgrade() -> None:
    op.add_column(
        'upload_sessions',
        sa.Column('celery_task_id', sa.String(length=255), nullable=True, server_default=None),
        schema=None
    )
    op.add_column(
        'upload_sessions',
        sa.Column('cancel_requested_at', sa.DateTime(timezone=True), nullable=True, server_default=None),
        schema=None
    )
    # Add index on celery_task_id for faster lookups (optional but recommended)
    op.create_index('ix_upload_sessions_celery_task_id', 'upload_sessions', ['celery_task_id'], unique=False)

def downgrade() -> None:
    op.drop_index('ix_upload_sessions_celery_task_id', table_name='upload_sessions')
    op.drop_column('upload_sessions', 'cancel_requested_at')
    op.drop_column('upload_sessions', 'celery_task_id')
```

### Deployment Steps

1. **Branch 1 (Backward compatible):**
   - Add new columns to schema (nullable defaults to NULL)
   - Run migration on production DB (no downtime, non-blocking)
   - Deploy FastAPI + Worker code with new fields (code is forward-compatible with NULL values)

2. **Branch 2 (Feature release, one week later):**
   - Update `process_tiling_task` to populate `celery_task_id` (already backward-compatible)
   - Add cancel endpoint

3. **No Branch 3 needed** — Feature is live after step 2

---

## Failure Modes & Mitigation

| Scenario | What Happens | Mitigation |
|----------|--------------|-----------|
| **User calls cancel, but task already done** | Endpoint returns 409 Conflict or 200 (idempotent). DB state is `done`, not `processing`. | Idempotent behavior: check `allowed_from` list; if not in allowed status, reject or return "already done" |
| **SIGTERM sent but worker ignores it** | Task continues to completion. DB is updated to `cancelled`, but tiles still exist. | On next retry attempt, check DB status before processing. Prevent re-entry if status is `cancelled`. |
| **Worker dies after revoke but before DB update** | Celery loses task, DB shows `processing`. User re-submits; task re-runs on different worker. | Include idempotency key or phase in task execution: always check DB status before starting work. |
| **Network error during revoke call** | Celery.control.revoke() fails. Task still runs. | Don't fail the response; prioritize DB state update. DB state (`cancelled`) is source of truth. Task will eventually complete or timeout. |
| **Partial tiles exist, cleanup fails** | Tiles directory lingers. Next retry overwrites them (safe). | Cleanup failures don't propagate; log and continue. Optional: cron job to detect orphaned directories. |
| **User cancels, then immediately retries** | Endpoint rejects retry because status is `cancelled`. | Document: user must reset status via `/retry` endpoint or dashboard to try again. |

---

## Alternative Approaches & Why Not

### Option B: Database-Only Cancellation (No Celery Revoke)

**Approach:** Just update DB status to `cancelled`; don't call `celery_app.control.revoke()`. Worker checks DB status at progress points.

**Pros:**
- Simpler (no signal handling in worker)
- No dependency on Celery control API

**Cons:**
- ❌ Task stays in RabbitMQ queue until consumed (wastes resources)
- ❌ If task is already executing, it continues to completion (defeats purpose)
- ❌ Partial tiles still generated (cleanup manual only)
- ❌ Adds latency: worker doesn't detect cancellation until next progress callback (could be 10+ min for large rasters)

**Verdict:** Not recommended. Option A is better.

### Option C: Job Queue with Cancel Support (e.g., RQ instead of Celery)

**Approach:** Replace Celery/RabbitMQ with Redis Queue (RQ), which has native job cancellation.

**Pros:**
- Native cancel support
- Simpler signal handling
- No broker complexity

**Cons:**
- ❌ Requires major refactor (Celery is already wired throughout)
- ❌ Loses Celery features (retries, task routing, monitoring)
- ❌ RQ is less battle-tested for high-volume production
- ❌ Timeline: weeks of work

**Verdict:** Not feasible for current sprint. Option A is pragmatic.

### Option D: Revert Status to `uploaded` Instead of `cancelled`

**Approach:** Cancel task, revert status to `uploaded` (pre-processing state).

**Pros:**
- User can immediately retry from familiar state

**Cons:**
- ❌ Hides intent: did upload really fail, or was it cancelled?
- ❌ Progress metadata lost (can't show "was 67% done when cancelled")
- ❌ No audit trail of cancellation action
- ❌ Partial Layer record in DB is now inconsistent (status=uploaded but layer_id is half-initialized)
- ❌ Violates Clean Architecture: mixing failure semantics

**Verdict:** Not recommended. `cancelled` is semantically clearer.

---

## Testing Strategy

### Unit Tests

1. **Test cancel endpoint with valid transitions**
   ```python
   # status=processing → status=cancelled, task_id cleared
   # Verify response shape and HTTP codes
   ```

2. **Test cancel endpoint with invalid transitions**
   ```python
   # status=uploaded → 409
   # status=done → 409
   # status=cancelled → 200 (idempotent)
   ```

3. **Test worker-side cancellation handling**
   ```python
   # Simulate SIGTERM signal → CancelledError caught → status=cancelled, cleanup called
   ```

4. **Test cleanup function**
   ```python
   # Create partial tiles directory → cleanup() → directory deleted
   # No directory → cleanup() → no error
   ```

### Integration Tests

1. **Queue tiling task, cancel while queued**
   ```python
   # POST /uploads/{id}/tile → processing
   # DELETE /uploads/{id}/tile → cancelled
   # Verify task never executes (worker logs show revoke)
   ```

2. **Queue tiling task, cancel while executing (race condition)**
   ```python
   # Use mock TilingService with controllable progress
   # POST /tile → executing
   # DELETE /tile (mid-execution) → SIGTERM sent → eventually cancelled
   # Verify partial tiles cleaned up
   ```

3. **Cancel non-existent task (404)**
   ```python
   # DELETE /uploads/invalid_id/tile → 404
   ```

### Manual Testing

1. Small file (< 10MB) → cancel during tiling
2. Large file (chunked) → cancel during tiling
3. Tiling that takes 30+ seconds → cancel → verify tiles don't exist
4. Cancel after tiling completes (should be 409 or idempotent 200)

---

## Monitoring & Observability

### Metrics to Track

1. **Cancellation rate:** `{service}_tiling_cancellations_total` (gauge)
2. **Time to revoke:** `{service}_task_revoke_duration_seconds` (histogram)
3. **Cleanup failures:** `{service}_cleanup_failures_total` (counter)

### Logs to Emit

```
[tiling] Task {task_id} queued for {upload_id}
[cancel] Revoke requested for task {task_id}
[cancel] Task {task_id} already in status '{status}', cannot cancel
[cleanup] Deleted partial tiles: {tiles_dir}
[cleanup] Cleanup failed for {layer_id}: {error}
```

### Alerts

- If `{service}_cleanup_failures_total` > 5 in 1 hour → investigate orphaned tile directories

---

## Summary: Implementation Checklist

| Task | File(s) | Priority |
|------|---------|----------|
| Add `celery_task_id`, `cancel_requested_at` to `UploadSession` | `app/domain/models.py` | Critical |
| Create Alembic migration | `alembic/versions/000X_...py` | Critical |
| Update `process_tiling_task` to store task ID + handle SIGTERM | `app/workers/tasks.py` | Critical |
| Add cancel endpoint (DELETE /uploads/{id}/tile) | `app/api/v1/endpoints/upload.py` | Critical |
| Add cleanup function | `app/infrastructure/services/tiling_service.py` | High |
| Update repository to support task_id operations | `app/infrastructure/db/repository.py` | High |
| Add new exception class for cancellation | `app/core/exceptions.py` | Medium |
| Update TilingService.process_tiling() to accept cancel_event | `app/infrastructure/services/tiling_service.py` | High |
| Write integration tests | `tests/test_cancel_tiling.py` | Medium |
| Update CLAUDE.md with cancel workflow docs | `CLAUDE.md` | Low |

---

## Rationale Summary

**Why DELETE instead of POST?**
- REST semantics: DELETE removes a resource (the running task)
- Clearer intent
- Idempotent operation

**Why new status `cancelled` instead of revert to `uploaded`?**
- Audit trail: preserves intent
- Prevents confusion with actual failures
- Enables proper state machine (cannot retry without explicit reset)

**Why Celery revoke + DB update instead of DB-only?**
- Revoke stops task immediately if queued
- DB update ensures state consistency if revoke fails
- Dual approach is resilient to network/broker failures

**Why clean up partial tiles?**
- Prevents garbage accumulation
- Makes retry predictable (clean slate)
- Frees disk space
- Worker has direct file access (safe to cleanup)

**Why store task_id in DB?**
- Enables reliable revocation across worker restarts
- Survives worker crashes (database is source of truth)
- Supports audit logging and forensics
- Minimal schema overhead (one string column)

