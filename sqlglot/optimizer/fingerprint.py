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
    Canonicalize a query by replacing all identifiers with anonymous sequential names,
    producing a structural "fingerprint" useful for comparing query shapes, hashing, etc.

    The algorithm works bottom-up: leaf scopes (those referencing real tables) are processed
    first, assigning canonical column names as columns are encountered. These names propagate
    upward through CTEs and subqueries via each scope's SELECT output mapping.

    Example:
        >>> import sqlglot
        >>> schema = {"src": {"c1": "INT", "c2": "INT"}}
        >>> fingerprint(sqlglot.parse_one("WITH t AS (SELECT c1, c2 FROM src) SELECT * FROM t"), schema=schema).sql()
        'WITH _t1 AS (SELECT _t0._c0 AS _c0, _t0._c1 AS _c1 FROM _t0 AS _t0) SELECT _t1._c0 AS _c0, _t1._c1 AS _c1 FROM _t1 AS _t1'

    Args:
        expression: The expression to fingerprint.
        dialect: The SQL dialect.
        schema: Schema information needed for column qualification.
        **qualify_kwargs: Additional keyword arguments passed to qualify().

    Returns:
        A deep copy of the expression with all identifiers replaced by canonical names.
    """
    expression = t.cast(
        "E",
        qualify(
            expression.copy(),
            dialect=dialect,
            schema=schema,
            quote_identifiers=False,
            **qualify_kwargs,
        ),
    )

    next_table = name_sequence("_t")
    next_column = name_sequence("_c")

    # id(Scope) -> canonical table name assigned to this scope when referenced as a source
    scope_table: dict[int, str] = {}

    # id(Scope) -> {old_output_col_name: canonical_col_name} from this scope's SELECT list
    scope_outputs: dict[int, dict[str, str]] = {}

    for scope in traverse_scope(expression):
        col_map: dict[tuple[str, str], str] = {}  # (source_alias, col_name) -> canonical
        table_map: dict[str, str] = {}  # source_alias -> canonical table name

        for source_name, source in scope.sources.items():
            source_cols = scope.source_columns(source_name)
            if not source_cols:
                continue

            if isinstance(source, exp.Table):
                table_map[source_name] = next_table()
                for col in source_cols:
                    key = (source_name, col.name)
                    if key not in col_map:
                        col_map[key] = next_column()
            elif isinstance(source, Scope):
                child_output = scope_outputs.get(id(source), {})

                if id(source) in scope_table:
                    canon_t = scope_table[id(source)]
                else:
                    canon_t = next_table()
                    scope_table[id(source)] = canon_t

                    # Rename the container alias (CTE definition or Subquery)
                    container = source.expression.parent
                    if isinstance(container, (exp.CTE, exp.Subquery)):
                        alias = container.args.get("alias")
                        if alias and isinstance(alias.this, exp.Identifier):
                            alias.this.set("this", canon_t)

                table_map[source_name] = canon_t

                for col in source_cols:
                    key = (source_name, col.name)
                    if key not in col_map:
                        col_map[key] = child_output.get(col.name, next_column())

        # Rewrite column references in this scope
        for col in scope.columns:
            canon_col = col_map.get((col.table, col.name))
            if canon_col:
                col.this.set("this", canon_col)

            canon_table = table_map.get(col.table)
            if canon_table and col.args.get("table"):
                col.args["table"].set("this", canon_table)

        # Rewrite Table nodes (real tables and CTE/subquery references in FROM)
        for table in scope.tables:
            canon = table_map.get(table.alias_or_name)
            if not canon:
                continue

            # Only rename the table name for CTE/subquery references (no db/catalog).
            # For real tables, keep the physical reference intact — only the alias changes.
            if isinstance(table.this, exp.Identifier) and not table.args.get("db"):
                table.this.set("this", canon)

            alias = table.args.get("alias")
            if alias and isinstance(alias.this, exp.Identifier):
                alias.this.set("this", canon)

        # Rewrite SELECT aliases and build the output mapping for parent scopes
        output_map: dict[str, str] = {}
        if isinstance(scope.expression, exp.Select):
            for sel in scope.expression.selects:
                if isinstance(sel, exp.Alias):
                    old_alias = sel.alias
                    inner = sel.this
                    new_name = inner.name if isinstance(inner, exp.Column) else next_column()
                    output_map[old_alias] = new_name
                    sel.set("alias", exp.to_identifier(new_name))

        scope_outputs[id(scope)] = output_map

        # Rewrite unqualified alias references (e.g., ORDER BY a, HAVING a > 5 referencing a SELECT alias)
        for col in find_all_in_scope(scope.expression, exp.Column):
            if not col.table and col.name in output_map:
                col.this.set("this", output_map[col.name])

    return expression
