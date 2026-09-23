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
| `RNDPLZ_GOOGLE_ALLOWED_SUBS` | 기존 승인 팀원의 Google subject ID 배열(JSON). 초대 등록 활성 또는 기존 DB 승인 팀원이 있으면 `[]` 허용 |
| `RNDPLZ_GOOGLE_ENROLLMENT_ENABLED` | 최초 초대 등록을 사용할 때만 문자열 `true`로 설정. 기본은 비활성 |
| `RNDPLZ_ACCOUNT_DB_PATH` | 영속 저장소 안 SQLite 파일의 절대경로 |
| `RNDPLZ_ACCOUNT_FILES_ROOT` | 같은 계정 서비스의 영속 첨부 디렉터리 절대경로 |
| `RNDPLZ_ACCOUNT_TRUSTED_STORAGE_ROOTS` | 관리자가 준비한 허용 저장 루트의 절대경로 배열(JSON) |

계정 승인은 Google의 변경되지 않는 `sub`로 관리합니다. 기존 환경변수 허용 목록과 최초 초대로 등록한 DB 승인을 사용하며, 명시적인 계정 철회는 두 승인보다 우선합니다. 이메일이나 이름이 같다는 이유로 계정을 합치거나 공개 프로필의 소유자로 지정하지 않습니다. 같은 서비스가 사용하는 저장소를 준비하며, 다른 프로젝트의 데이터베이스를 재사용하지 않습니다.

DB와 첨부 경로를 허용 루트 안에 두고 `/tmp` 같은 임시 경로는 사용하지 않습니다. 경로 검사를 통과하는 것만으로 실제 영속 볼륨이 검증되지는 않습니다. 기존 Render 설정은 임시 상태를 사용하므로 현재 구성을 그대로 두고 영구 저장이 된다고 안내해서는 안 됩니다. 이 변경은 신규 유료 리소스를 생성하거나 기존 서비스 요금제를 바꾸지 않습니다.

## 처음 사용하는 팀원 등록

먼저 OAuth와 영속 저장소를 설정합니다. `RNDPLZ_GOOGLE_ENROLLMENT_ENABLED=true`로 초대 등록을 명시적으로 켜면 `RNDPLZ_GOOGLE_ALLOWED_SUBS=[]` 상태에서도 최초 초대를 발급할 수 있습니다. 무제한 공개 가입은 열리지 않습니다. 팀원이 자신의 `sub`를 미리 알아내 제공할 필요는 없습니다.
최초 승인자가 0명인 상태에서는 `RNDPLZ_GOOGLE_ENROLLMENT_ENABLED=true`여도 일반 Google 로그인 시작이 거절되므로, `https://rndplz.onrender.com/auth/google/enroll`의 초대입력 화면에서 시작합니다.

가입 뒤 신규 초대를 닫으려면 이 옵션을 `false`로 바꿉니다. `RNDPLZ_GOOGLE_ALLOWED_SUBS=[]`를 유지해도 기존에 활성 승인된 DB 팀원은 로그인할 수 있습니다. 아직 승인된 팀원이 없는 초기 상태에서 빈 목록만으로 일반 로그인을 열지는 않습니다.

운영자는 이 서비스의 서버 환경과 같은 계정 DB를 사용하는 비공개 터미널에서 다음 명령을 실행합니다. 기본 유효시간은 600초이며 `--ttl`은 60~3600초 범위입니다.

```text
python -m rndplz.account_admin issue-invitation --ttl 600 --person-id LOCAL-JINHO
```

`--person-id`는 초대받는 팀원이 공개 명단의 어느 인물인지(예: `LOCAL-JINHO`)를 지정하며, 가입이 끝나면 그 계정에 인물이 묶여 제안 메일 수신 주소로 계정 이메일을 씁니다. 한 인물은 한 계정에만 묶이며 `bind-person --account-id <id> --person-id <person>`으로 나중에 바꾸거나 `list-accounts`로 확인할 수 있습니다.

발급 결과 JSON의 원문 초대 토큰은 stdout으로 한 번만 반환됩니다. DB에는 해시만 저장됩니다. 터미널 출력의 수집·녹화·파일 리디렉션을 사용하지 말고, 운영자가 해당 팀원에게 개별 전달합니다. 토큰을 보고서·로그·Git·공유 화면에 남기거나 URL에 넣지 않습니다. 초대 관리용 ID와 비밀 토큰을 구분합니다.

팀원은 `https://rndplz.onrender.com/auth/google/enroll`을 열고 받은 초대 코드를 입력한 뒤 정상 Google 로그인으로 진행합니다. 이 주소는 초대 토큰이 들어 있지 않은 고정 입력 화면입니다. 서버는 초대를 하나의 로그인 흐름에 묶고 Google 서명·issuer·audience·state·nonce·PKCE를 검증한 뒤에만 계정을 승인합니다. 이메일이나 이름으로 기존 연구자 프로필을 연결하지 않습니다.

초대는 최초 로그인 흐름에 연결된 뒤 다른 흐름에서 재사용할 수 없습니다. 사용자가 취소했거나 Google 교환·검증이 실패했거나 흐름이 만료되면 새 초대를 발급해야 합니다. 실패한 시도는 계정 승인 성공으로 취급하지 않습니다.

관리자는 발급 때 받은 초대 ID로 다음 읽기 명령을 사용해 등록 상태와 연결된 계정 ID를 확인할 수 있습니다. 원문 초대 토큰·Google sub·이메일·세션을 다시 출력하는 명령은 아닙니다.

```text
python -m rndplz.account_admin invitation-status --id <invitation-id>
```

초대나 계정을 철회할 때는 각 관리용 ID를 사용합니다. 아래 자리표시자는 실제 32자리 16진수 ID로 바꿉니다. 초대 토큰을 `--id`에 넣지 않습니다.

```text
python -m rndplz.account_admin revoke-invitation --id <invitation-id>
python -m rndplz.account_admin revoke-account --id <account-id>
```

초대 철회는 해당 초대를 통한 가입을 막습니다. 이미 가입한 계정의 승인을 철회하려면 계정 철회를 사용합니다. 계정 철회는 기존 환경변수·DB 승인보다 우선하고 해당 계정의 서비스 접근과 후속 쓰기를 차단합니다. Google 계정 자체를 삭제하거나 Google 권한을 철회하지 않으며, 보관 프로필을 삭제하는 명령도 아닙니다.

## 연결 후 확인

승인한 계정 A로 로그인해 프로필을 저장하고 로그아웃합니다. 다시 로그인해 값과 변경 이력을 확인한 뒤, 계정 B가 A의 자료를 읽거나 고칠 수 없는지 확인합니다. 새 앱 인스턴스와 실제 재배포 후에도 A의 값이 유지되는지 확인해야 운영 보존을 검증할 수 있습니다. 첨부 파일의 보존은 DB 기록과 별도로 확인합니다.

로그아웃은 이 서비스의 세션을 끝냅니다. Google 계정 자체의 로그아웃이나 Google 권한 철회는 수행하지 않습니다. 로그인 전 방문자 자료의 이관은 이번 기능에 포함하지 않습니다.

운영 요청 로그에는 OAuth callback의 query string과 쿠키, 인증 코드, ID/access token을 남기지 않습니다. 현재 배포의 Gunicorn access log는 꺼져 있습니다. HTTPS와 동일 출처의 기존 POST Origin/CSRF 검사를 유지합니다.

구현 기준: [Google OpenID Connect](https://developers.google.com/identity/openid-connect/openid-connect).
