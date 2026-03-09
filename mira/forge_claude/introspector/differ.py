"""Schema diff engine — compare two manifests and produce change report.

When re-running FORGE against an evolved database, the differ compares
the new manifest against the previous one and produces:
  (a) Human-readable change report
  (b) Alembic migration stubs (text, not actual Alembic code)
  (c) Impact assessment for downstream artifacts

Diff categories: table_added, table_removed, column_added, column_removed,
column_type_changed, index_added, foreign_key_added, row_count_changed.

Spec reference: Section 3.7
"""

from __future__ import annotations

from mira.forge_claude.introspector.manifest import SchemaManifest, SchemaDiff


def diff_manifests(
    old: SchemaManifest,
    new: SchemaManifest,
) -> SchemaDiff:
    """Compare two schema manifests and produce a diff.

    Args:
        old: The previous schema manifest.
        new: The current schema manifest.

    Returns:
        SchemaDiff with all detected changes.
    """
    old_tables = {t.name: t for t in old.tables}
    new_tables = {t.name: t for t in new.tables}

    tables_added = [name for name in new_tables if name not in old_tables]
    tables_removed = [name for name in old_tables if name not in new_tables]

    columns_added = []
    columns_removed = []
    columns_type_changed = []
    indexes_added = []
    foreign_keys_added = []
    row_count_changes = []

    # Compare tables that exist in both
    for name in old_tables:
        if name not in new_tables:
            continue

        old_t = old_tables[name]
        new_t = new_tables[name]

        old_cols = {c.name: c for c in old_t.columns}
        new_cols = {c.name: c for c in new_t.columns}

        # Column additions
        for col_name in new_cols:
            if col_name not in old_cols:
                columns_added.append({
                    "table": name,
                    "column": col_name,
                    "type": new_cols[col_name].type,
                })

        # Column removals
        for col_name in old_cols:
            if col_name not in new_cols:
                columns_removed.append({
                    "table": name,
                    "column": col_name,
                    "type": old_cols[col_name].type,
                })

        # Type changes
        for col_name in old_cols:
            if col_name in new_cols:
                if old_cols[col_name].type != new_cols[col_name].type:
                    columns_type_changed.append({
                        "table": name,
                        "column": col_name,
                        "old_type": old_cols[col_name].type,
                        "new_type": new_cols[col_name].type,
                    })

        # Index additions
        old_idxs = set(old_t.indexes)
        new_idxs = set(new_t.indexes)
        for idx in new_idxs - old_idxs:
            indexes_added.append({"table": name, "index": idx})

        # FK additions
        old_fks = {(fk.column, fk.references_table, fk.references_column) for fk in old_t.foreign_keys}
        new_fks = {(fk.column, fk.references_table, fk.references_column) for fk in new_t.foreign_keys}
        for fk in new_fks - old_fks:
            foreign_keys_added.append({
                "table": name,
                "column": fk[0],
                "references_table": fk[1],
                "references_column": fk[2],
            })

        # Row count changes
        if old_t.row_count != new_t.row_count:
            row_count_changes.append({
                "table": name,
                "old_count": old_t.row_count,
                "new_count": new_t.row_count,
                "delta": new_t.row_count - old_t.row_count,
            })

    has_breaking = bool(tables_removed or columns_removed or columns_type_changed)

    return SchemaDiff(
        database_name=new.database_name,
        tables_added=tables_added,
        tables_removed=tables_removed,
        columns_added=columns_added,
        columns_removed=columns_removed,
        columns_type_changed=columns_type_changed,
        indexes_added=indexes_added,
        foreign_keys_added=foreign_keys_added,
        row_count_changes=row_count_changes,
        has_breaking_changes=has_breaking,
    )


