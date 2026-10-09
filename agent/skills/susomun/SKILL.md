---
name: susomun
description: 사내 연구 문제를 함께 풀 사람·근거를 찾을 때 수소문의 공개 자료를 검색하고, 필요하면 의뢰 초안을 준비한다.
---

# 수소문

연구 문제를 설명한 사용자에게 공개 근거로 연결되는 사람을 찾고, 어떤 기록이 그 연결을 뒷받침하는지 확인한다. 도구는 이 PC에서 결정적으로 실행되며 모델·외부 네트워크 호출이나 발송·저장을 수행하지 않는다.

자료는 같은 저장소 말뭉치·공개 설정으로 만든 시작 시점 스냅샷이며 웹과 공개 투영·카드 규칙을 공유한다. 계정 DB·상태 저장소를 읽지 않으므로 운영 웹에 저장된 개인 카드 편집본과 실시간으로 동기화하지 않는다. 공개 설정·말뭉치·역량 파일이 바뀌면 최신 자료를 쓰기 위해 MCP 프로세스를 다시 시작해야 한다.

## 도구 선택과 순서

MCP가 연결되어 있으면 아래 이름의 도구를 사용한다. 연결되어 있지 않으면 `rndplz/`와 `pack/`이 있는 저장소 루트에서 명령행을 실행한다. 저장소 위치를 모르면 수소문이 설치된 경로를 확인한다. 등록이나 설치가 필요하면 저장소의 `agent/README.md`를 참고하되, 사용자가 요청한 검색을 위해 임의로 클라이언트 설정을 바꾸지 않는다.

| 목적 | MCP 도구 | 명령행 (`python -m rndplz.agent` 뒤) |
|---|---|---|
| 문제로 사람 찾기 | `find_people(query, limit=5)` | `find-people "질문" --limit 5` |
| 공개 카드 확인 | `get_person(person_id)` | `person PERSON_ID` |
| 근거 상세 확인 | `get_record(record_id)` | `record RECORD_ID` |
| 역량 목록 탐색 | `list_capabilities()` | `capabilities` |
| 역량별 사람 탐색 | `people_for_capability(capability_id)` | `capability CAPABILITY_ID` |
| 의뢰 초안 준비 | `draft_request(person_ids, need, requester_note='')` | `draft --to PERSON_ID --need "필요한 도움"` |

1. 사용자가 말한 문제·조건·필요한 도움을 보존해 `find_people`로 찾는다. 역량에서 출발하면 `list_capabilities`의 실제 ID를 골라 `people_for_capability`로 탐색한다.
2. 선택한 후보의 `get_person`과 연결된 기록의 `get_record`를 읽는다. 후보·기록·역량 ID는 반환값에서 가져오며 추측해 만들지 않는다.
3. 결과가 없거나 모호하면 반환된 안내와 자료의 한계를 알린다. 필요한 조건을 사용자에게 확인하고 질의를 구체화한다. 근거 없는 후보를 채우지 않는다.
4. 의뢰 초안이 필요하면 확인된 사람 ID와 사용자의 필요를 `draft_request`에 전달한다. 여러 명은 MCP의 `person_ids` 배열 또는 명령행 `--to ID_1,ID_2`로 지정한다.
5. 초안을 사용자에게 보여 주고, **사람이 수소문 화면에서 확인·발송**하도록 넘긴다. 보내기·제안함 저장은 대행하지 않는다.

## 결과를 전할 때

- 한글 표시명을 사용하고 필요한 경우 보조 이름을 함께 적는다. 사람을 제시할 때 추천 설명과 근거 기록의 ID·제목·연도·근거 종류·출처 주소를 함께 제시한다.
- 공개 근거로 연결된 후보라는 점과 **연락 가능성·협업 의사는 미확인**이라는 고지를 보존한다. 현재 소속·가용 시간 등 자료가 확인하지 않은 내용을 확정하지 않는다.
- 공개되지 않은 인물·개인 프로필·연락처를 추측하거나 다른 정보로 복원하지 않는다. 웹과 같은 공개 범위 안에서만 도구 결과를 사용하며 공개 설정을 넓히지 않는다.
- 내부 추천 점수나 순위를 능력·업무 성과 평가로 해석하지 않는다. `schema_version`, `pool_version`, `generated_at`을 확인해 어느 자료와 응답을 근거로 했는지 구분한다.
- 명령행 기본 JSON은 UTF-8이다. 사람이 읽는 요약이 필요하면 `--text`를 사용한다. JSON 오류와 0이 아닌 종료 코드를 정상 결과로 전달하지 않는다. MCP의 `isError`도 확인한다.

## 예시 1 — 문제에서 자문 후보 찾기

사용자: “화학공정의 모델 예측 제어에서 입력 제약을 검토해 줄 사람을 찾아 줘.”

```powershell
python -m rndplz.agent find-people "화학공정 모델 예측 제어 입력 제약 자문" --limit 3
python -m rndplz.agent person PERSON_ID
python -m rndplz.agent record RECORD_ID
```

`PERSON_ID`와 `RECORD_ID`는 첫 결과에서 고른 실제 값으로 바꾼다. 후보의 한글 이름, 해당 문제와 연결되는 이유, 확인한 기록·출처를 함께 전달하고 연락 가능성과 협업 의사는 미확인이라고 알린다.

## 예시 2 — 역량에서 찾고 초안 준비하기

사용자: “연구 맵에서 필요한 역량을 살펴보고, 관련 경험자에게 자문을 구할 초안을 만들어 줘.”

```text
list_capabilities({})
people_for_capability({"capability_id":"CAPABILITY_ID"})
get_person({"person_id":"PERSON_ID"})
get_record({"record_id":"RECORD_ID"})
draft_request({"person_ids":["PERSON_ID"],"need":"입력 제약과 모델 불확실성에 대한 자문","requester_note":"구현 의뢰가 아닌 검토 요청"})
```

위 표기는 MCP 도구 호출 순서와 인자 예시다. 대문자 ID는 앞 단계 결과의 실제 ID로 바꾼다. 사용자가 선택한 역량과 필요에 맞춰 인자를 채우고 근거를 확인한 뒤 초안을 만든다. 제목·본문을 전달하고 사람이 수소문 화면에서 확인·발송하도록 안내한다.
