import logging
import os
import re
import time
from dataclasses import dataclass
from functools import lru_cache
from typing import Iterator

from langchain_community.utilities import SQLDatabase
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import Runnable, RunnableLambda
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from prompts import ANSWER_PROMPT, BASE_COLUMNS, CHAT_PROMPT, COLUMN_DESCRIPTIONS, FIELD_LABELS_TEXT, SQL_PROMPT

logger = logging.getLogger("chatbot")

# .env 의 GEMINI_MODEL 로 변경 가능
DEFAULT_LLM_MODEL = "gemini-3.5-flash-lite"

# 한 번에 보여줄 최대 회원 수
MAX_ROWS = 20

# 대화 기록은 최근 항목만, 항목마다 길이를 잘라서 프롬프트에 넣는다.
MAX_HISTORY_ITEMS = 10
MAX_HISTORY_ITEM_CHARS = 500

# 회원 조회가 필요 없는 질문일 때 SQL 단계가 출력하는 값
NO_QUERY = "NO_QUERY"

# 저장 값 목록을 프롬프트에 넣어줄 분류형 컬럼
CATEGORICAL_COLUMNS = ["orgmem_area_work", "jobtype", "orgmem_major_txt", "orgmem_circles",
                       "org_position", "orgmem_executive"]

FORBIDDEN_SQL = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|REPLACE|TRUNCATE|ATTACH|DETACH|PRAGMA|VACUUM|GRANT|REVOKE)\b",
    re.IGNORECASE,
)

# 사용자에게 보여줄 오류 문구 (원문은 서버 로그에만 남긴다)
SQL_ERROR_MESSAGE = "질문을 이해하지 못했어요. 조금 다르게 물어봐 주세요."
GENERAL_ERROR_MESSAGE = "일시적인 오류가 발생했어요. 잠시 후 다시 시도해 주세요."


class InvalidQueryError(ValueError):
    """LLM이 실행할 수 없거나 허용되지 않는 SQL을 생성한 경우."""


def user_error_message(error: Exception) -> str:
    if isinstance(error, SQLAlchemyError):
        return SQL_ERROR_MESSAGE
    return GENERAL_ERROR_MESSAGE


def init_database(db_uri: str) -> SQLDatabase:
    # 예: sqlite:///../db/members.db, mysql+mysqlconnector://user:pw@host:3306/db
    # 샘플 행은 회원 개인정보가 매 요청 LLM으로 전송되므로 넣지 않는다.
    return SQLDatabase.from_uri(db_uri, sample_rows_in_table_info=0)


def fetch_rows(db: SQLDatabase, query: str, max_rows: int) -> list:
    # db.run()은 결과 전체를 문자열로 돌려주므로, 엔진으로 직접 실행해 필요한 행만 dict 로 읽는다.
    with db._engine.connect() as conn:
        result = conn.execute(text(query))
        return [dict(row._mapping) for row in result.fetchmany(max_rows)]


def get_column_values(db: SQLDatabase) -> str:
    lines = []
    for column in CATEGORICAL_COLUMNS:
        rows = fetch_rows(db, f"SELECT DISTINCT {column} FROM orgmember WHERE {column} IS NOT NULL ORDER BY {column}", 1000)
        lines.append(f"- {column}: {', '.join(str(row[column]) for row in rows)}")
    return "\n".join(lines)


def _tel_link(number: str) -> str:
    # 010-1234-5678 → [010-1234-5678](tel:+821012345678)
    digits = re.sub(r"\D", "", number)
    return f"[{number}](tel:+82{digits[1:]})" if digits.startswith("0") else number


def _join(*parts) -> str:
    return " ".join(str(p) for p in parts if p)


def prepare_rows(rows: list) -> list:
    """LLM이 그대로 옮겨 쓰기만 하면 되도록 SQL 결과를 정리한다.

    - 값이 없는(None·빈 문자열) 컬럼 제외
    - 3칸으로 나뉜 휴대전화를 tel 링크 하나로, 이메일은 mailto 링크로
    - 우편번호·주소·상세주소를 한 줄로
    """
    prepared = []
    for row in rows:
        out = {}
        for column, value in row.items():
            if value is None or value == "":
                continue
            if column == "orgmem_phone1":
                number = "-".join(str(row[c]) for c in ("orgmem_phone1", "orgmem_phone2", "orgmem_phone3") if row.get(c))
                out["orgmem_phone"] = _tel_link(number)
            elif column in ("orgmem_phone2", "orgmem_phone3"):
                continue
            elif column == "orgmem_home_tel":
                out[column] = _tel_link(str(value))
            elif column == "orgmem_email":
                out[column] = f"[{value}](mailto:{value})"
            elif column.startswith(("orgmem_home_addr", "orgmem_office_addr")):
                key = "orgmem_home_addr" if column.startswith("orgmem_home") else "orgmem_office_addr"
                if key not in out:
                    zipcode, addr1, addr2 = (row.get(f"{key}{s}") for s in ("_zipcode", "1", "2"))
                    out[key] = _join(f"({zipcode})" if zipcode else None, addr1, addr2)
            else:
                out[column] = value
        prepared.append(out)
    return prepared