def generate_migration_stubs(diff: SchemaDiff) -> str:
    """Generate Alembic-style migration stubs from a schema diff.

    Returns Python code as a string (not actual runnable migrations,
    but structured stubs for a developer to refine).
    """
    lines = [
        '"""Auto-generated migration stub from FORGE schema diff."""',
        "",
        "from alembic import op",
        "import sqlalchemy as sa",
        "",
        "",
        "def upgrade():",
    ]

    has_ops = False

    for table in diff.tables_added:
        has_ops = True
        lines.append(f"    # TODO: Define columns for new table '{table}'")
        lines.append(f"    op.create_table('{table}',")
        lines.append(f"        sa.Column('id', sa.Integer(), primary_key=True),")
        lines.append(f"        # Add columns here")
        lines.append(f"    )")
        lines.append("")

    for table in diff.tables_removed:
        has_ops = True
        lines.append(f"    op.drop_table('{table}')")
        lines.append("")

    for col in diff.columns_added:
        has_ops = True
        lines.append(
            f"    op.add_column('{col['table']}', "
            f"sa.Column('{col['column']}', sa.String()))"
            f"  # TODO: Set correct type"
        )

    for col in diff.columns_removed:
        has_ops = True
        lines.append(
            f"    op.drop_column('{col['table']}', '{col['column']}')"
        )

    for col in diff.columns_type_changed:
        has_ops = True
        lines.append(
            f"    # Type change: {col['table']}.{col['column']} "
            f"from {col['old_type']} to {col['new_type']}"
        )
        lines.append(
            f"    op.alter_column('{col['table']}', '{col['column']}', "
            f"type_=sa.String())  # TODO: Set correct type"
        )

    if not has_ops:
        lines.append("    pass  # No schema changes detected")

    lines.append("")
    lines.append("")
    lines.append("def downgrade():")
    lines.append("    pass  # TODO: Implement downgrade")
    lines.append("")

    return "\n".join(lines)


def format_change_report(diff: SchemaDiff) -> str:
    """Format a human-readable change report."""
    lines = [f"Schema Diff Report: {diff.database_name}", "=" * 50, ""]

    if not any([
        diff.tables_added, diff.tables_removed, diff.columns_added,
        diff.columns_removed, diff.columns_type_changed,
        diff.indexes_added, diff.foreign_keys_added, diff.row_count_changes,
    ]):
        lines.append("No changes detected.")
        return "\n".join(lines)

    if diff.has_breaking_changes:
        lines.append("WARNING: Breaking changes detected!")
        lines.append("")

    if diff.tables_added:
        lines.append(f"Tables Added ({len(diff.tables_added)}):")
        for t in diff.tables_added:
            lines.append(f"  + {t}")
        lines.append("")

    if diff.tables_removed:
        lines.append(f"Tables Removed ({len(diff.tables_removed)}):")
        for t in diff.tables_removed:
            lines.append(f"  - {t}")
        lines.append("")

    if diff.columns_added:
        lines.append(f"Columns Added ({len(diff.columns_added)}):")
        for c in diff.columns_added:
            lines.append(f"  + {c['table']}.{c['column']} ({c['type']})")
        lines.append("")

    if diff.columns_removed:
        lines.append(f"Columns Removed ({len(diff.columns_removed)}):")
        for c in diff.columns_removed:
            lines.append(f"  - {c['table']}.{c['column']} ({c['type']})")
        lines.append("")

    if diff.columns_type_changed:
        lines.append(f"Type Changes ({len(diff.columns_type_changed)}):")
        for c in diff.columns_type_changed:
            lines.append(
                f"  ~ {c['table']}.{c['column']}: "
                f"{c['old_type']} -> {c['new_type']}"
            )
        lines.append("")

    if diff.row_count_changes:
        lines.append(f"Row Count Changes ({len(diff.row_count_changes)}):")
        for r in diff.row_count_changes:
            delta = r["delta"]
            sign = "+" if delta > 0 else ""
            lines.append(
                f"  {r['table']}: {r['old_count']} -> {r['new_count']} ({sign}{delta})"
            )
        lines.append("")

    return "\n".join(lines)
