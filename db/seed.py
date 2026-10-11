"""샘플 동문회 회원 DB(SQLite) 생성 스크립트.

사용법:
    python db/seed.py                 # db/members.db 생성 (회원 200명)
    python db/seed.py -n 500          # 회원 수 지정
    python db/seed.py -o other.db     # 출력 파일 지정

모든 데이터는 무작위로 만든 가상 정보이며, 같은 --seed 값이면 항상 같은 결과가 나온다.
"""
import argparse
import random
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

DB_DIR = Path(__file__).resolve().parent
SCHEMA_PATH = DB_DIR / "schema.sql"
DEFAULT_DB_PATH = DB_DIR / "members.db"

LAST_NAMES = ["김", "이", "박", "최", "정", "강", "조", "윤", "장", "임", "한", "오", "서", "신", "권", "황", "안", "송", "류", "홍"]
LAST_NAMES_CHI = {"김": "金", "이": "李", "박": "朴", "최": "崔", "정": "鄭", "강": "姜", "조": "趙", "윤": "尹", "장": "張", "임": "林",
                  "한": "韓", "오": "吳", "서": "徐", "신": "申", "권": "權", "황": "黃", "안": "安", "송": "宋", "류": "柳", "홍": "洪"}
FIRST_NAME_SYLLABLES = ["민", "서", "준", "지", "현", "우", "수", "영", "도", "하", "은", "진", "태", "성", "윤", "재", "혜", "동", "경", "상", "구", "관", "희", "석"]

# (근무 지역, 지역 코드, 우편번호 앞자리, 주소 접두어)
AREAS = [
    ("서울", "02", "0", "서울특별시 {}구"),
    ("울산", "052", "4", "울산광역시 {}구"),
    ("부산", "051", "4", "부산광역시 {}구"),
    ("대구", "053", "4", "대구광역시 {}구"),
    ("경기", "031", "1", "경기도 {}시"),
    ("경남", "055", "5", "경상남도 {}시"),
]
AREA_WEIGHTS = [30, 30, 15, 8, 12, 5]  # 울산동문회가 있으므로 울산 비중을 높게
DISTRICTS = {
    "서울": ["강남", "서초", "송파", "마포", "종로", "영등포"],
    "울산": ["남", "중", "동", "북"],
    "부산": ["해운대", "부산진", "동래", "연제"],
    "대구": ["수성", "달서", "중", "북"],
    "경기": ["수원", "성남", "용인", "화성"],
    "경남": ["창원", "김해", "양산", "진주"],
}
ROADS = ["중앙로", "번영로", "대학로", "삼산로", "테헤란로", "문화로", "산업로", "해안로"]

# (전공 코드, 상세 전공명)
MAJORS = [
    ("M01", "기계공학과"), ("M02", "전기전자공학과"), ("M03", "화학공학과"), ("M04", "조선해양공학과"),
    ("M05", "컴퓨터공학과"), ("M06", "건축학과"), ("M07", "경영학과"), ("M08", "경제학과"),
    ("M09", "국어국문학과"), ("M10", "영어영문학과"), ("M11", "법학과"), ("M12", "의학과"),
]

# (직종, 근무지 후보, 사업 분야)
JOBS = [
    ("회사원", ["현대자동차", "현대중공업", "SK에너지", "삼성전자", "LG화학", "S-OIL", "포스코"], "제조업"),
    ("자영업", ["한빛상사", "동해무역", "새솔식품", "바른인테리어", "미래카센터"], "도소매업"),
    ("교육자", ["울산고등학교", "서울중학교", "한마음초등학교", "울산대학교", "주식회사 신도"], "교육서비스업"),
    ("공무원", ["울산광역시청", "서울특별시청", "남구청", "국세청", "부산지방법원"], "공공행정"),
    ("의료인", ["울산대학교병원", "서울아산병원", "튼튼정형외과", "밝은눈안과"], "보건업"),
    ("법조인", ["법무법인 정의", "법무법인 한결", "울산지방검찰청"], "법률서비스업"),
    ("IT 개발자", ["네이버", "카카오", "에이치소프트", "데이터랩"], "정보통신업"),
    ("금융인", ["KB국민은행", "신한은행", "경남은행", "삼성증권"], "금융업"),
    ("건축가", ["한울건축사사무소", "현대건설", "태영건설"], "건설업"),
]
TOP_COMPANIES = {"현대자동차", "현대중공업", "SK에너지", "삼성전자", "LG화학", "S-OIL", "포스코", "네이버", "카카오",
                 "KB국민은행", "신한은행", "삼성증권", "현대건설"}
