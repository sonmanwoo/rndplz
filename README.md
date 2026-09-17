# 수소문 · Research, together

질문을 구체화하고, 논문·경력 기록을 근거로 연결할 사람을 찾는 해커톤 서비스입니다.
이 저장소는 배포용 현재 소스 스냅샷입니다. 개발 PC의 대화·첨부·키·과거 Git 이력은 포함하지 않습니다.

## 실행
Python 3.10 이상에서 `pip install -r requirements.txt` 후 Linux에서는
`gunicorn -c gunicorn.conf.py rndplz.public_web:application`을 실행합니다.
Render에서는 이 저장소를 연결한 다음 `render.yaml` Blueprint로 배포할 수 있습니다.

## 공개 범위와 기능
기본 공개 자료는 공개 논문 기반 프로필입니다. 개인 경력은 공개 승인이 있는 배포에만 포함합니다.
방문자별 대화·첨부·시연 제안은 분리됩니다. 제안은 실제 외부인에게 발송되지 않습니다.
API 연결 전에는 “AI 미연결”을 표시하고 기록 탐색 안내 및 근거 검색을 제공합니다.
실제 AI 대화는 서버에 OPENAI_API_KEY + RNDPLZ_OPENAI_MODEL 또는
ANTHROPIC_API_KEY + RNDPLZ_CLAUDE_MODEL을 설정해야 합니다.

## 검증과 운영
`python -m unittest rndplz.verify_public` / `node rndplz/verify_sphere.cjs`
공개 입구는 WSGI이며 로컬 시연 서버를 인터넷에 직접 노출하지 않습니다.
무료 Render의 파일은 재시작 시 사라질 수 있습니다. 장기 운영에는 별도 영속 저장소가 필요합니다.

사진·출처·AI 생성 일러스트의 구분은 각 카드에서 확인할 수 있습니다.
