# 제안 메일 발송 (선택 기능)

"시연 보냄" 상태로 저장한 제안을 SMTP로 실제 수신자에게 보냅니다. 서버 환경변수로만 켜지며, 설정이 없으면 기존처럼 제안함 기록만 남깁니다.

| 환경변수 | 값 |
|---|---|
| `RNDPLZ_MAIL_USERNAME` | 보내는 계정(Gmail 주소). `RNDPLZ_MAIL_FROM`이 없으면 발신 주소로도 사용 |
| `RNDPLZ_MAIL_PASSWORD` | Gmail **앱 비밀번호**(2단계 인증 계정에서 발급). 일반 비밀번호는 동작하지 않음 |
| `RNDPLZ_MAIL_RECIPIENTS_FILE` | 저장소 밖 JSON 파일 경로. `{"LOCAL-XXXX": "name@example.com", ...}` 형태로 person id → 주소 |
| `RNDPLZ_MAIL_SMTP_HOST` / `RNDPLZ_MAIL_SMTP_PORT` | 기본 `smtp.gmail.com` / `587` (STARTTLS) |
| `RNDPLZ_MAIL_COPY_TO` | 선택. 보낸 사람 사본(Cc) 주소 |
| `RNDPLZ_MAIL_SUBJECT_PREFIX` | 선택. 기본 `[수소문]` |

동작:

- `POST /api/proposals`에서 `state=sent`일 때만 발송합니다. 초안(`draft`)은 보내지 않습니다.
- 수신자 주소가 파일에 없거나 형식이 틀리면 `skipped_no_address`로 기록하고 제안은 그대로 저장됩니다.
- 발송 실패도 제안을 지우지 않고 `delivery.status=failed`와 오류 종류만 기록합니다.
- 같은 저장 식별자(idempotency key)로 다시 저장하면 이전 제안을 돌려주고 메일을 다시 보내지 않습니다.
- 제안 기록의 `delivery`에는 가려진 주소(`m***@example.com`)와 시각만 남습니다. 비밀번호·전체 주소는 응답과 로그에 나오지 않습니다.
- `/api/chat/bootstrap`의 `mail_delivery.enabled`로 화면 문구가 바뀌고, 보낸 뒤 발송 건수/주소 미등록/실패 건수를 알립니다.

수신자 주소와 앱 비밀번호는 공개 저장소에 넣지 않습니다. 이 PC 호스팅에서는 `hosting/secrets.ps1`과 `hosting/recipients.json`에 둡니다.
