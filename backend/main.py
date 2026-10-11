import os
from pathlib import Path
from dotenv import load_dotenv
import markdown2

import asyncio
from fastapi import FastAPI, HTTPException, Request, Form, Depends
from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from typing import List

from chain import init_database, get_response
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

# HTML 템플릿을 렌더링하기 위한 설정
# directory의 폴더에서 HTML 파일을 찾음
templates = Jinja2Templates(directory="../frontend/public")

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

@app.get("/", response_class=HTMLResponse) # 메인화면 구성
async def read_index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.post("/ask")
async def ask_question(user: User, db: SQLDatabase = Depends(get_db)):
    try:
        # 사용자의 질문에 대한 응답 생성
        response = get_response(user.question, db, user.chat_history)
        return {"question": user.question, "answer": response}
        
        # async def stream_response():
        #     async for chunk in get_response(user_question.question, db, chat_history):
        #         yield chunk
        #         await asyncio.sleep(0.1)
        # return StreamingResponse(stream_response(), media_type="text/event-stream")
    
    except Exception as e:
        print(str(e))
        raise HTTPException(status_code=500, detail=str(e))

