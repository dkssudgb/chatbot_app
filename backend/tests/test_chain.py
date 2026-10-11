"""LLM 없이 실행할 수 있는 chain.py 단위 테스트.

실행: cd backend && python -m pytest
"""
import ast

import pytest

from chain import (
    MAX_HISTORY_ITEM_CHARS, MAX_HISTORY_ITEMS, MAX_ROWS, NO_QUERY, SQL_ERROR_MESSAGE, GENERAL_ERROR_MESSAGE,
    InvalidQueryError, clean_sql, format_history, prepare_rows, run_query, user_error_message, validate_sql,
)


# ---------- clean_sql ----------

@pytest.mark.parametrize("raw, expected", [
    ("SELECT 1", "SELECT 1"),
    ("```sql\nSELECT 1;\n```", "SELECT 1;"),
    ("```\nSELECT 1\n```", "SELECT 1"),
    ("SQL: SELECT 1", "SELECT 1"),
    ("SQL Query: SELECT 1", "SELECT 1"),
    ("  NO_QUERY  ", "NO_QUERY"),
])
def test_clean_sql(raw, expected):
    assert clean_sql(raw) == expected


# ---------- validate_sql ----------

@pytest.mark.parametrize("query", ["NO_QUERY", "no_query", "NO_QUERY;"])
def test_validate_sql_no_query(query):
    assert validate_sql(query) == NO_QUERY


@pytest.mark.parametrize("query", [
    "SELECT orgmem_name FROM orgmember",
    "SELECT orgmem_name FROM orgmember;",
    "WITH t AS (SELECT 1) SELECT * FROM t",
])
def test_validate_sql_allows_single_select(query):
    assert validate_sql(query) == query.rstrip(";")


@pytest.mark.parametrize("query", [
    "",
    "DELETE FROM orgmember",
    "DROP TABLE orgmember",
    "UPDATE orgmember SET orgmem_name = 'x'",
    "PRAGMA table_info(orgmember)",
    "SELECT 1; DROP TABLE orgmember",
    "SELECT 1; SELECT 2",
    "ATTACH DATABASE 'x.db' AS x",
])
def test_validate_sql_rejects(query):
    with pytest.raises(InvalidQueryError):
        validate_sql(query)


# ---------- prepare_rows ----------

def test_prepare_rows_builds_links_and_drops_empty_values():
    rows = [{
        "orgmem_name": "홍길동",
        "orgmem_phone1": "010", "orgmem_phone2": "1234", "orgmem_phone3": "5678",
        "orgmem_email": "hong@example.com",
        "orgmem_home_tel": "052-123-4567",
        "orgmem_home_addr_zipcode": "44610", "orgmem_home_addr1": "울산광역시 남구 삼산로 1", "orgmem_home_addr2": "101동 202호",
        "org_position": None,
        "orgmem_circles": "",
    }]
    assert prepare_rows(rows) == [{
        "orgmem_name": "홍길동",
        "orgmem_phone": "[010-1234-5678](tel:+821012345678)",
        "orgmem_email": "[hong@example.com](mailto:hong@example.com)",
        "orgmem_home_tel": "[052-123-4567](tel:+82521234567)",
        "orgmem_home_addr": "(44610) 울산광역시 남구 삼산로 1 101동 202호",
    }]


def test_prepare_rows_keeps_column_order():
    rows = [{"orgmem_name": "a", "orgmem_seqNum": 3, "orgmem_phone1": "010", "orgmem_phone2": "1", "orgmem_phone3": "2", "jobtype": "교육자"}]
    assert list(prepare_rows(rows)[0]) == ["orgmem_name", "orgmem_seqNum", "orgmem_phone", "jobtype"]


def test_prepare_rows_keeps_aggregates():
    assert prepare_rows([{"COUNT(*)": 7}]) == [{"COUNT(*)": 7}]


# ---------- run_query (샘플 DB) ----------

def test_run_query_truncates_to_max_rows(db):
    # SQL에 LIMIT 이 없어도 MAX_ROWS 개까지만 넘기고, 잘렸다고 안내한다.
    result = run_query(db, "SELECT orgmem_name FROM orgmember ORDER BY orgmem_name")
    assert result["row_count"] == MAX_ROWS
    assert len(ast.literal_eval(result["response"])) == MAX_ROWS
    assert "일부만 보여주므로" in result["limit_note"]


def test_run_query_exactly_max_rows_is_not_truncated(db):
    result = run_query(db, f"SELECT orgmem_name FROM orgmember ORDER BY orgmem_name LIMIT {MAX_ROWS}")
    assert result["row_count"] == MAX_ROWS
    assert "하지 않는다" in result["limit_note"]


def test_run_query_empty_result(db):
    result = run_query(db, "SELECT orgmem_name FROM orgmember WHERE orgmem_area_work = '제주'")
    assert result["row_count"] == 0
    assert result["response"] == "(결과 없음)"


def test_run_query_count(db):
    result = run_query(db, "SELECT COUNT(*) FROM orgmember")
    assert ast.literal_eval(result["response"]) == [{"COUNT(*)": 200}]


def test_run_query_formats_member_rows(db):
    result = run_query(db, "SELECT orgmem_name, orgmem_phone1, orgmem_phone2, orgmem_phone3, orgmem_email "
                           "FROM orgmember WHERE orgmem_name = '강구관'")
    assert ast.literal_eval(result["response"]) == [{
        "orgmem_name": "강구관",
        "orgmem_phone": "[010-1234-5678](tel:+821012345678)",
        "orgmem_email": "[kyun11@example.com](mailto:kyun11@example.com)",
    }]


# ---------- format_history ----------

def test_format_history_limits_items_and_length():
    history = [f"사용자: 질문 {i}" for i in range(MAX_HISTORY_ITEMS + 5)] + ["챗봇: " + "가" * 2000]
    lines = format_history(history).split("\n")
    assert len(lines) == MAX_HISTORY_ITEMS
    assert lines[0] == "사용자: 질문 6"
    assert len(lines[-1]) == MAX_HISTORY_ITEM_CHARS


def test_format_history_empty():
    assert format_history([]) == ""


# ---------- user_error_message ----------

def test_user_error_message(db):
    from sqlalchemy.exc import SQLAlchemyError
    with pytest.raises(SQLAlchemyError) as exc:
        run_query(db, "SELECT no_such_column FROM orgmember")
    assert user_error_message(exc.value) == SQL_ERROR_MESSAGE
    assert user_error_message(RuntimeError("quota exceeded")) == GENERAL_ERROR_MESSAGE
