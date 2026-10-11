"""실제 Gemini를 호출해 프롬프트 동작을 점검하는 평가 스크립트. (pytest 대상 아님)

프롬프트를 고친 뒤 기존 동작이 깨지지 않았는지 확인할 때 실행한다.
    cd backend && python tests/eval_llm.py
    python tests/eval_llm.py --delay 0      # 유료 등급 등 호출 제한이 없을 때

점검 항목
- 분류: 인사·잡담은 NO_QUERY, 회원 질문은 SQL
- 컬럼: 기본 컬럼을 정해진 순서로 조회하고, 자택 정보는 요청했을 때만 조회
- 답변: 결과의 모든 값이 빠짐없이 그대로(링크 포함) 출력되고, '없음' 같은 표기가 없음
- 후속 질문: 이전 SQL을 대화 기록으로 받아 조건을 이어서 쓰는지
"""
import argparse
import ast
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

import main  # noqa: E402  (DB 연결)
from chain import NO_QUERY, build_chains, format_history, run_query  # noqa: E402
from prompts import BASE_COLUMNS, FIELD_LABELS  # noqa: E402

BASE = [c.strip() for c in BASE_COLUMNS.split(",")]
HOME_COLUMNS = {"orgmem_home_addr_zipcode", "orgmem_home_addr1", "orgmem_home_addr2", "orgmem_home_tel"}
LABEL_OF = {cols[0]: label for cols, label in FIELD_LABELS}

CHAT_QUESTIONS = ["안녕", "고마워!", "너는 뭘 할 수 있어?", "오늘 날씨 어때?"]

# (질문, 추가로 조회해야 하는 컬럼, 자택 정보 조회 여부)
MEMBER_QUESTIONS = [
    ("울산에서 일하는 선생님 찾아줘", {"jobtype"}, False),
    ("강구관 연락처 알려줘", set(), False),
    ("총동문회 회장이 누구야?", set(), False),
    ("밴드부 회원 알려줘", {"orgmem_circles"}, False),
    ("회원 명단 보여줘", set(), False),
    ("강구관 자택 주소 알려줘", {"orgmem_home_addr1"}, True),
    ("제주에서 일하는 회원 찾아줘", set(), False),
]

FOLLOW_UP = ("그 중에 홍씨만 알려줘", "울산에서 일하는 선생님 찾아줘", ["orgmem_area_work", "교육자", "홍"])


class Evaluator:
    def __init__(self, delay: float):
        self.chains = build_chains(main.db)
        self.delay = delay
        self.failures = []

    def call(self, runnable, inputs):
        result = runnable.invoke(inputs)
        time.sleep(self.delay)  # 무료 등급: 모델당 분당 15회
        return result

    def check(self, name: str, ok: bool, detail: str = ""):
        print(f"  [{'OK' if ok else 'FAIL'}] {name}{' — ' + detail if detail and not ok else ''}")
        if not ok:
            self.failures.append(f"{name}: {detail}")

    def sql(self, question: str, history: list = ()) -> str:
        return self.call(self.chains.sql, {"question": question, "chat_history": format_history(list(history))})

    def answer(self, question: str, query: str, result: dict) -> str:
        return self.call(self.chains.answer, {"question": question, "chat_history": "", "query": query, **result})

    def check_answer(self, question: str, query: str, result: dict):
        text = self.answer(question, query, result)
        rows = ast.literal_eval(result["response"]) if result["row_count"] else []
        missing = []
        for row in rows:
            for column, value in row.items():
                expected = f"**{value}**" if column == "orgmem_name" else str(value)
                if expected not in text:
                    missing.append(f"{row.get('orgmem_name')}:{column}")
                if column in LABEL_OF and LABEL_OF[column] not in text:
                    missing.append(f"라벨:{LABEL_OF[column]}")
        self.check("답변에 모든 값·항목 이름 포함", not missing, f"누락 {sorted(set(missing))[:5]}")
        self.check("'None'·'없음' 표기 없음", not rows or ("None" not in text and "없음" not in text))

    def run(self):
        print("\n== 인사·잡담 → NO_QUERY")
        for q in CHAT_QUESTIONS:
            query = self.sql(q)
            self.check(f"{q!r}", query == NO_QUERY, f"SQL: {query}")

        print("\n== 회원 질문 → 조회 컬럼과 답변")
        for q, extra, wants_home in MEMBER_QUESTIONS:
            print(f"- {q}")
            query = self.sql(q)
            if query == NO_QUERY:
                self.check("SQL 생성", False, "NO_QUERY 로 분류됨")
                continue
            match = re.match(r"SELECT\s+(.*?)\s+FROM\s", query, re.S | re.I)
            columns = [c.strip() for c in match.group(1).split(",")] if match else []
            self.check("기본 컬럼을 정해진 순서로 조회", columns[:len(BASE)] == BASE, f"{columns}")
            self.check("필요한 추가 컬럼 조회", extra <= set(columns), f"필요 {extra}, 조회 {columns[len(BASE):]}")
            self.check("자택 정보는 요청했을 때만", bool(HOME_COLUMNS & set(columns)) == wants_home, f"{columns}")
            self.check_answer(q, query, run_query(main.db, query))

        print("\n== 후속 질문 (대화 기록에 이전 SQL 전달)")
        q, prev_q, must_have = FOLLOW_UP
        prev_sql = self.sql(prev_q)
        query = self.sql(q, [f"사용자: {prev_q}", f"실행한 SQL: {prev_sql}"])
        self.check(f"{q!r} 가 이전 조건을 이어서 씀", all(s in query for s in must_have), f"SQL: {query}")

        print(f"\n결과: 실패 {len(self.failures)}건")
        for failure in self.failures:
            print(f"  - {failure}")
        return not self.failures


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="실제 Gemini로 프롬프트 동작 점검")
    parser.add_argument("--delay", type=float, default=4.5, help="LLM 호출 간 대기(초). 무료 등급 분당 15회 제한 대응 (기본 4.5)")
    args = parser.parse_args()
    sys.exit(0 if Evaluator(args.delay).run() else 1)
