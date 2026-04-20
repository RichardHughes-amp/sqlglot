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
        The expression with all identifiers replaced by canonical names.
    """
    expression = t.cast(
        "E",
        qualify(
            expression,
            dialect=dialect,
            schema=schema,
            quote_identifiers=False,
            **qualify_kwargs,
        ),
    )

    next_table = name_sequence("_t")
    next_column = name_sequence("_c")

    def _canon(ident: exp.Identifier, name: str) -> None:
        # Canonical names are always safe bare identifiers, so strip any inherited
        # quoted=True flag — otherwise quoted source identifiers stay quoted in the
        # output, causing semantically equivalent queries to produce different
        # fingerprints (and in case-sensitive dialects like Snowflake, "_c0" and
        # _c0 are genuinely different identifiers).
        ident.set("this", name)
        ident.set("quoted", False)

    # id(Scope) -> canonical table name assigned to this scope when referenced as a source
    scope_table: dict[int, str] = {}

    # id(Scope) -> {old_output_col_name: canonical_col_name} from this scope's SELECT list
    scope_outputs: dict[int, dict[str, str]] = {}

    # id(Table) -> {col_name: canonical}. Shared across scopes so the same Table node
    # referenced from multiple scopes (e.g. LATERAL/UNNEST) keeps consistent column names.
    table_columns: dict[int, dict[str, str]] = {}

    for scope in traverse_scope(expression):
        # Group columns by source alias in a single pass; external columns (referencing outer
        # scopes) fall into entries whose key isn't in scope.sources and are skipped here —
        # they'll be rewritten when their defining scope is processed.
        columns_by_source: dict[str, list[exp.Column]] = {}
        for col in scope.columns:
            columns_by_source.setdefault(col.table, []).append(col)

        table_map: dict[str, str] = {}  # source_alias -> canonical table name

        for source_name, source in scope.sources.items():
            source_cols = columns_by_source.get(source_name)
            if not source_cols:
                continue

            alias_holder: exp.Expr | None = None

            if isinstance(source, exp.Table):
                # A Table AST node can appear as a source in multiple scopes (e.g. when
                # referenced inside a CROSS JOIN UNNEST). Track by id so we reuse the same
                # canonical name and column mapping instead of allocating fresh ones.
                canon_t = scope_table.get(id(source), "")
                if not canon_t:
                    canon_t = next_table()
                    scope_table[id(source)] = canon_t
                child_output: dict[str, str] = {}
                name_map: dict[str, str] = table_columns.setdefault(id(source), {})
            elif isinstance(source, Scope):
                # Key scope_outputs by id(expression) so recursive-CTE phantoms (whose
                # expression IS the seed branch's SELECT) share output naming with the seed.
                src_expr = source.expression
                child_output = scope_outputs.get(id(src_expr), {})

                # Key scope_table by the enclosing container's id so phantoms and the main
                # CTE scope resolve to the same canonical name.
                parent = src_expr.parent
                if isinstance(parent, (exp.CTE, exp.Subquery)):
                    alias_holder = parent
                elif isinstance(parent, exp.SetOperation) and isinstance(parent.parent, exp.CTE):
                    alias_holder = parent.parent  # recursive-CTE phantom
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

            # Assign canonical column names and rewrite references in a single pass
            for col in source_cols:
                old_name = col.name
                canon_col = name_map.get(old_name)
                if canon_col is None:
                    canon_col = child_output.get(old_name) or next_column()
                    name_map[old_name] = canon_col

                _canon(col.this, canon_col)
                table_id = col.args.get("table")
                if table_id:
                    _canon(table_id, canon_t)

            # Rename the alias on the container (table name + any declared column aliases)
            if alias_holder:
                alias = alias_holder.args.get("alias")
                if alias:
                    if isinstance(alias.this, exp.Identifier):
                        _canon(alias.this, canon_t)
                    if alias.columns:
                        alias.set(
                            "columns",
                            [
                                exp.to_identifier(name_map.get(c.name, c.name))
                                for c in alias.columns
                            ],
                        )
                # BigQuery UNNEST ... WITH OFFSET AS <id> declares a pseudo-column via
                # the offset arg (not the alias) — canonicalize it too.
                if isinstance(alias_holder, exp.Unnest):
                    offset_id = alias_holder.args.get("offset")
                    if isinstance(offset_id, exp.Identifier) and offset_id.name in name_map:
                        _canon(offset_id, name_map[offset_id.name])

        # PIVOTs attach to a Table rather than being a source in scope.sources, but their
        # alias acts as a table qualifier for column references like `my_pivot.x`.
        # Only the alias is canonicalized — the pivot output column names are bound to
        # the IN-clause literals (e.g. IN ('x') produces a column literally named `x`),
        # so renaming them would break the query.
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

        # Rewrite Table nodes (real tables and CTE/subquery references in FROM)
        for table in scope.tables:
            canon = table_map.get(table.alias_or_name)
            if not canon:
                continue

            # Only rename the table name for CTE/subquery references (no db/catalog).
            # For real tables, keep the physical reference intact — only the alias changes.
            if isinstance(table.this, exp.Identifier) and not table.args.get("db"):
                _canon(table.this, canon)

            alias = table.args.get("alias")
            if alias:
                if isinstance(alias.this, exp.Identifier):
                    _canon(alias.this, canon)
                # Table-valued functions (e.g. generate_series(1,10) AS g(n)) declare column
                # aliases on the TableAlias — canonicalize them using the shared column map.
                if alias.columns:
                    tc = table_columns.get(id(table), {})
                    alias.set(
                        "columns",
                        [exp.to_identifier(tc.get(c.name, c.name)) for c in alias.columns],
                    )

        # Rewrite SELECT aliases and build the output mapping for parent scopes
        output_map: dict[str, str] = {}
        scope_expr = scope.expression
        if isinstance(scope_expr, exp.Select):
            for sel in scope_expr.selects:
                if isinstance(sel, exp.Alias):
                    old_alias = sel.alias
                    inner = sel.this
                    new_name = inner.name if isinstance(inner, exp.Column) else next_column()
                    output_map[old_alias] = new_name
                    sel.set("alias", exp.to_identifier(new_name))
        elif isinstance(scope_expr, exp.SetOperation) and scope.union_scopes:
            # SetOperation results adopt the left branch's column names
            output_map = scope_outputs.get(id(scope.union_scopes[0].expression), {}).copy()

        scope_outputs[id(scope_expr)] = output_map

        # Rewrite unqualified alias references (e.g., ORDER BY a, HAVING a > 5 referencing a SELECT alias)
        for col in find_all_in_scope(scope_expr, exp.Column):
            if not col.table and col.name in output_map:
                _canon(col.this, output_map[col.name])

        # For UNION BY NAME, align canonical column names across branches so that columns
        # with matching original aliases end up with the same canonical name. Without this,
        # `SELECT a FROM x UNION BY NAME SELECT a FROM y` and `... UNION BY NAME SELECT b FROM y`
        # produce the same fingerprint despite having different semantics.
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
                for node in right_scope.expression.walk():
                    if isinstance(node, exp.Identifier) and node.name in rename:
                        _canon(node, rename[node.name])

                scope_outputs[id(right_scope.expression)] = {
                    k: rename.get(v, v) for k, v in right_out.items()
                }

    return expression
