# 원/달러 환율 사이트

오늘 환율과 최근 3개월 추이를 그래프 + 표로 보여주는 웹 서버입니다.
폰에서도 그대로 보이도록 반응형으로 만들었습니다.

================================================
[방법 1] 클라우드에 올려서 폰 어디서나 보기 (추천)
================================================
PC를 안 켜도, LTE로도, 주소만 있으면 폰에서 항상 보입니다.
Render.com 무료 플랜으로 합니다. (신용카드 불필요)

준비물: GitHub 계정 (없으면 github.com 에서 무료 가입)

--- 1단계. GitHub에 코드 올리기 (가장 쉬운 웹 방식) ---
1) github.com 로그인 → 오른쪽 위 '+' → New repository
2) 이름 아무거나(예: krw-usd-rate) → Create repository
3) 만들어진 페이지에서 'uploading an existing file' 링크 클릭
4) 이 폴더 안의 모든 파일/폴더를 드래그해서 업로드
   (app.py, requirements.txt, Procfile, render.yaml, runtime.txt,
    templates 폴더, static 폴더 전부)
5) 아래 'Commit changes' 클릭

--- 2단계. Render에 연결 ---
1) render.com 접속 → 'Get Started' → GitHub 계정으로 로그인
2) 대시보드에서 'New +' → 'Web Service'
3) 방금 만든 GitHub 저장소 선택 → Connect
4) 설정이 자동으로 잡힘 (render.yaml 덕분):
   - Build Command: pip install -r requirements.txt
   - Start Command: gunicorn app:app
   - Instance Type: Free
   확인만 하고 'Create Web Service' 클릭
5) 몇 분 기다리면 'Live' 상태가 되고
   https://krw-usd-rate-xxxx.onrender.com 같은 주소가 생김
6) 그 주소를 폰 브라우저에 입력 → 끝!
   폰 홈 화면에 추가하면 앱처럼 쓸 수 있음.

* 무료 플랜은 15분간 접속이 없으면 잠들고, 다시 열 때
  첫 로딩이 30초~1분 걸릴 수 있습니다(그 다음부턴 빠름). 정상입니다.


================================================
[방법 2] 내 PC를 서버로 켜서 같은 와이파이의 폰에서 보기
================================================
1) pip install -r requirements.txt   (최초 1회)
2) python app.py
3) 화면에 뜨는 http://192.168.x.x:5000 주소를
   같은 와이파이의 폰 브라우저에 입력
   (PC 방화벽에서 Python 허용 필요, PC가 켜져 있어야 함)


## 구성 파일
- app.py            : Flask 서버 + 환율 수집/캐시(30분)
- templates/index.html : 화면 (Chart.js 그래프 + 표)
- static/style.css  : 모바일 스타일
- requirements.txt  : 필요한 라이브러리
- Procfile          : Render 실행 명령
- render.yaml       : Render 자동 설정
- runtime.txt       : 파이썬 버전 지정

## 데이터 출처
- 1차: Frankfurter (유럽중앙은행 ECB 고시환율, 영업일 기준)
- 2차(백업): Yahoo Finance (KRW=X)
- 화면 5분마다 자동 갱신, 서버는 30분 캐시
