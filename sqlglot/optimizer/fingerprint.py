from __future__ import annotations

import typing as t

from sqlglot import exp
from sqlglot.dialects.dialect import DialectType
from sqlglot.helper import name_sequence
from sqlglot.optimizer.qualify import qualify
from sqlglot.optimizer.scope import Scope, find_all_in_scope, traverse_scope
from sqlglot.schema import Schema

if t.TYPE_CHECKING:
    from sqlglot._typing import E


def fingerprint(
    expression: E,
    dialect: DialectType = None,
    schema: dict[str, object] | Schema | None = None,
    **qualify_kwargs: t.Any,
) -> E:
    """
    Canonicalize a query to a structural fingerprint.

    Preserves data-contract names (base-table names and columns, top-level output
    aliases) and canonicalizes internal names (table aliases, CTE/subquery names,
    internal column aliases) to sequential `_tN` / `_cN`. For set operations the
    top-level output is the leftmost leaf SELECT.

    Example:
        >>> import sqlglot
        >>> schema = {"src": {"c1": "INT", "c2": "INT"}}
        >>> fingerprint(sqlglot.parse_one("WITH t AS (SELECT c1, c2 FROM c.db.src) SELECT * FROM t"), schema=schema).sql()
        'WITH "_t1" AS (SELECT "_t0"."c1" AS "c1", "_t0"."c2" AS "c2" FROM "c"."db"."src" AS "_t0") SELECT "_t1"."c1" AS "c1", "_t1"."c2" AS "c2" FROM "_t1" AS "_t1"'
    """
    expression = t.cast("E", qualify(expression, dialect=dialect, schema=schema, **qualify_kwargs))

    # Top-level output scope: its aliases are the query's data contract
    output_scope_expr: exp.Expr = expression
    while isinstance(output_scope_expr, exp.SetOperation):
        output_scope_expr = output_scope_expr.left.unnest()

    next_table = name_sequence("_t")
    next_column = name_sequence("_c")

    def _canon(ident: exp.Identifier, name: str) -> None:
        ident.set("this", name)
        ident.set("quoted", True)

    scope_table: dict[int, str] = {}
    scope_outputs: dict[int, dict[str, str]] = {}

    # Shared across scopes so a Table referenced from multiple scopes (LATERAL/UNNEST) gets consistent column names
    table_columns: dict[int, dict[str, str]] = {}

    for scope in traverse_scope(expression):
        scope_expr = scope.expression
        is_output_scope = scope_expr is output_scope_expr

        columns_by_source: dict[str, list[exp.Column]] = {}
        for col in scope.columns:
            columns_by_source.setdefault(col.table, []).append(col)

        table_map: dict[str, str] = {}

        for source_name, source in scope.sources.items():
            source_cols = columns_by_source.get(source_name)
            if not source_cols:
                continue

            alias_holder: exp.Expr | None = None
            is_base_source = isinstance(source, exp.Table)

            if is_base_source:
                canon_t = scope_table.get(id(source), "")
                if not canon_t:
                    canon_t = next_table()
                    scope_table[id(source)] = canon_t
                child_output: dict[str, str] = {}
                name_map: dict[str, str] = table_columns.setdefault(id(source), {})
            elif isinstance(source, Scope):
                # Key by id(expression) so a recursive CTE's self-reference, i.e., a separate
                # Scope whose `expression` is the same object as the CTE's base branch, shares
                # the base branch's output mapping.
                src_expr = source.expression
                child_output = scope_outputs.get(id(src_expr), {})

                parent = src_expr.parent
                if isinstance(parent, (exp.CTE, exp.Subquery)):
                    alias_holder = parent
                elif (
                    isinstance(parent, exp.SetOperation)
                    and isinstance(cte := parent.parent, exp.CTE)
                    and isinstance(with_ := cte.parent, exp.With)
                    and with_.recursive
                ):
                    alias_holder = cte
                elif source.is_udtf:
                    alias_holder = src_expr

                table_key = id(alias_holder) if alias_holder else id(source)
                canon_t = scope_table.get(table_key, "")

                if not canon_t:
                    canon_t = next_table()
                    scope_table[table_key] = canon_t
                else:
                    alias_holder = None  # already renamed on a previous encounter

                name_map = {}
            else:
                continue

            table_map[source_name] = canon_t

            for col in source_cols:
                old_name = col.name
                canon_col = name_map.get(old_name)

                if canon_col is None:
                    if is_base_source:
                        canon_col = old_name
                    else:
                        canon_col = child_output.get(old_name) or next_column()

                    name_map[old_name] = canon_col

                # Base-table column refs are part of the data contract => preserve verbatim (including quote state).
                # Scope-sourced column refs are internal handles pointing at CTE/subquery aliases (injected unquoted
                # via exp.to_identifier); they must match, so _canon
                if not is_base_source:
                    _canon(col.this, canon_col)

                table_id = col.args.get("table")
                if table_id:
                    _canon(table_id, canon_t)

            if alias_holder:
                if alias := alias_holder.args.get("alias"):
                    if isinstance(alias.this, exp.Identifier):
                        _canon(alias.this, canon_t)
                    if alias.columns:
                        alias.set(
                            "columns",
                            [
                                exp.to_identifier(name_map.get(c.name, c.name), quoted=c.quoted)
                                for c in alias.columns
                            ],
                        )

                # BigQuery UNNEST ... WITH OFFSET AS <id> declares a pseudo-column via
                # the offset arg (not the alias).
                if isinstance(alias_holder, exp.Unnest):
                    offset_id = alias_holder.args.get("offset")
                    if isinstance(offset_id, exp.Identifier) and offset_id.name in name_map:
                        _canon(offset_id, name_map[offset_id.name])

        # PIVOT output column names are bound to the IN-clause literals, so only the
        # alias (which qualifies column refs like `my_pivot.x`) is canonicalized.
        for pivot in scope.pivots:
            pivot_alias = pivot.args.get("alias")
            if not (pivot_alias and isinstance(pivot_alias.this, exp.Identifier)):
                continue
            pivot_cols = columns_by_source.get(pivot_alias.this.name)
            if not pivot_cols:
                continue

            canon_t = next_table()
            _canon(pivot_alias.this, canon_t)

            for col in pivot_cols:
                table_id = col.args.get("table")
                if table_id:
                    _canon(table_id, canon_t)

        for table in scope.tables:
            canon = table_map.get(table.alias_or_name)
            if not canon:
                continue

            # Real tables (qualified with db/catalog) keep their physical name;
            # CTE/subquery references get the canonical `_tN`.
            if isinstance(table.this, exp.Identifier) and not table.args.get("db"):
                _canon(table.this, canon)

            alias = table.args.get("alias")
            if alias:
                if isinstance(alias.this, exp.Identifier):
                    _canon(alias.this, canon)
                if alias.columns:
                    tc = table_columns.get(id(table), {})
                    alias.set(
                        "columns",
                        [
                            exp.to_identifier(tc.get(c.name, c.name), quoted=c.quoted)
                            for c in alias.columns
                        ],
                    )

        output_map: dict[str, str] = {}
        if isinstance(scope_expr, exp.Select):
            for sel in scope_expr.selects:
                if isinstance(sel, exp.Alias):
                    old_alias = sel.alias
                    inner = sel.this
                    if is_output_scope:
                        new_name = old_alias
                    elif isinstance(inner, exp.Column):
                        new_name = inner.name
                        sel.set("alias", exp.to_identifier(new_name, quoted=inner.this.quoted))
                    else:
                        new_name = next_column()
                        sel.set("alias", exp.to_identifier(new_name, quoted=True))

                    output_map[old_alias] = new_name
        elif isinstance(scope_expr, exp.SetOperation) and scope.union_scopes:
            output_map = scope_outputs.get(id(scope.union_scopes[0].expression), {}).copy()

        scope_outputs[id(scope_expr)] = output_map

        # Unqualified alias references (ORDER BY a, HAVING a > 5, ...)
        for col in find_all_in_scope(scope_expr, exp.Column):
            if not col.table and col.name in output_map:
                _canon(col.this, output_map[col.name])

        # UNION BY NAME matches columns across branches by original alias, so canonical
        # names must align — otherwise `... UNION BY NAME SELECT a ...` and
        # `... UNION BY NAME SELECT b ...` fingerprint identically despite reading
        # different columns from the right side.
        if isinstance(scope_expr, exp.SetOperation) and scope_expr.args.get("by_name"):
            left_scope, right_scope = scope.union_scopes
            left_out = scope_outputs.get(id(left_scope.expression), {})
            right_out = scope_outputs.get(id(right_scope.expression), {})

            rename: dict[str, str] = {}
            for orig_name, left_canon in left_out.items():
                right_canon = right_out.get(orig_name)
                if right_canon and right_canon != left_canon:
                    rename[right_canon] = left_canon

            if rename:

                def _apply_rename(node: exp.Expr) -> None:
                    if isinstance(node, exp.SetOperation):
                        _apply_rename(node.left)
                        _apply_rename(node.right)
                        return
                    if isinstance(node, exp.Select):
                        for sel in node.selects:
                            if isinstance(sel, exp.Alias):
                                aid = sel.args.get("alias")
                                if isinstance(aid, exp.Identifier) and aid.name in rename:
                                    _canon(aid, rename[aid.name])
                        for col in find_all_in_scope(node, exp.Column):
                            if not col.table and col.name in rename:
                                _canon(col.this, rename[col.name])

                _apply_rename(right_scope.expression)

                scope_outputs[id(right_scope.expression)] = {
                    k: rename.get(v, v) for k, v in right_out.items()
                }

    return expression
