from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_community.utilities import SQLDatabase
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnablePassthrough

def init_database(db_uri: str) -> SQLDatabase:
    # 예: sqlite:///../db/members.db, mysql+mysqlconnector://user:pw@host:3306/db
    return SQLDatabase.from_uri(db_uri)

def get_sql_chain(db):
    template = """
    You are a manager at a '동문회'. You are interacting with a user who is asking you questions about the assosiation's member database.
    Based on the table schema below, write a SQL query that would answer the user's question. Take the conversation history into account.
    
    Below is what some columns in the orgmember table mean.
    - orgmem_name : 회원의 이름, Member's name
    - orgmem_area_work : 근무 지역, work area
    - jobtype : 직종, 직업, 일, 하는 일, type of occupation, occupational category
    - orgmem_phone1, orgmem_phone2, orgmem_phone3 : 휴대전화번호, mobile phone number, phone number, contact information
    - orgmem_office_nm : 근무지명, place of work
    - orgmem_email : 이메일, e-mail, contact 
    - orgmem_seqNum : 기수 
    - orgmem_major : 전공 코드
    - orgmem_lunar : 음력/양력
    - orgmem_admyear : 입학년도
    - orgmem_grdyear : 졸업연도
    - app_install : 앱 설치 여부
    - certification_num : IOS 승인요청 번호
    - orgmem_homepage : 업체 홈페이지
    - orgmem_sns : sns 주소
    - business_field : 사업 분야
    - link1 : 홍보동영상 link
    - link2 : 지식백과 link
    - topcompany : 100대 기업
    - orgmem_position : 동문회 직책
    - chapter_position : 장학회 직책
    - committee_position : 위원회 직책
    - orgmem_major_txt : 상세 전공명
    - orgmem_name_chi : 이름_중국어
    - orgmem_home_addr_zipcode : 자택 우편번호
    - orgmem_home_addr1 : 자택 주소
    - orgmem_home_addr2 : 자택 상세주소
    - orgmem_home_tel : 자택전화번호
    - orgmem_class : 졸업반
    - orgmem_position : 부서 내 직위
    - orgmem_office_addr_zipcode : 근무지 우편번호
    - orgmem_office_addr1 : 근무지 주소
    - orgmem_office_addr2 : 근무지 상세주소
    - orgmem_img : 직원 이미지
    - company_intro : 회사소개자료
    - business_card : 명함사진
    - company_img : 회사 이미지
    - create_host : 생성 ip
    - create_id : 생성자
    - create_date : 생성날짜
    - orgmem_area : 지역코드
    - orgmem_fax : 팩스번호
    - etc_position : 고문/자문 직책
    - etc_position1 : 기타 직책
    - area_position : 지역동문회 직책
    - orgmem_circles : 동아리
    - orgmem_executive : 울산동문회 직책
    - org_position : 총동문회 직책
    - circles_position : 동아리 직책
    
    <SCHEMA>{schema}<SCHEMA>
    
    Conversation History: {chat_history}
    
    Write only the SQL query and nothing else. Do not wrap the SQL query in any other text, not even backticks.
    
    For example:
    Question: 서울에 사는 사람을 찾아줘.
    SQL Query: SELECT * FROM employee WHERE City='서울';
    Question: 회원 수가 총 몇명이야?
    SQL Query: SELECT COUNT(*) FROM employee;
    
    Your turn:
    
    Question: {question}
    SQL Query: 
    """
    
    prompt = ChatPromptTemplate.from_template(template)
    
    llm = ChatGoogleGenerativeAI(model="gemini-1.5-pro", temperature=0, max_output_tokens=600)
    
    def get_schema(_):
        return db.get_table_info()
    
    return (
        RunnablePassthrough.assign(schema=get_schema)
        | prompt
        | llm.bind(stop=["\nSQLResult:"])
        | StrOutputParser()
    )

def get_response(user_query: str, db:SQLDatabase, chat_history: list):
    sql_chain = get_sql_chain(db)
    query = sql_chain.invoke({
        "question": user_query,
        "chat_history": chat_history
    })
    
    if not query: # 쿼리가 제대로 생성되었는지 확인 
        return "유효한 쿼리를 생성할 수 없습니다."
    
    # 데이터베이스에서 쿼리 실행
    response = db.run(query)
    
    template = """
    You are a manager at a '동문회'. You are interacting with a user who is asking you questions about the assosiation's member database.
    Based on the table schema below, question, sql query and sql response, write a natural language response.
    
    If a user wants to find out about a particular member, output the user information in the following way. You need to access the orgmember table.
    For example:
    If the membership information is as below,
        orgmem_name = 강구관 
        orgmem_area_work = 서울
        jobtype = 교육자
        orgmem_phone1 = 010
        orgmem_phone2 = 1234
        orgmem_phone3 = 5678
        orgmem_office_nm = 주식회사 신도
        orgmem_email = kyun11@hanmail.net
    
    Please apply the markdown language format and print it out as below:
    
    **강구관**        
    - 근무지역 : 서울        
    - 근무지명 : 주식회사 신도        
    - 직종 : 교육자        
    - 전화번호 : [010-1234-5678](tel:+821012345678)        
    - 이메일 : [kyun11@hanmail.net](mailto:kyun11@hanmail.net)        
    
    If any information is null, output it as blank (for example, "근무지역 : ").
    If there are multiple people, please list them in ascending order based on their names. Separate them into lines and print them out.
    
    <SCHEMA>{schema}<SCHEMA>
    
    Conversation History: {chat_history}
    SQL Query: <SQL>{query}<SQL>
    User question: {question}
    SQL Response: {response}"""
    
    prompt = ChatPromptTemplate.from_template(template)
    
    llm = ChatGoogleGenerativeAI(model="gemini-1.5-pro", temperature=0, max_output_tokens=600, response_format="markdown")
    
    # chain = (
    #     RunnablePassthrough.assign(query=sql_chain).assign(
    #         schema=lambda _: db.get_table_info(),
    #         response=lambda vars: db.run(vars["query"]),
    #     )
    #     | prompt
    #     | llm
    #     | StrOutputParser()
    # )
    
    chain = (prompt | llm | StrOutputParser())
    
    return chain.invoke({
        "schema": db.get_table_info(), 
        "query": query, 
        "question": user_query,
        "response": response, 
        "chat_history": chat_history
    })