OFFICE_POSITIONS = ["사원", "대리", "과장", "차장", "부장", "이사", "대표", "교사", "교수", "원장", "변호사", "팀장"]

CIRCLES = ["산악회", "축구회", "골프회", "밴드부", "사진동아리", "봉사동아리", "독서회", "바둑회"]

# (컬럼명, 직책 후보, 직책을 가질 확률)
POSITION_COLUMNS = [
    ("org_position", ["부회장", "감사", "이사"], 0.08),
    ("area_position", ["지역부회장", "지역총무"], 0.08),
    ("chapter_position", ["장학이사"], 0.04),
    ("committee_position", ["운영위원", "홍보위원"], 0.06),
    ("etc_position", ["고문", "자문위원"], 0.04),
    ("etc_position1", ["명예회원", "후원회원"], 0.03),
]
ULSAN_EXECUTIVES = ["울산동문회 부회장", "울산동문회 총무", "울산동문회 이사"]
# 한 명만 맡는 직책: (컬럼명, 직책, 대상 근무 지역 또는 None)
UNIQUE_POSITIONS = [
    ("org_position", "회장", None),
    ("org_position", "수석부회장", None),
    ("org_position", "사무총장", None),
    ("chapter_position", "장학회장", None),
    ("committee_position", "운영위원장", None),
    ("orgmem_executive", "울산동문회장", "울산"),
]
REGION_WORDS = ["서울", "울산", "부산", "대구", "경남", "경기"]


def make_name(rng):
    last = rng.choice(LAST_NAMES)
    return last, last + "".join(rng.sample(FIRST_NAME_SYLLABLES, 2))


def make_address(rng, area, prefix, zip_head):
    district = rng.choice(DISTRICTS[area])
    zipcode = zip_head + "".join(str(rng.randint(0, 9)) for _ in range(4))
    addr1 = f"{prefix.format(district)} {rng.choice(ROADS)} {rng.randint(1, 300)}"
    return zipcode, addr1


def make_member(rng, idx):
    last, name = make_name(rng)
    area, area_code, zip_head, prefix = rng.choices(AREAS, weights=AREA_WEIGHTS)[0]
    major_code, major_txt = rng.choice(MAJORS)
    jobtype, offices, business_field = rng.choice(JOBS)
    # 다른 지역명이 들어간 근무지(예: 서울 근무자의 '울산광역시청')는 제외
    local_offices = [o for o in offices if not any(r in o for r in REGION_WORDS if r != area)]
    office = rng.choice(local_offices or offices)

    admyear = rng.randint(1985, 2020)
    grdyear = admyear + rng.choice([4, 4, 4, 6])  # 일부는 군 복무 등으로 6년
    seq_num = admyear - 1984  # 1985년 입학생 = 1기

    home_zip, home_addr1 = make_address(rng, area, prefix, zip_head)
    office_zip, office_addr1 = make_address(rng, area, prefix, zip_head)
    email_id = f"member{idx:04d}"
    circle = rng.choice(CIRCLES) if rng.random() < 0.4 else None

    member = {
        "orgmem_name": name,
        "orgmem_name_chi": LAST_NAMES_CHI[last] + "○○",
        "orgmem_lunar": rng.choice(["양력", "양력", "음력"]),
        "orgmem_seqNum": seq_num,
        "orgmem_major": major_code,
        "orgmem_major_txt": major_txt,
        "orgmem_admyear": admyear,
        "orgmem_grdyear": grdyear,
        "orgmem_class": f"{grdyear}년 졸업반",
        "orgmem_circles": circle,
        "orgmem_phone1": "010",
        "orgmem_phone2": f"{rng.randint(1000, 9999)}",
        "orgmem_phone3": f"{rng.randint(1000, 9999)}",
        "orgmem_email": f"{email_id}@example.com" if rng.random() < 0.85 else None,
        "orgmem_home_tel": f"{area_code}-{rng.randint(200, 999)}-{rng.randint(1000, 9999)}" if rng.random() < 0.3 else None,
        "orgmem_fax": f"{area_code}-{rng.randint(200, 999)}-{rng.randint(1000, 9999)}" if rng.random() < 0.15 else None,
        "orgmem_sns": f"https://instagram.com/{email_id}" if rng.random() < 0.2 else None,
        "orgmem_home_addr_zipcode": home_zip,
        "orgmem_home_addr1": home_addr1,
        "orgmem_home_addr2": f"{rng.randint(101, 120)}동 {rng.randint(101, 1504)}호",
        "orgmem_area": area_code,
        "orgmem_area_work": area,
        "jobtype": jobtype,
        "orgmem_office_nm": office,
        "orgmem_position": rng.choice(OFFICE_POSITIONS),
        "orgmem_office_addr_zipcode": office_zip,
        "orgmem_office_addr1": office_addr1,
        "orgmem_office_addr2": f"{rng.randint(1, 20)}층",
        "orgmem_homepage": f"https://www.example.com/company/{idx}" if jobtype == "자영업" else None,
        "business_field": business_field,
        "topcompany": "Y" if office in TOP_COMPANIES else "N",
        "orgmem_executive": rng.choice(ULSAN_EXECUTIVES) if area == "울산" and rng.random() < 0.1 else None,
        "circles_position": rng.choice(["회장", "총무", "회원"]) if circle else None,
        "link1": f"https://www.youtube.com/watch?v=sample{idx}" if rng.random() < 0.05 else None,
        "link2": None,
        "orgmem_img": f"/uploads/members/{idx}.jpg" if rng.random() < 0.5 else None,
        "company_intro": None,
        "business_card": f"/uploads/cards/{idx}.jpg" if rng.random() < 0.3 else None,
        "company_img": None,
        "app_install": rng.choice(["Y", "Y", "N"]),
        "certification_num": None,
        "create_host": f"192.168.0.{rng.randint(2, 254)}",
        "create_id": "admin",
        "create_date": (datetime(2020, 1, 1) + timedelta(days=rng.randint(0, 1800), seconds=rng.randint(0, 86399)))
        .strftime("%Y-%m-%d %H:%M:%S"),
    }
    for column, candidates, prob in POSITION_COLUMNS:
        member[column] = rng.choice(candidates) if rng.random() < prob else None
    return member


