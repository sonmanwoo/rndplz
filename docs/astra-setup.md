# 공개 서비스 Astra 연결

1. https://platform.openai.com/api-keys 에서 프로젝트 API 키를 발급한다.
2. Render rndplz 서비스 Environment에서 OPENAI_API_KEY를 비밀 값으로 등록한다.
3. RNDPLZ_OPENAI_MODEL=gpt-6-astra를 등록한다. 생략해도 OpenAI 기본값은 gpt-6-astra다.
4. Save and deploy 후 /api/chat/models에서 모델 이름을 확인하고 짧은 대화로 실제 응답을 확인한다.

키는 브라우저 코드, Git, 채팅, 로그에 넣지 않는다. 계정의 API 사용 가능 여부와 결제 설정은 운영자가 확인한다.

## 구현과 검증
- OpenAI API 키가 있으면 로컬 모델보다 OpenAI를 기본 선택한다. 명시한 다른 OpenAI 모델 ID는 존중한다.
- Astra 요청: Chat Completions, streaming, reasoning_effort=low, service_tier=default, max_completion_tokens=1800.
- API 키가 없으면 공개 서비스는 AI 미연결 안내를 표시한다.
- 2026-09-18: verify_chat + verify_public 14개 통과. HTTP 모의 응답 계약 검증이며 실제 Astra 응답은 키 등록 대기 중이다.
- API 호출은 제공사별 서버 프로세스당 20회로 제한된다. 재시작마다 초기화되는 시연 한도이며 월 비용 한도는 아니다.

공식 근거: https://developers.openai.com/api/docs/models/gpt-6-astra · https://developers.openai.com/api/docs/quickstart · https://render.com/docs/configure-environment-variables
