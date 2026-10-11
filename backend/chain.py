import ast
import os
import re
from functools import lru_cache

from langchain_community.utilities import SQLDatabase
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnableLambda, RunnablePassthrough

from prompts import ANSWER_PROMPT, BASE_COLUMNS, CHAT_PROMPT, COLUMN_DESCRIPTIONS, FIELD_LABELS_TEXT, SQL_PROMPT

# .env 의 GEMINI_MODEL 로 변경 가능
DEFAULT_LLM_MODEL = "gemini-3.5-flash-lite"

# 한 번에 보여줄 최대 회원 수 (SQL의 LIMIT)
MAX_ROWS = 20

# 회원 조회가 필요 없는 질문일 때 SQL 단계가 출력하는 값
NO_QUERY = "NO_QUERY"

# 저장 값 목록을 프롬프트에 넣어줄 분류형 컬럼
CATEGORICAL_COLUMNS = ["orgmem_area_work", "jobtype", "orgmem_major_txt", "orgmem_circles",
                       "org_position", "orgmem_executive"]

FORBIDDEN_SQL = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|REPLACE|TRUNCATE|ATTACH|DETACH|PRAGMA|VACUUM|GRANT|REVOKE)\b",
    re.IGNORECASE,
)


class InvalidQueryError(ValueError):
    """LLM이 실행할 수 없거나 허용되지 않는 SQL을 생성한 경우."""


def init_database(db_uri: str) -> SQLDatabase:
    # 예: sqlite:///../db/members.db, mysql+mysqlconnector://user:pw@host:3306/db
    # 샘플 행은 회원 개인정보가 매 요청 LLM으로 전송되므로 넣지 않는다.
    return SQLDatabase.from_uri(db_uri, sample_rows_in_table_info=0)


def get_column_values(db: SQLDatabase) -> str:
    lines = []
    for column in CATEGORICAL_COLUMNS:
        result = db.run(f"SELECT DISTINCT {column} FROM orgmember WHERE {column} IS NOT NULL ORDER BY {column}")
        values = [row[0] for row in ast.literal_eval(result)] if result else []
        lines.append(f"- {column}: {', '.join(map(str, values))}")
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
    # db.run()은 결과를 문자열로 돌려주므로, 행 단위로 가공하기 위해 dict 목록을 받는다.
    rows = prepare_rows(db._execute(query))
    limit_note = (f"결과가 최대 개수({MAX_ROWS}개)만큼 조회되어 일부만 보여준 것일 수 있으니, 조건을 좁혀 다시 질문하도록 안내한다."
                  if len(rows) >= MAX_ROWS else "결과 개수가 적으므로 일부만 보여준다는 안내는 하지 않는다.")
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


@lru_cache(maxsize=None)
def build_chain(db: SQLDatabase):
    # 스키마와 저장 값 목록은 요청마다 바뀌지 않으므로 체인을 만들 때 한 번만 조회한다.
    sql_prompt = SQL_PROMPT.partial(
        dialect=db.dialect,
        schema=db.get_table_info(),
        column_descriptions=COLUMN_DESCRIPTIONS,
        column_values=get_column_values(db),
        max_rows=str(MAX_ROWS),
        no_query=NO_QUERY,
        base_columns=BASE_COLUMNS,
    )
    answer_prompt = ANSWER_PROMPT.partial(max_rows=str(MAX_ROWS), field_labels=FIELD_LABELS_TEXT)

    # main.py 의 load_dotenv() 이후에 읽도록 체인을 만들 때 조회한다.
    model = os.getenv("GEMINI_MODEL") or DEFAULT_LLM_MODEL
    # Gemini 3 모델은 추론(thinking) 토큰도 출력 한도에 포함되므로 여유 있게 잡는다.
    sql_llm = ChatGoogleGenerativeAI(model=model, temperature=0, max_output_tokens=2048)
    answer_llm = ChatGoogleGenerativeAI(model=model, temperature=0, max_output_tokens=4096)

    sql_chain = (
        sql_prompt
        | sql_llm
        | StrOutputParser()
        | RunnableLambda(clean_sql)
        | RunnableLambda(validate_sql)
    )

    # 회원 조회: SQL 실행 결과를 바탕으로 답변
    db_answer_chain = (
        # 컬럼명과 함께, 링크·주소를 미리 만들어 넘겨야 LLM이 빠뜨리거나 잘못 옮기지 않는다.
        RunnableLambda(lambda v: {**v, **run_query(db, v["query"])})
        | answer_prompt
        | answer_llm
        | StrOutputParser()
    )
    # 인사·잡담 등: DB를 조회하지 않고 대화로 답변
    chat_chain = CHAT_PROMPT | answer_llm | StrOutputParser()

    def route(inputs):
        return chat_chain if inputs["query"] == NO_QUERY else db_answer_chain

    return RunnablePassthrough.assign(query=sql_chain) | RunnableLambda(route)


def get_response(user_query: str, db: SQLDatabase, chat_history: list):
    try:
        return build_chain(db).invoke({
            "question": user_query,
            "chat_history": "\n".join(chat_history),
        })
    except InvalidQueryError as e:
        return str(e)


def stream_response(user_query: str, db: SQLDatabase, chat_history: list):
    # SQL 생성·실행이 끝난 뒤 답변 LLM의 출력 토큰을 생성되는 대로 내보낸다.
    try:
        yield from build_chain(db).stream({
            "question": user_query,
            "chat_history": "\n".join(chat_history),
        })
    except InvalidQueryError as e:
        yield str(e)
