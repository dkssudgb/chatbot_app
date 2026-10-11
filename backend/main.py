import os
from pathlib import Path
from dotenv import load_dotenv

import asyncio
from fastapi import FastAPI, HTTPException, Form, Depends
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from typing import List

from chain import init_database, get_response, stream_response
from langchain_community.utilities import SQLDatabase

app = FastAPI()

# React 앱이 다른 도메인에서 FastAPI 서버에 요청하기 때문에 CORS 설정 필요
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 환경 변수 로드
load_dotenv()

# API_KEY = os.getenv('GOOGLE_API_KEY')

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
        # 사용자의 질문에 대한 응답 생성
        response = get_response(user.question, db, user.chat_history)
        return {"question": user.question, "answer": response}
    
    except Exception as e:
        print(str(e))
        raise HTTPException(status_code=500, detail=str(e))

# 답변을 생성되는 대로 text/plain 청크로 전송
@app.post("/ask/stream")
def ask_question_stream(user: User, db: SQLDatabase = Depends(get_db)):
    chunks = stream_response(user.question, db, user.chat_history)
    
    # 첫 청크는 SQL 생성·실행이 끝나야 나오므로 미리 받아 둔다.
    # 이 단계의 오류는 응답 시작 전이라 일반 500 에러로 돌려줄 수 있다.
    try:
        first_chunk = next(chunks, "")
    except Exception as e:
        print(str(e))
        raise HTTPException(status_code=500, detail=str(e))
    
    def generate():
        yield first_chunk
        try:
            yield from chunks
        except Exception as e:
            # 응답이 이미 시작되어 상태 코드를 바꿀 수 없으므로 본문에 오류를 덧붙인다.
            print(str(e))
            yield f"\n\n(답변 중 오류가 발생했습니다: {e})"
    
    return StreamingResponse(generate(), media_type="text/plain; charset=utf-8")

