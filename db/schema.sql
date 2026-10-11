-- 동문회 회원 테이블 (샘플 DB용)
-- 원본 DB에 접근할 수 없어 chain.py 프롬프트의 컬럼 설명을 바탕으로 복원함
DROP TABLE IF EXISTS orgmember;

CREATE TABLE orgmember (
    orgmem_id                  INTEGER PRIMARY KEY AUTOINCREMENT,

    -- 기본 정보
    orgmem_name                TEXT NOT NULL,  -- 회원 이름
    orgmem_name_chi            TEXT,           -- 이름(한자)
    orgmem_lunar               TEXT,           -- 음력/양력 ('음력', '양력')
    orgmem_seqNum              INTEGER,        -- 기수
    orgmem_major               TEXT,           -- 전공 코드
    orgmem_major_txt           TEXT,           -- 상세 전공명
    orgmem_admyear             INTEGER,        -- 입학년도
    orgmem_grdyear             INTEGER,        -- 졸업연도
    orgmem_class               TEXT,           -- 졸업반
    orgmem_circles             TEXT,           -- 동아리

    -- 연락처
    orgmem_phone1              TEXT,           -- 휴대전화 앞자리 (예: 010)
    orgmem_phone2              TEXT,           -- 휴대전화 가운데 자리
    orgmem_phone3              TEXT,           -- 휴대전화 끝자리
    orgmem_email               TEXT,           -- 이메일
    orgmem_home_tel            TEXT,           -- 자택 전화번호
    orgmem_fax                 TEXT,           -- 팩스번호
    orgmem_sns                 TEXT,           -- SNS 주소

    -- 자택 주소
    orgmem_home_addr_zipcode   TEXT,           -- 자택 우편번호
    orgmem_home_addr1          TEXT,           -- 자택 주소
    orgmem_home_addr2          TEXT,           -- 자택 상세주소

    -- 직장 정보
    orgmem_area                TEXT,           -- 지역 코드
    orgmem_area_work           TEXT,           -- 근무 지역 (예: 서울, 울산)
    jobtype                    TEXT,           -- 직종
    orgmem_office_nm           TEXT,           -- 근무지명
    orgmem_position            TEXT,           -- 부서 내 직위 / 동문회 직책
    orgmem_office_addr_zipcode TEXT,           -- 근무지 우편번호
    orgmem_office_addr1        TEXT,           -- 근무지 주소
    orgmem_office_addr2        TEXT,           -- 근무지 상세주소
    orgmem_homepage            TEXT,           -- 업체 홈페이지
    business_field             TEXT,           -- 사업 분야
    topcompany                 TEXT,           -- 100대 기업 여부 ('Y', 'N')

    -- 단체 내 직책
    org_position               TEXT,           -- 총동문회 직책
    area_position              TEXT,           -- 지역동문회 직책
    orgmem_executive           TEXT,           -- 울산동문회 직책
    chapter_position           TEXT,           -- 장학회 직책
    committee_position         TEXT,           -- 위원회 직책
    circles_position           TEXT,           -- 동아리 직책
    etc_position               TEXT,           -- 고문/자문 직책
    etc_position1              TEXT,           -- 기타 직책

    -- 첨부/링크
    link1                      TEXT,           -- 홍보동영상 링크
    link2                      TEXT,           -- 지식백과 링크
    orgmem_img                 TEXT,           -- 회원 이미지 경로
    company_intro              TEXT,           -- 회사소개자료 경로
    business_card              TEXT,           -- 명함 사진 경로
    company_img                TEXT,           -- 회사 이미지 경로

    -- 앱/관리
    app_install                TEXT,           -- 앱 설치 여부 ('Y', 'N')
    certification_num          TEXT,           -- iOS 승인요청 번호
    create_host                TEXT,           -- 생성 IP
    create_id                  TEXT,           -- 생성자
    create_date                TEXT            -- 생성 일시 (YYYY-MM-DD HH:MM:SS)
);

CREATE INDEX idx_orgmember_name ON orgmember (orgmem_name);
CREATE INDEX idx_orgmember_area_work ON orgmember (orgmem_area_work);
CREATE INDEX idx_orgmember_seqnum ON orgmember (orgmem_seqNum);
