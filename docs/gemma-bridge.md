# 공개 서비스의 로컬 Gemma 연결

공개 Render 서비스가 받은 대화 요청을 운영자 PC가 HTTPS로 가져와, 루프백 Ollama의 gemma4:e4b로 처리하고 응답을 돌려준다. PC에 외부 접속 포트를 열지 않는다. PC와 Ollama 및 연결기가 실행 중이어야 한다.

## 설정
- Render: RNDPLZ_PUBLIC_MODEL=bridge, RNDPLZ_BRIDGE_TOKEN=별도 생성한 연결 비밀 값.
- PC: out/gemma-bridge/config.json에 service_url, model, token. out은 Git 제외.
- 실행: python -u -m rndplz.gemma_bridge --config "out/gemma-bridge/config.json"
- 공개 화면: gemma4:e4b · 운영자 PC. 연결이 없으면 기록 탐색 안내가 기본이다.
- Astra 키와 모델 설정은 보존하되 bridge 모드에서는 호출하지 않는다.

## 범위와 검증
- 시연용 동시 작업 2개, 작업 대기 최대 150초, 응답 길이 24,000자.
- 서버는 1 worker / 8 threads 구성이다. 대화 슬롯은 4개로 제한하여 연결기 요청을 처리할 여유를 남긴다.
- 작업별 임의 lease와 순번으로 응답이 섞이거나 중복되지 않도록 검사한다. 인증 없는 작업 접근은 거절한다.
- 키·대화 내용은 연결기 로그에 쓰지 않는다. 공개 서버의 기존 방문자별 대화 저장은 그대로 적용한다.
- 2026-09-18: 어댑터·공개 서비스·연결기 검사 17개 통과. 로컬 Gemma 응답 '연결 성공' 확인.
- Astra 실제 요청은 429 credit_balance_exhausted로 실패했다. API 크레딧 보충 전 재시도하지 않는다.
