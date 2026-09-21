# Google 계정과 비공개 프로필 설정

Google 계정으로 로그인한 팀원은 자신의 프로필을 저장하고 다시 로그인해 열 수 있습니다. 프로필은 계정별로 분리되며 공개 인물 목록에 자동 게시되지 않습니다. 방문자 프로필과 대화는 계정으로 자동 이전하지 않습니다.

현재 공개 서비스에는 Google 웹 OAuth 클라이언트와 재배포 후에도 유지되는 저장소가 연결되어 있지 않습니다. 설정 전에는 로그인 버튼 대신 준비 중 안내를 표시합니다. 합성 서명과 로컬 데이터베이스 검사는 실제 Google 로그인이나 운영 저장소의 내구성 검증을 대신하지 않습니다.

## 연결할 값

Google 웹 애플리케이션 클라이언트에 리디렉션 URI를 정확히 등록하고 다음 값을 서버 환경변수로 설정합니다. 비밀값은 소스코드, Git, 브라우저 코드 또는 대화에 넣지 않습니다.

| 환경변수 | 값 |
|---|---|
| `RNDPLZ_GOOGLE_CLIENT_ID` | 해당 웹 OAuth 클라이언트 ID |
| `RNDPLZ_GOOGLE_CLIENT_SECRET` | 서버 전용 클라이언트 secret |
| `RNDPLZ_GOOGLE_REDIRECT_URI` | `https://rndplz.onrender.com/auth/google/callback` |
| `RNDPLZ_PUBLIC_ORIGIN` | `https://rndplz.onrender.com` |
| `RNDPLZ_GOOGLE_ALLOWED_SUBS` | 승인한 팀원의 Google subject ID 문자열 배열(JSON) |
| `RNDPLZ_ACCOUNT_DB_PATH` | 영속 저장소 안 SQLite 파일의 절대경로 |
| `RNDPLZ_ACCOUNT_FILES_ROOT` | 같은 계정 서비스의 영속 첨부 디렉터리 절대경로 |
| `RNDPLZ_ACCOUNT_TRUSTED_STORAGE_ROOTS` | 관리자가 준비한 허용 저장 루트의 절대경로 배열(JSON) |

허용 목록은 Google의 변경되지 않는 `sub`로 관리합니다. 이메일이나 이름이 같다는 이유로 계정을 합치거나 공개 프로필의 소유자로 지정하지 않습니다. 같은 서비스가 사용하는 저장소를 준비하며, 다른 프로젝트의 데이터베이스를 재사용하지 않습니다.

DB와 첨부 경로를 허용 루트 안에 두고 `/tmp` 같은 임시 경로는 사용하지 않습니다. 경로 검사를 통과하는 것만으로 실제 영속 볼륨이 검증되지는 않습니다. 기존 Render 설정은 임시 상태를 사용하므로 현재 구성을 그대로 두고 영구 저장이 된다고 안내해서는 안 됩니다. 이 변경은 신규 유료 리소스를 생성하거나 기존 서비스 요금제를 바꾸지 않습니다.

## 연결 후 확인

승인한 계정 A로 로그인해 프로필을 저장하고 로그아웃합니다. 다시 로그인해 값과 변경 이력을 확인한 뒤, 계정 B가 A의 자료를 읽거나 고칠 수 없는지 확인합니다. 새 앱 인스턴스와 실제 재배포 후에도 A의 값이 유지되는지 확인해야 운영 보존을 검증할 수 있습니다. 첨부 파일의 보존은 DB 기록과 별도로 확인합니다.

로그아웃은 이 서비스의 세션을 끝냅니다. Google 계정 자체의 로그아웃이나 Google 권한 철회는 수행하지 않습니다. 로그인 전 방문자 자료의 이관은 이번 기능에 포함하지 않습니다.

운영 요청 로그에는 OAuth callback의 query string과 쿠키, 인증 코드, ID/access token을 남기지 않습니다. 현재 배포의 Gunicorn access log는 꺼져 있습니다. HTTPS와 동일 출처의 기존 POST Origin/CSRF 검사를 유지합니다.

구현 기준: [Google OpenID Connect](https://developers.google.com/identity/openid-connect/openid-connect).
