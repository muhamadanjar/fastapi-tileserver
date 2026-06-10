"""Post-write hook to rename migration files with sequential numbering."""
import os
import re
import sys


def rename_migration(filepath):
    """Rename migration file and update revision ID inside."""
    versions_dir = os.path.dirname(filepath)
    filename = os.path.basename(filepath)

    # Extract slug from current filename (e.g., "f7a7da334e60_test_sequential.py" -> "test_sequential")
    match = re.match(r"^[a-f0-9]+_(.+)\.py$", filename)
    if not match:
        # Already using sequential naming, skip
        return

    slug = match.group(1)

    # Find highest existing sequential number
    # Only look for files matching pattern: NNNN_slug.py (numbered) or hash_slug.py (to be renamed)
    existing_files = [f for f in os.listdir(versions_dir) if f.endswith(".py") and not f.startswith("__")]
    numbers = []
    for f in existing_files:
        # Match both sequential (0001_...) and hash-based (abc123_...) patterns
        # Only extract number if it's all digits (sequential) not hex hash
        m = re.match(r"^(\d+)_", f)
        if m:
            numbers.append(int(m.group(1)))

    next_num = (max(numbers) if numbers else 0) + 1
    new_revision_id = f"{next_num:04d}"
    new_filename = f"{new_revision_id}_{slug}.py"
    new_filepath = os.path.join(versions_dir, new_filename)

    # Read file
    with open(filepath, 'r') as f:
        content = f.read()

    # Extract current revision ID from file
    rev_match = re.search(r"revision:\s*str\s*=\s*['\"]([^'\"]+)['\"]", content)
    if not rev_match:
        return

    old_revision_id = rev_match.group(1)

    # Replace old revision ID with new sequential one
    content = re.sub(
        rf"(revision:\s*str\s*=\s*['\"]){old_revision_id}(['\"])",
        rf"\g<1>{new_revision_id}\g<2>",
        content
    )

    # Also update Revision ID comment if present
    content = re.sub(
        rf"(Revision ID:\s*){old_revision_id}(\s*\n)",
        rf"\g<1>{new_revision_id}\g<2>",
        content
    )

    # Write to new filename
    with open(new_filepath, 'w') as f:
        f.write(content)

    # Keep the original file path too for Alembic to find (it expects original path after hook)
    with open(filepath, 'w') as f:
        f.write(content)

    print(f"Renamed: {filename} -> {new_filename}")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        rename_migration(sys.argv[1])