def sample_member_from_prompt():
    """chain.py 응답 프롬프트의 예시 회원. 출력 형식 테스트용으로 고정 데이터를 넣는다."""
    return {
        "orgmem_name": "강구관", "orgmem_name_chi": "姜○○", "orgmem_lunar": "양력", "orgmem_seqNum": 12,
        "orgmem_major": "M09", "orgmem_major_txt": "국어국문학과", "orgmem_admyear": 1996, "orgmem_grdyear": 2000,
        "orgmem_class": "2000년 졸업반", "orgmem_phone1": "010", "orgmem_phone2": "1234", "orgmem_phone3": "5678",
        "orgmem_email": "kyun11@example.com", "orgmem_area": "02", "orgmem_area_work": "서울", "jobtype": "교육자",
        "orgmem_office_nm": "주식회사 신도", "orgmem_position": "이사", "business_field": "교육서비스업",
        "topcompany": "N", "app_install": "Y", "create_id": "admin", "create_date": "2020-03-02 09:00:00",
    }


def assign_unique_positions(rng, members):
    """회장처럼 한 명만 맡는 직책을 서로 다른 회원에게 하나씩 배정한다."""
    taken = set()
    for column, title, area in UNIQUE_POSITIONS:
        candidates = [i for i, m in enumerate(members[1:], start=1)
                      if i not in taken and (area is None or m["orgmem_area_work"] == area)]
        idx = rng.choice(candidates)
        members[idx][column] = title
        taken.add(idx)


def build_db(db_path, count, seed):
    rng = random.Random(seed)
    members = [sample_member_from_prompt()] + [make_member(rng, i) for i in range(1, count)]
    assign_unique_positions(rng, members)

    db_path.unlink(missing_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        for member in members:
            columns = ", ".join(member)
            placeholders = ", ".join("?" * len(member))
            conn.execute(f"INSERT INTO orgmember ({columns}) VALUES ({placeholders})", list(member.values()))
    conn.close()
    return len(members)


def main():
    parser = argparse.ArgumentParser(description="샘플 동문회 회원 DB(SQLite) 생성")
    parser.add_argument("-n", "--count", type=int, default=200, help="생성할 회원 수 (기본 200)")
    parser.add_argument("-o", "--output", type=Path, default=DEFAULT_DB_PATH, help="출력 DB 파일 경로")
    parser.add_argument("--seed", type=int, default=42, help="난수 시드 (기본 42)")
    args = parser.parse_args()

    total = build_db(args.output, args.count, args.seed)
    print(f"{args.output} 생성 완료: 회원 {total}명")


if __name__ == "__main__":
    main()