def run_query(db: SQLDatabase, query: str) -> dict:
    started = time.perf_counter()
    # LIMIT 을 프롬프트에만 맡기지 않고 코드에서도 MAX_ROWS 개까지만 LLM에 넘긴다.
    # 1개를 더 읽어서 결과가 잘렸는지 판단한다.
    rows = fetch_rows(db, query, MAX_ROWS + 1)
    truncated = len(rows) > MAX_ROWS
    rows = prepare_rows(rows[:MAX_ROWS])
    logger.info("DB 결과 %d행%s (%.0fms)", len(rows), " (잘림)" if truncated else "", (time.perf_counter() - started) * 1000)

    limit_note = (f"조회 결과가 {MAX_ROWS}개를 넘어 일부만 보여주므로, 조건을 좁혀 다시 질문하도록 안내한다."
                  if truncated else "일부만 보여준다는 안내는 하지 않는다.")
    return {"response": str(rows) if rows else "(결과 없음)", "row_count": len(rows), "limit_note": limit_note}


def clean_sql(text: str) -> str:
    # 지시와 달리 ```sql ... ``` 로 감싸거나 "SQL:" 을 붙이는 경우 제거
    text = re.sub(r"```(?:sql)?", "", text, flags=re.IGNORECASE).strip()
    text = re.sub(r"^SQL\s*(Query)?\s*:\s*", "", text, flags=re.IGNORECASE)
    return text.strip()


def validate_sql(query: str) -> str:
    if not query:
        raise InvalidQueryError("유효한 쿼리를 생성할 수 없습니다.")
    if query.rstrip(";").strip().upper() == NO_QUERY:
        return NO_QUERY

    statements = [s for s in query.split(";") if s.strip()]
    if len(statements) != 1:
        raise InvalidQueryError("한 번에 하나의 조회 쿼리만 실행할 수 있습니다.")

    statement = statements[0].strip()
    if not re.match(r"^(SELECT|WITH)\b", statement, re.IGNORECASE) or FORBIDDEN_SQL.search(statement):
        raise InvalidQueryError("회원 정보 조회 외의 요청은 처리할 수 없습니다.")
    return statement


def format_history(chat_history: list) -> str:
    # 클라이언트가 긴 기록을 보내더라도 프롬프트가 커지지 않도록 자른다.
    items = [item[:MAX_HISTORY_ITEM_CHARS] for item in chat_history[-MAX_HISTORY_ITEMS:]]
    return "\n".join(items)


@dataclass
class Chains:
    sql: Runnable     # 질문 → SQL 또는 NO_QUERY
    answer: Runnable  # 질문 + SQL 결과 → 답변
    chat: Runnable    # 인사·잡담 → 답변 (DB 조회 없음)


@lru_cache(maxsize=None)
def build_chains(db: SQLDatabase) -> Chains:
    # 스키마와 저장 값 목록은 요청마다 바뀌지 않으므로 체인을 만들 때 한 번만 조회한다.
    sql_prompt = SQL_PROMPT.partial(
        dialect=db.dialect,
        schema=db.get_table_info(),
        column_descriptions=COLUMN_DESCRIPTIONS,
        column_values=get_column_values(db),
        # 결과가 잘렸는지 알 수 있도록 SQL에서는 1개 더 조회하게 한다. (run_query 참고)
        sql_limit=str(MAX_ROWS + 1),
        no_query=NO_QUERY,
        base_columns=BASE_COLUMNS,
    )
    answer_prompt = ANSWER_PROMPT.partial(field_labels=FIELD_LABELS_TEXT)

    # main.py 의 load_dotenv() 이후에 읽도록 체인을 만들 때 조회한다.
    model = os.getenv("GEMINI_MODEL") or DEFAULT_LLM_MODEL
    # Gemini 3 모델은 추론(thinking) 토큰도 출력 한도에 포함되므로 여유 있게 잡는다.
    sql_llm = ChatGoogleGenerativeAI(model=model, temperature=0, max_output_tokens=2048)
    answer_llm = ChatGoogleGenerativeAI(model=model, temperature=0, max_output_tokens=4096)

    return Chains(
        sql=sql_prompt | sql_llm | StrOutputParser() | RunnableLambda(clean_sql) | RunnableLambda(validate_sql),
        answer=answer_prompt | answer_llm | StrOutputParser(),
        chat=CHAT_PROMPT | answer_llm | StrOutputParser(),
    )


def prepare_answer(user_query: str, db: SQLDatabase, chat_history: list) -> tuple:
    """SQL 생성·실행까지 마치고 (생성된 SQL, 답변 청크 iterator) 를 돌려준다.

    여기서 난 오류는 답변을 보내기 전이므로 호출한 쪽에서 오류 응답으로 처리할 수 있다.
    허용되지 않는 SQL이면 SQL 없이 안내 문구 하나만 돌려준다.
    """
    chains = build_chains(db)
    inputs = {"question": user_query, "chat_history": format_history(chat_history)}

    started = time.perf_counter()
    try:
        query = chains.sql.invoke(inputs)
    except InvalidQueryError as e:
        logger.warning("질문=%r → 허용되지 않는 SQL: %s", user_query, e)
        return None, iter([str(e)])
    logger.info("질문=%r → SQL: %s (%.2fs)", user_query, query, time.perf_counter() - started)

    if query == NO_QUERY:
        return query, chains.chat.stream(inputs)
    return query, chains.answer.stream({**inputs, "query": query, **run_query(db, query)})


def get_response(user_query: str, db: SQLDatabase, chat_history: list) -> tuple:
    query, chunks = prepare_answer(user_query, db, chat_history)
    return query, "".join(chunks)
