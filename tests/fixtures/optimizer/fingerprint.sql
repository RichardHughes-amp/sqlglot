# title: simple select
SELECT a FROM x;
SELECT _t0._c0 AS _c0 FROM _t0 AS _t0;

# title: select with where
SELECT a FROM x WHERE b > 5;
SELECT _t0._c0 AS _c0 FROM _t0 AS _t0 WHERE _t0._c1 > 5;

# title: select star expanded
SELECT * FROM x;
SELECT _t0._c0 AS _c0, _t0._c1 AS _c1 FROM _t0 AS _t0;

# title: two columns
SELECT a, b FROM x;
SELECT _t0._c0 AS _c0, _t0._c1 AS _c1 FROM _t0 AS _t0;

# title: single cte
WITH t AS (SELECT a, b FROM x) SELECT * FROM t;
WITH _t1 AS (SELECT _t0._c0 AS _c0, _t0._c1 AS _c1 FROM _t0 AS _t0) SELECT _t1._c0 AS _c0, _t1._c1 AS _c1 FROM _t1 AS _t1;

# title: multi cte
WITH t1 AS (SELECT a FROM x), t2 AS (SELECT b FROM y) SELECT t1.a, t2.b FROM t1 JOIN t2 ON t1.a = t2.b;
WITH _t2 AS (SELECT _t0._c0 AS _c0 FROM _t0 AS _t0), _t3 AS (SELECT _t1._c1 AS _c1 FROM _t1 AS _t1) SELECT _t2._c0 AS _c0, _t3._c1 AS _c1 FROM _t2 AS _t2 JOIN _t3 AS _t3 ON _t2._c0 = _t3._c1;

# title: cross join
SELECT x.a, y.c FROM x CROSS JOIN y;
SELECT _t0._c0 AS _c0, _t1._c1 AS _c1 FROM _t0 AS _t0 CROSS JOIN _t1 AS _t1;

# title: inner join
SELECT x.a, y.c FROM x JOIN y ON x.b = y.b;
SELECT _t0._c0 AS _c0, _t1._c2 AS _c2 FROM _t0 AS _t0 JOIN _t1 AS _t1 ON _t0._c1 = _t1._c3;

# title: self join
SELECT a.a, b.b FROM x AS a JOIN x AS b ON a.a = b.b;
SELECT _t0._c0 AS _c0, _t1._c1 AS _c1 FROM _t0 AS _t0 JOIN _t1 AS _t1 ON _t0._c0 = _t1._c1;

# title: subquery in from
SELECT t.a FROM (SELECT a FROM x) AS t;
SELECT _t1._c0 AS _c0 FROM (SELECT _t0._c0 AS _c0 FROM _t0 AS _t0) AS _t1;

# title: subquery with column aliases
SELECT t.p, t.q FROM (SELECT a, b FROM x) AS t(p, q);
SELECT _t1._c0 AS _c0, _t1._c1 AS _c1 FROM (SELECT _t0._c0 AS _c0, _t0._c1 AS _c1 FROM _t0 AS _t0) AS _t1;

# title: nested subqueries
SELECT t.a FROM (SELECT t.a FROM (SELECT a FROM x) AS t) AS t;
SELECT _t2._c0 AS _c0 FROM (SELECT _t1._c0 AS _c0 FROM (SELECT _t0._c0 AS _c0 FROM _t0 AS _t0) AS _t1) AS _t2;

# title: uncorrelated subquery
SELECT a FROM x WHERE b IN (SELECT b FROM y);
SELECT _t1._c1 AS _c1 FROM _t1 AS _t1 WHERE _t1._c2 IN (SELECT _t0._c0 AS _c0 FROM _t0 AS _t0);

# title: correlated subquery
SELECT a FROM x WHERE EXISTS (SELECT 1 FROM y WHERE y.b = x.b);
SELECT _t1._c2 AS _c2 FROM _t1 AS _t1 WHERE EXISTS(SELECT 1 AS _c1 FROM _t0 AS _t0 WHERE _t0._c0 = _t1._c3);

# title: aggregation
SELECT a, COUNT(b) FROM x GROUP BY a HAVING COUNT(b) > 1;
SELECT _t0._c0 AS _c0, COUNT(_t0._c1) AS _c2 FROM _t0 AS _t0 GROUP BY _t0._c0 HAVING COUNT(_t0._c1) > 1;

