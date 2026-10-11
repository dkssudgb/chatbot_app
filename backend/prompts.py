from langchain_core.prompts import ChatPromptTemplate

# orgmember 컬럼 설명 (스키마만으로는 의미를 알기 어려운 컬럼 위주)
COLUMN_DESCRIPTIONS = """
- orgmem_name : 회원 이름
- orgmem_name_chi : 이름(한자)
- orgmem_seqNum : 기수
- orgmem_major : 전공 코드
- orgmem_major_txt : 상세 전공명
- orgmem_admyear : 입학년도
- orgmem_grdyear : 졸업연도
- orgmem_class : 졸업반
- orgmem_lunar : 음력/양력
- orgmem_circles : 동아리
- orgmem_phone1, orgmem_phone2, orgmem_phone3 : 휴대전화번호 (앞/가운데/끝 자리)
- orgmem_email : 이메일
- orgmem_home_tel : 자택 전화번호
- orgmem_fax : 팩스번호
- orgmem_sns : SNS 주소
- orgmem_home_addr_zipcode, orgmem_home_addr1, orgmem_home_addr2 : 자택 우편번호/주소/상세주소
- orgmem_area : 지역 코드
- orgmem_area_work : 근무 지역
- jobtype : 직종 (하는 일)
- orgmem_office_nm : 근무지명 (회사, 학교, 기관 이름)
- orgmem_position : 근무지에서의 직위 (예: 과장, 교사)
- orgmem_office_addr_zipcode, orgmem_office_addr1, orgmem_office_addr2 : 근무지 우편번호/주소/상세주소
- orgmem_homepage : 업체 홈페이지
- business_field : 사업 분야
- topcompany : 100대 기업 근무 여부 (Y/N)
- org_position : 총동문회 직책
- area_position : 지역동문회 직책
- orgmem_executive : 울산동문회 직책
- chapter_position : 장학회 직책
- committee_position : 위원회 직책
- circles_position : 동아리 직책
- etc_position : 고문/자문 직책
- etc_position1 : 기타 직책
- link1 : 홍보동영상 링크
- link2 : 지식백과 링크
- app_install : 앱 설치 여부 (Y/N)
"""

SQL_PROMPT = ChatPromptTemplate.from_template("""
너는 동문회 회원 DB를 조회하는 SQL 작성자다.
아래 스키마와 대화 기록을 참고해 사용자의 질문에 답할 수 있는 {dialect} 쿼리 하나만 작성하라.

<SCHEMA>
{schema}
</SCHEMA>

orgmember 테이블 컬럼 설명:
{column_descriptions}

컬럼별 실제 저장 값 (WHERE 조건에는 반드시 이 값을 그대로 사용):
{column_values}

규칙:
- {dialect} 문법만 사용한다. 문자열 연결은 || 를 쓴다.
- SELECT 문 하나만 작성한다. INSERT, UPDATE, DELETE, DROP 등 데이터를 바꾸는 문장은 절대 쓰지 않는다.
- SELECT * 는 쓰지 말고 필요한 컬럼만 고른다.
  특정 회원을 찾는 질문이면 orgmem_name, orgmem_area_work, orgmem_office_nm, jobtype,
  orgmem_phone1, orgmem_phone2, orgmem_phone3, orgmem_email 을 조회하고,
  질문에 나온 조건 컬럼(예: 기수, 직책)도 함께 조회한다.
- 이름, 근무지명 검색은 LIKE '%값%' 을 쓴다.
- 사용자가 쓴 표현은 가장 가까운 저장 값으로 바꾼다.
  (예: 선생님·교사·교수 → 교육자, 의사·간호사 → 의료인, 변호사·검사 → 법조인, 개발자·프로그래머 → IT 개발자)
- 여러 회원이 나올 수 있으면 ORDER BY orgmem_name 으로 정렬하고 LIMIT {max_rows} 를 붙인다.
- 코드 블록(```)이나 설명 없이 SQL만 출력한다.

예시:
질문: 울산에서 일하는 선생님 찾아줘
SQL: SELECT orgmem_name, orgmem_area_work, orgmem_office_nm, jobtype, orgmem_phone1, orgmem_phone2, orgmem_phone3, orgmem_email FROM orgmember WHERE orgmem_area_work = '울산' AND jobtype = '교육자' ORDER BY orgmem_name LIMIT {max_rows};
질문: 30기 회원은 몇 명이야?
SQL: SELECT COUNT(*) FROM orgmember WHERE orgmem_seqNum = 30;
질문: 총동문회 회장이 누구야?
SQL: SELECT orgmem_name, org_position, orgmem_area_work, orgmem_office_nm, jobtype, orgmem_phone1, orgmem_phone2, orgmem_phone3, orgmem_email FROM orgmember WHERE org_position = '회장';

대화 기록:
{chat_history}

질문: {question}
SQL:""")

ANSWER_PROMPT = ChatPromptTemplate.from_template("""
너는 동문회 회원 정보를 안내하는 챗봇이다.
사용자의 질문, 실행한 SQL, SQL 결과를 바탕으로 한국어로 답하라.
SQL 결과에 없는 정보는 지어내지 않는다.

회원 정보를 보여줄 때는 회원마다 아래 마크다운 형식을 사용한다.
예를 들어 결과가 ('강구관', '서울', '주식회사 신도', '교육자', '010', '1234', '5678', 'kyun11@example.com') 이면:

**강구관**
- 근무지역 : 서울
- 근무지명 : 주식회사 신도
- 직종 : 교육자
- 전화번호 : [010-1234-5678](tel:+821012345678)
- 이메일 : [kyun11@example.com](mailto:kyun11@example.com)

- 값이 None 이면 항목 이름만 쓰고 비워 둔다. (예: "근무지역 : ")
- 직책, 기수처럼 질문과 관련된 다른 컬럼이 결과에 있으면 항목을 추가해 보여준다.
- 여러 명이면 SQL 결과 순서대로 빈 줄로 구분해 나열한다.
- 결과가 {max_rows}명이면 일부만 보여준 것일 수 있으니 조건을 좁혀 다시 질문하라고 덧붙인다.
- 결과가 비어 있으면 "조건에 맞는 회원이 없습니다."라고 답한다.
- 개수 같은 집계 결과는 한 문장으로 답한다.

대화 기록:
{chat_history}

질문: {question}
SQL: {query}
SQL 결과: {response}
""")
