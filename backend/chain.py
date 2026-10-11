import ast
import re
from functools import lru_cache

from langchain_community.utilities import SQLDatabase
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnableLambda, RunnablePassthrough

from prompts import ANSWER_PROMPT, COLUMN_DESCRIPTIONS, SQL_PROMPT

LLM_MODEL = "gemini-1.5-pro"

# 한 번에 보여줄 최대 회원 수 (SQL의 LIMIT)
MAX_ROWS = 20

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


def clean_sql(text: str) -> str:
    # 지시와 달리 ```sql ... ``` 로 감싸거나 "SQL:" 을 붙이는 경우 제거
    text = re.sub(r"```(?:sql)?", "", text, flags=re.IGNORECASE).strip()
    text = re.sub(r"^SQL\s*(Query)?\s*:\s*", "", text, flags=re.IGNORECASE)
    return text.strip()


def validate_sql(query: str) -> str:
    if not query:
        raise InvalidQueryError("유효한 쿼리를 생성할 수 없습니다.")

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
    )
    answer_prompt = ANSWER_PROMPT.partial(max_rows=str(MAX_ROWS))

    sql_llm = ChatGoogleGenerativeAI(model=LLM_MODEL, temperature=0, max_output_tokens=600)
    answer_llm = ChatGoogleGenerativeAI(model=LLM_MODEL, temperature=0, max_output_tokens=4096)

    sql_chain = (
        sql_prompt
        | sql_llm
        | StrOutputParser()
        | RunnableLambda(clean_sql)
        | RunnableLambda(validate_sql)
    )

    return (
        RunnablePassthrough.assign(query=sql_chain)
        .assign(response=lambda v: db.run(v["query"]))
        | answer_prompt
        | answer_llm
        | StrOutputParser()
    )


def get_response(user_query: str, db: SQLDatabase, chat_history: list):
    try:
        return build_chain(db).invoke({
            "question": user_query,
            "chat_history": "\n".join(chat_history),
        })
    except InvalidQueryError as e:
        return str(e)
