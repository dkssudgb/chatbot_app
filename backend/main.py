import logging
import os
import time
from pathlib import Path
from typing import List
from urllib.parse import quote

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Depends
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from langchain_community.utilities import SQLDatabase

from chain import init_database, get_response, prepare_answer, user_error_message

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [%(name)s] %(message)s")
logger = logging.getLogger("chatbot")

# 생성된 SQL을 프론트엔드에 전달하는 응답 헤더 (다음 질문의 대화 기록에 사용)
SQL_HEADER = "X-Generated-SQL"

app = FastAPI()

# React 앱이 다른 도메인에서 FastAPI 서버에 요청하기 때문에 CORS 설정 필요
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=[SQL_HEADER],  # 브라우저에서 이 헤더를 읽을 수 있도록
)

# 환경 변수 로드
load_dotenv()

# 기본값: 저장소의 샘플 DB (python db/seed.py 로 생성)
DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "db" / "members.db"
# mode=ro: 챗봇은 조회만 하므로 읽기 전용으로 연결
DATABASE_URL = os.getenv('DATABASE_URL') or f"sqlite:///file:{DEFAULT_DB_PATH}?mode=ro&uri=true"

# 데이터베이스 (앱 시작 시 한 번만 연결하고 재사용)
db = init_database(DATABASE_URL)

def get_db() -> SQLDatabase:
    return db

class User(BaseModel):
    question: str
    chat_history: List[str]

@app.get("/") # 서버 상태 확인용
async def health_check():
    return {"status": "ok"}

# LLM·DB 호출이 동기 방식이므로 async 대신 def 로 선언해 스레드풀에서 실행 (다른 요청을 막지 않도록)
@app.post("/ask")
def ask_question(user: User, db: SQLDatabase = Depends(get_db)):
    try:
        sql, answer = get_response(user.question, db, user.chat_history)
        return {"question": user.question, "answer": answer, "sql": sql}

    except Exception as e:
        logger.exception("답변 생성 실패: 질문=%r", user.question)
        raise HTTPException(status_code=500, detail=user_error_message(e))

# 답변을 생성되는 대로 text/plain 청크로 전송
@app.post("/ask/stream")
def ask_question_stream(user: User, db: SQLDatabase = Depends(get_db)):
    started = time.perf_counter()

    # SQL 생성·실행과 첫 청크까지는 응답을 시작하기 전에 처리한다.
    # 이 단계의 오류는 일반 500 에러로 돌려줄 수 있다.
    try:
        sql, chunks = prepare_answer(user.question, db, user.chat_history)
        first_chunk = next(chunks, "")
    except Exception as e:
        logger.exception("답변 생성 실패: 질문=%r", user.question)
        raise HTTPException(status_code=500, detail=user_error_message(e))
    logger.info("첫 청크까지 %.2fs", time.perf_counter() - started)

    def generate():
        yield first_chunk
        try:
            yield from chunks
        except Exception as e:
            # 응답이 이미 시작되어 상태 코드를 바꿀 수 없으므로 본문에 오류를 덧붙인다.
            logger.exception("답변 스트리밍 중 실패: 질문=%r", user.question)
            yield f"\n\n({user_error_message(e)})"
        logger.info("답변 완료 %.2fs", time.perf_counter() - started)

    # HTTP 헤더에는 ASCII만 쓸 수 있어 SQL(한글 포함)을 URL 인코딩한다.
    headers = {SQL_HEADER: quote(sql)} if sql else {}
    return StreamingResponse(generate(), media_type="text/plain; charset=utf-8", headers=headers)
