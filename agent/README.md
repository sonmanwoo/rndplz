# 수소문 에이전트 도구 연결

이 PC의 공개 말뭉치를 읽어 사람·근거를 찾고 의뢰 초안을 만듭니다. 도구 함수 한 벌을 명령행과 MCP 서버가 함께 사용합니다. 모델 호출, 외부 네트워크 연결, 제안함·프로필·상태 저장, 발송은 하지 않습니다. 원격 API와 키 인증은 이번 구현 범위에 없습니다.

## 실행 준비

Python 3.10 이상이 있는 기존 프로젝트 환경을 사용합니다. MCP 구현은 표준 라이브러리만 사용하며 별도의 `mcp` 패키지를 설치하지 않습니다. 아래 PowerShell 명령의 작업 폴더는 `rndplz/`와 `pack/`이 있는 저장소 루트입니다.

```powershell
Set-Location -LiteralPath 'D:/0_Agent AI/24_RnDplz/hosting/app'
python -m rndplz.agent find-people "화학공정의 모델 예측 제어를 자문할 사람" --limit 5
python -m rndplz.agent capabilities --text
```

같은 저장소 말뭉치와 공개 범위 설정으로 만든 시작 시점 스냅샷에 웹과 같은 공개 투영·카드 규칙을 적용합니다. 계정 DB나 상태 저장소는 읽지 않으므로, 계정 기능을 켠 운영 웹에서 저장한 개인 카드 편집본과 실시간으로 동기화하지 않습니다.

`RNDPLZ_PUBLISH_PERSONAL`과 `RNDPLZ_PUBLIC_PERSON_IDS`는 웹 운영자가 승인한 설정만 그대로 전달합니다. 후보를 늘리려고 공개 설정을 바꾸지 않습니다. 공개 설정·말뭉치·역량 파일을 바꿨다면 캐시에 최신 자료를 반영하도록 MCP 프로세스를 다시 시작합니다.

## 명령행과 MCP 도구

기본 출력은 UTF-8 JSON이며 한글을 그대로 출력합니다. `--text`를 붙이면 한국어 요약을 출력합니다. 입력 오류는 JSON 오류와 0이 아닌 종료 코드로 구분합니다. 아래 `PERSON_ID`, `RECORD_ID`, `CAPABILITY_ID`는 각각 앞선 도구 응답에서 얻은 실제 ID로 바꿉니다.

| 명령행 | MCP 도구와 인자 | 결과 |
|---|---|---|
| `find-people "질문" --limit 5` | `find_people(query, limit=5)` | 사람, 추천 설명, 연결 근거 또는 결과 없음·모호함 안내 |
| `person PERSON_ID` | `get_person(person_id)` | 공개 인물 카드와 근거 |
| `record RECORD_ID` | `get_record(record_id)` | 근거 기록 상세 |
| `capabilities` | `list_capabilities()` | 연구 맵 순서의 역량과 사람 수 |
| `capability CAPABILITY_ID` | `people_for_capability(capability_id)` | 역량에 연결된 사람과 근거 수 |
| `draft --to PERSON_ID --need "필요한 도움"` | `draft_request(person_ids, need, requester_note='')` | 제목·본문과 사람에게 넘길 안내 |

명령행의 공통 접두사는 `python -m rndplz.agent`입니다. 초안 대상이 여러 명이면 `--to PERSON_ID_1,PERSON_ID_2`로 지정합니다. 모든 도구 응답에는 `schema_version`, `pool_version`, `generated_at`, 공개 근거와 미확인 사항에 관한 고지가 포함됩니다. 내부 추천 점수는 제공하지 않습니다.

추천은 현재 연락 가능성이나 협업 의사를 확인한 결과가 아닙니다. 사람을 제시할 때 연결된 기록의 제목·연도·근거 종류·출처를 함께 제시합니다. 초안은 사람이 수소문 화면에서 확인·발송하도록 넘깁니다.

## Claude Code 등록 예시

다음은 **Claude가 사용자 확인 후 실행할 예시**입니다. 이번 구현에서는 실제 MCP 등록이나 사용자 설정 파일 수정을 수행하지 않습니다.

