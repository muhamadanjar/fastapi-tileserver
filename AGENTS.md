# Database schema and migrations

- Make every database-field addition or change in the SQLModel model first.
- After updating the SQLModel model, generate an Alembic migration from that model change. Do not write Alembic migrations manually.
- Manual migrations are allowed only when strictly necessary, such as resolving a migration conflict with the existing database.
- Keep the migration history clean, ordered, and free from overlapping changes.