# title: expression in select
SELECT a + 1 FROM x;
SELECT _t0._c0 + 1 AS _c1 FROM _t0 AS _t0;

# title: order by alias reference
SELECT a, b FROM x ORDER BY a LIMIT 10;
SELECT _t0._c0 AS _c0, _t0._c1 AS _c1 FROM _t0 AS _t0 ORDER BY _c0 LIMIT 10;

# title: order by positional reference
SELECT a, b FROM x ORDER BY 1 DESC;
SELECT _t0._c0 AS _c0, _t0._c1 AS _c1 FROM _t0 AS _t0 ORDER BY _c0 DESC;

# title: group by positional reference
SELECT a, COUNT(b) FROM x GROUP BY 1;
SELECT _t0._c0 AS _c0, COUNT(_t0._c1) AS _c2 FROM _t0 AS _t0 GROUP BY _t0._c0;

# title: group by multiple positional references
SELECT a, b, COUNT(*) FROM x GROUP BY 1, 2;
SELECT _t0._c0 AS _c0, _t0._c1 AS _c1, COUNT(*) AS _c2 FROM _t0 AS _t0 GROUP BY _t0._c0, _t0._c1;

# title: union
SELECT a FROM x UNION SELECT b FROM y;
SELECT _t0._c0 AS _c0 FROM _t0 AS _t0 UNION SELECT _t1._c1 AS _c1 FROM _t1 AS _t1;

# title: union by name, matching column names unify to the same canonical name
# dialect: duckdb
SELECT a, b FROM x UNION BY NAME SELECT b, c FROM z;
SELECT _t0._c0 AS _c0, _t0._c1 AS _c1 FROM _t0 AS _t0 UNION BY NAME SELECT _t1._c1 AS _c1, _t1._c3 AS _c3 FROM _t1 AS _t1;

# title: union by name, disjoint column names stay distinct
# dialect: duckdb
SELECT a FROM x UNION BY NAME SELECT c FROM y;
SELECT _t0._c0 AS _c0 FROM _t0 AS _t0 UNION BY NAME SELECT _t1._c1 AS _c1 FROM _t1 AS _t1;

# title: case when
SELECT CASE WHEN a > 0 THEN b ELSE a END FROM x;
SELECT CASE WHEN _t0._c0 > 0 THEN _t0._c1 ELSE _t0._c0 END AS _c2 FROM _t0 AS _t0;

# title: three way join
SELECT x.a, y.b, z.c FROM x JOIN y ON x.b = y.b JOIN z ON y.c = z.c;
SELECT _t0._c0 AS _c0, _t1._c2 AS _c2, _t2._c4 AS _c4 FROM _t0 AS _t0 JOIN _t1 AS _t1 ON _t0._c1 = _t1._c2 JOIN _t2 AS _t2 ON _t1._c3 = _t2._c4;

# title: struct field access, field names are preserved
SELECT structs.one.a_1 FROM structs;
SELECT _t0._c0.a_1 AS _c1 FROM _t0 AS _t0;

# title: nested struct field access, field names are preserved
SELECT structs.nested_0.nested_1.a_2 FROM structs;
SELECT _t0._c0.nested_1.a_2 AS _c1 FROM _t0 AS _t0;

# title: struct field access in where, field names are preserved
SELECT structs.one.b_1 FROM structs WHERE structs.one.a_1 > 0;
SELECT _t0._c0.b_1 AS _c1 FROM _t0 AS _t0 WHERE _t0._c0.a_1 > 0;

# title: json bracket access, field names are preserved
SELECT j['name'] FROM jtbl WHERE j['age'] > 18;
SELECT _t0._c0['name'] AS _c1 FROM _t0 AS _t0 WHERE _t0._c0['age'] > 18;

# title: json nested bracket access, field names are preserved
SELECT j['a']['b'] FROM jtbl;
SELECT _t0._c0['a']['b'] AS _c1 FROM _t0 AS _t0;

# title: json extract function, path string is preserved
SELECT JSON_EXTRACT(j, '$.field') FROM jtbl;
SELECT JSON_EXTRACT(_t0._c0, '$.field') AS _c1 FROM _t0 AS _t0;

# title: postgres json arrow operator, field name is preserved
# dialect: postgres
SELECT j -> 'field' FROM jtbl;
SELECT _t0._c0 -> 'field' AS _c1 FROM _t0 AS _t0;