먼저 위 `Set-Location` 명령으로 저장소 루트에 들어간 다음 등록합니다.

```powershell
claude mcp add susomun -- python -m rndplz.agent mcp
```

이 간단한 등록 예시는 Claude Code도 같은 저장소 루트에서 시작하는 방식입니다. 다른 작업 폴더에서 쓸 경우에는 Python 실행 파일과 저장소 경로를 고정한 실행 명령을 등록할 수 있습니다. 아래 역시 등록 예시이며, 기본 등록과 둘 중 하나를 선택합니다.

```powershell
claude mcp add susomun -- C:/Python311/python.exe -c "import os,runpy,sys; os.chdir('D:/0_Agent AI/24_RnDplz/hosting/app'); sys.argv=['rndplz.agent','mcp']; runpy.run_module('rndplz.agent',run_name='__main__')"
```

Python 경로는 이 PC에서 확인한 실행 파일 예시입니다. 다른 환경에서는 해당 프로젝트를 실행할 Python 경로로 바꿉니다. Claude Code가 MCP 프로세스를 실행한 후 도구 6개를 인식하는지는 등록 단계에서 별도로 확인합니다.

기본 등록은 해당 프로젝트의 `local` 범위입니다. 위 대체 명령은 수소문 실행 폴더를 고정하는 용도이며, 다른 프로젝트에서 쓰려면 사용할 프로젝트 폴더에서 등록합니다. 여러 프로젝트에 공통으로 등록하려면 Claude가 사용자 확인 후 `claude mcp add --scope user susomun -- ...` 형식을 선택합니다.

## Codex 등록 예시

Claude가 사용자 확인 후 `~/.codex/config.toml`에 추가할 내용입니다. Windows에서 기본 위치는 `%USERPROFILE%/.codex/config.toml`입니다. 이미 `mcp_servers.susomun` 항목이 있다면 중복 추가하지 말고 기존 항목을 검토합니다.

```toml
[mcp_servers.susomun]
command = "C:/Python311/python.exe"
args = ["-m", "rndplz.agent", "mcp"]
cwd = "D:/0_Agent AI/24_RnDplz/hosting/app"
```

`cwd`는 말뭉치와 `rndplz` 모듈이 있는 저장소 루트이고, `command`는 사용할 Python 실행 파일입니다. 이 예시는 공개 범위를 넓히는 환경변수를 추가하지 않습니다. 웹과 별도로 실행되는 클라이언트에서 승인된 공개 설정을 전달해야 한다면 운영자가 그 값을 확인합니다.

## MCP 통신과 Claude 검증 순서

`python -m rndplz.agent mcp`는 표준 입출력으로 한 줄씩 JSON-RPC 2.0 메시지를 주고받습니다. 표준 출력에는 프로토콜 메시지만 나오며 로그는 표준 오류를 사용합니다. `initialize`에서 버전을 협상하고 `notifications/initialized` 이후 `tools/list`, `tools/call`을 사용합니다. 서버 이름은 `susomun`이고 도구 6개 모두 `readOnlyHint=true`입니다. `tools/call` 결과는 JSON 문자열을 담은 `content`와 객체인 `structuredContent`를 함께 제공합니다.

1. [구현 보고서](../agent-codex-impl.md)의 시험 결과와 실제 출력 예시를 검토합니다.
2. 사용자 확인 후 Claude Code 또는 Codex에 등록하고 도구 6개가 보이는지 확인합니다.
3. `find_people` → `get_person` → `get_record`를 호출해 후보·공개 카드·근거가 이어지는지 확인합니다.
4. 필요한 경우 `draft_request`를 호출해 초안을 사람이 검토할 수 있게 전달합니다. 에이전트는 보내기나 제안함 저장을 대행하지 않습니다.
5. [스킬 안내서](skills/susomun/SKILL.md)를 검토한 뒤 Claude가 설치합니다. 이 저장소에 파일을 추가한 것만으로 클라이언트 설치가 완료되지는 않습니다.

연결 예시는 로컬 설치 자료와 구현 계약을 기준으로 작성했습니다. 외부 네트워크를 사용한 최신 문서 조회, 실제 클라이언트 등록·실연은 이번 구현 검증에 포함하지 않습니다.
