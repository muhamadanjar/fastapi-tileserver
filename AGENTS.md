# Database schema and migrations

- Make every database-field addition or change in the SQLModel model first.
- After updating the SQLModel model, generate an Alembic migration from that model change. Do not write Alembic migrations manually.
- Manual migrations are allowed only when strictly necessary, such as resolving a migration conflict with the existing database.
- Manually editing or creating a migration revision is also allowed when unavoidable to repair migration ordering, revision naming, or other migration metadata that Alembic cannot resolve safely.
- Keep the migration history clean, ordered, and free from overlapping changes.
