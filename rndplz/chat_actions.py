"""Grounded conversational actions over the current service's visible corpus only."""
import re
import unicodedata


def normalized(text):
    return unicodedata.normalize('NFKC', str(text or '')).casefold().strip()


class ChatActions:
    def __init__(self, service):
        self.service = service
        self.engine = service.engine
        self.corpus = service.corpus
        self.names = []
        for person in self.corpus.people.values():
            aliases = [person.name, *person.profile.get('aliases', [])]
            if person.virtual:
                aliases.append(re.sub(r'^\(가상\)\s*', '', person.name))
            for alias in set(aliases):
                compact = re.sub(r'[\s.·-]', '', normalized(alias))
                if len(compact) < 2:
                    continue
                pattern = r'(?<![a-z0-9가-힣])' + r'[\s.·-]*'.join(re.escape(c) for c in compact)
                pattern += r'(?![a-z0-9])'
                if re.search(r'[가-힣]$', compact):
                    pattern += r'(?=$|[^가-힣]|님|씨|교수|박사|연구|라는|이라는|의|은|는|이|가|도|를|을|과|와|에게|한테)'
                self.names.append((person.id, re.compile(pattern), len(compact)))

    def matches(self, text):
        value = normalized(text)
        found = [(pid, match.start(), match.end(), size)
                 for pid, pattern, size in self.names for match in pattern.finditer(value)]
        # A full registered name takes precedence over an alias inside it.
        found = [row for row in found if not any(other[1] <= row[1] and other[2] >= row[2]
                 and other[3] > row[3] for other in found)]
        ids = sorted({row[0] for row in found})
        remainder = value
        for start, end in sorted({(row[1], row[2]) for row in found}, reverse=True):
            remainder = remainder[:start] + ' ' + remainder[end:]
        return ids, remainder

    def excluded(self, text):
        value = normalized(text)
        return {pid for pid, pattern, _ in self.names for match in pattern.finditer(value)
                if re.match(r'\s*(?:님|씨|교수님?|박사님?)?\s*(?:은|는|을|를|이|가)?\s*(?:(?:추천하지|보여주지|찾지|포함하지|(?:찾는|추천하는)\s*(?:건|것은|게))\s*)?(?:말고|제외|빼(?:고|줘|주세요)|아니(?:라|야|고|에요)|아닌)', value[match.end():])}

    def blank(self, intent, message='', cards=None, choices=None):
        return {'intent': intent, 'mode': 'advice', 'mode_label': '인물 조회', 'field': 'unknown',
                'topic_ids': [], 'candidates': cards or [], 'choices': choices or [],
                'author_strip': [], 'author_strip_record': None, 'closest_topics': [],
                'empty_message': message, 'record_count': 0, 'model_calls': 0,
                'ranking_source': '기록 조회', 'claims': []}

    def choice_rows(self, ids):
        return [{'id': pid, 'name': self.corpus.people[pid].name, 'org': self.corpus.people[pid].org,
                 'virtual': self.corpus.people[pid].virtual} for pid in ids if pid in self.corpus.people]

    def clarification(self, ids, message, query=''):
        return {'reply': message, 'result': self.blank('person_choice', message, choices=self.choice_rows(ids)),
                'context': {'kind': 'person_choice', 'ids': ids, 'query': query}, 'can_propose': False}

    def profile_candidate(self, row):
        person = self.corpus.people[row['person_id']]
        facts = row['matches']
        labels = list(dict.fromkeys(f['basis'] for f in facts))
        citations = list(dict.fromkeys(f"{f['basis']}에 「{f['value']}」 ({f['query_term']} 일치)" for f in facts))
        count = len(self.corpus.by_person.get(person.id, []))
        return {'id': person.id, 'name': person.name, 'org': person.org, 'org_type': person.org_type,
                'profile': person.profile if person.profile.get('curated') else {},
                'virtual': person.virtual, 'kind': person.kind, 'role': ' · '.join(labels),
                'reason': ', '.join(citations) + ' 항목이 있습니다. 이 조건에 직접 연결되는 수행 기록은 확인되지 않았습니다.',
                'experience': '프로필 등록 항목 · 수행 경험 미확인', 'evidence': [], 'evidence_counts': {},
                'profile_matches': facts, 'details': {'profile_matches': facts}, 'profile_only': True,
                'record_count': count, 'works_in_corpus': count, 'works_count': person.profile.get('works_count'),
                'relevant_records': 0, 'condition_evidence_count': 0, 'condition_checked': True,
                'topics': [], 'profile_topics': [], 'portfolio': '등록 항목 일치 · 수행 경험 미확인',
                'record_confirmed': False, 'individual_performance_verified': False,
                'person_confirmed': False, 'availability': '미확인', 'lookup_only': True}

    def profiles(self, ids, text=''):
        # Only an explicitly stated affiliation is checked; it is not current HR verification.
        affiliation = re.search(r'^\s*([^,!?\n]{2,120}?)\s*소속', text) if len(ids) == 1 else None
        requested_org = affiliation.group(1).strip(' .()') if affiliation else ''
        topics = self.engine.topics_for(text)
        field = self.engine.field_for(topics, 'advice', text)
        relevant = {r.id for r, score in self.engine.record_scores(text, topics, field, 'advice')} if topics else set()
        profile_terms = self.engine.profile_query_terms(text)
        profile_rows = {r['person_id']: r for r in self.engine.profile_matches(text, ids)}
        cards = []
        for pid in ids:
            detail = self.service.person(pid)
            own = self.corpus.by_person[pid]
            evidence = detail['evidence']
            matched = [e for e in evidence if e['id'] in relevant]
            reason = '요청한 이름의 등록 기록입니다. 특정 업무의 적임자나 본인 확인을 뜻하지 않습니다.'
            if topics:
                reason = ('요청 조건과 연결된 참여 기록을 함께 표시했습니다. 개인의 직접 수행 여부는 미확인입니다.'
                          if matched else '이 사람의 등록 기록에서 요청 조건에 맞는 근거는 찾지 못했습니다. 아래는 인물 자체의 기록입니다.')
            if profile_terms and not matched:
                reason = '이 사람의 등록 기술·관심과 수행 기록에서 요청 조건을 확인하지 못했습니다.'
            card = {**detail, 'role': '등록 인물', 'reason': reason,
                    'evidence': (matched if profile_terms else matched or evidence)[:3],
                    'condition_evidence_count': len(matched),
                    'condition_checked': bool(topics or profile_terms or requested_org),
                    'works_count': self.corpus.people[pid].profile.get('works_count'),
                    'works_in_corpus': len(own), 'relevant_records': len(matched), 'lookup_only': True}
            if pid in profile_rows and not matched:
                card.update(self.profile_candidate(profile_rows[pid]))
            org_matches = bool(requested_org and normalized(requested_org) in normalized(detail['org']))
            card.update(requested_affiliation=requested_org, affiliation_checked=bool(requested_org),
                        affiliation_matches=org_matches if requested_org else None)
            if requested_org and not org_matches:
                card['reason'] = '요청한 소속과 등록 소속이 일치하지 않습니다. 등록 소속: ' + detail['org'] + '. ' + card['reason']
            cards.append(card)
        names = ' · '.join(card['name'] for card in cards)
        result = self.blank('person_lookup', cards=cards)
        result['record_count'] = sum(card['record_count'] for card in cards)
        result['topic_ids'] = list(topics)
        only_ids = [c['id'] for c in cards if c.get('profile_only')]
        reply = names + '의 등록 이력과 근거 기록을 보여드릴게요. 현재 소속·수행 역할·연락 의향은 별도 확인이 필요합니다.'
        if only_ids:
            reply = names + '의 등록 기술·관심을 확인했습니다. 해당 조건의 수행 기록은 찾지 못했으며, 전체 이력과 구분해 표시합니다.'
        return {'reply': reply, 'result': result,
                'context': {'kind': 'person_lookup', 'ids': ids, 'query': text, 'profile_only_ids': only_ids},
                'can_propose': False}

    def profile_followup(self, context, ids, text):
        # A request for the same person's evidence retains the original condition.
        # Their full career remains available in person detail, not as condition evidence.
        prior = context.get('profile_only_ids', [])
        fresh = self.engine.profile_query_terms(text) or self.engine.topics_for(text)
        switch = re.search(r'말고|제외|대신|아니면|새로|다른\s*분야|주제\s*(?:변경|바꿔)', text)
        if prior and all(pid in prior for pid in ids) and not fresh and not switch:
            return (context.get('query', '') + '\n' + text).strip()
        return text

    @staticmethod
    def unknown_name(text):
        patterns = [
            r'^\s*(?:혹시\s+)?([가-힣]{2,5}|[a-z]+(?:[ .-]*[a-z]+){1,3})\s*(?:님)?(?:을|를)?\s*(?:보여줘|보여주세요|찾아줘|찾아주세요|있니|있나요)[?!.\s]*$',
            r'([가-힣]{2,8}(?:\s+[가-힣]{1,3})?)\s*(?:이?라는|이라고\s*하는)\s*(?:사람|연구자|분)',
            r'([가-힣]{2,5})\s*(?:님|박사|교수)(?:님)?(?:의|은|는|도|을|를)?\s*(?:프로필|이력|경력|논문|보여|알려|있)',
            r'^\s*([가-힣]{2,5}|[a-z]+(?:\s+[a-z]+){1,3})\s*(?:의\s*)?(?:프로필|이력)\s*(?:을|를)?\s*(?:보여|알려)',
        ]
        for pattern in patterns:
            match = re.search(pattern, normalized(text))
            if match:
                name=match.group(1).strip()
                if name not in ('사람','연구자','연구원','인물','기록','이력','자료','논문','결과','목록','프로필','근거','후보','제안'):
                    return name
        return None

    @staticmethod
    def cancelled(text):
        return bool(re.fullmatch(r'(?:아니(?:다|야|요)?[,\s]*)?(?:됐어|됐어요|됐습니다|그만(?:해|할게|할래|해주세요)?|취소(?:해|할게|해주세요)?|중단(?:해|할게|해주세요)?|stop|cancel|never\s*mind)[.!…\s]*', normalized(text)))

    @staticmethod
    def people_request(text):
        # Match the requested object, not the word "recommend" by itself.
        if re.search(r'(?:찾는|찾을|추천하는|검색하는|필요한지|연결하는).{0,18}(?:방법|기준|이유|원리)', text):
            return False
        noun = r'(?:전문가|연구자|연구원|권위자|인재|사람|담당자|협업자|인물|누가|누구)'
        clauses = re.finditer(r'([^.!?\n;]*?)(말고|아니라|대신|[.!?\n;]|$)', normalized(text))
        for match in clauses:
            clause, ending = match.groups()
            if ending in ('말고', '아니라', '대신') or not re.search(noun, clause):
                continue
            if re.search(r'(?:찾|추천|검색|조회|연결|필요).{0,12}(?:않|말|마(?:세요|라|요|$)|나중|아직|없|아니|안\s*(?:해|하|찾|추천))|(?:전문가|사람|인물)(?:가|는|은|이)?\s*아니', clause):
                continue
            if re.search(r'찾|추천|검색|조회|연결|보여|알려|필요|있(?:니|나|을)|누가|누구|명단|목록|만나|이야기|상담|협업', clause):
                return True
            # Topic + person category is a normal compact search ("딥러닝 권위자").
            if re.search(noun + r'(?:들)?(?:요)?\s*$', clause.strip()):
                return True
        return False

    @classmethod
    def discussion_request(cls, text):
        value = normalized(text)
        if re.search(r'(?:이력|프로필|경력)(?:들)?(?:을|를)?\s*비교', value):
            return False
        person = r'(?:전문가|사람|연구자|인물|검색|추천)'
        deferred = re.search(person + r'.{0,25}(?:찾지|추천하지|검색하지|조회하지|아직|나중|찾는\s*(?:게|건|것)|아니라|말고|안\s*해도)', value)
        # A later explicit positive people request can end an earlier deferral.
        if cls.people_request(value):
            return False
        if deferred:
            return True
        return bool(re.search(r'(?:방법|대안|아이디어|접근|설계|가설|실험|장단점|원리|판단\s*기준|문제\s*정의).{0,50}(?:추천|비교|설명|고민|정리|검토|알려|어떻게|생각)|(?:비교|설명|고민|논의|정정|수정)(?:해|하|할|을|하는|한|부터)|무엇부터|어느\s*실험', value))

    def search_refinement(self, context, text):
        if context.get('kind') != 'recommend' or self.discussion_request(text):
            return False
        if re.search(r'그\s*중|거기서|후보|명단|목록|검색\s*결과|더\s*좁혀', text):
            return True
        if context.get('profile_only_ids') and re.search(r'말고|제외|아닌|빼(?:고|줘)', text):
            return True
        # A short topical fragment refines displayed people; a methods question does not.
        return bool(len(text.strip()) < 60 and self.engine.topics_for(text)
                    and not re.search(r'[?？]|줘|주세요|할까|할지|어떻게|정리|검토|설명|실험|정정', text))

    def query_for(self, session, text):
        prepared = '_request_query' in session
        if prepared:
            text = session['_request_query']
        # A conversational synonym; it does not change corpus classification or weights.
        text = re.sub(r'전열\s*성능', '열전달 heat transfer 성능', text)
        text = re.sub(r'이미지\s*인식', '컴퓨터 비전', text)
        if prepared:
            return text
        context = session.get('search_context') or {}
        previous = context.get('query', '') if context.get('kind') == 'recommend' else ''
        current_topics = self.engine.topics_for(text)
        current_field = self.engine.field_for(current_topics, self.engine.mode_for(text), text)
        prior_field = self.engine.field_for(self.engine.topics_for(previous), self.engine.mode_for(previous), previous)
        changed = bool(re.search(r'아니면|대신|주제\s*(?:바꿔|변경)|새로|다른\s*분야', text))
        if self.engine.profile_query_terms(previous):
            refinement = re.search(r'그\s*조건|이\s*조건|거기서|그중|그\s*중|추가로|함께|도\s*(?:포함|가능)', text)
            # An unknown new field must not inherit the previous control profile match.
            changed = changed or bool(re.search(r'말고|제외|아닌|빼(?:고|줘)', text))
            changed = changed or bool(not refinement and (self.people_request(text) or self.engine.profile_query_terms(text)))
        if changed or current_field != 'unknown' and prior_field != current_field:
            return text
        return (previous + '\n' + text).strip() if previous else text

    @staticmethod
    def requires_performance(text):
        return bool(re.search(r'(?:실제|직접).{0,16}(?:수행|실험|경험|실적)|(?:수행|실험|경험|실적)\s*(?:근거|기록).{0,12}(?:있는|확인|만)', text))

    def recommend(self, session, text, excluded=None, discovery=None):
        query = self.query_for(session, text)
        # Keep legacy record ranking and its evidence contract untouched.
        if discovery is None:
            result = self.engine.recommend(query)
        else:
            # Rank only the records that supported readiness, using the existing
            # engine's votes and reasons. Never filter a truncated top-N list.
            weighted = self.engine.topics_for(query)
            accepted = {tid for condition in discovery['conditions'] for tid in condition['topic_ids']}
            topics = {tid:weighted.get(tid,1) for tid in sorted(accepted)}
            mode = self.engine.mode_for(query)
            field = self.engine.field_for(topics, mode, query)
            allowed = set(discovery['candidate_ids']); records = set(discovery['record_ids'])
            scores = [(r,score) for r,score in self.engine.record_scores(query,topics,field,mode) if r.id in records]
            grouped = {}
            for record,score in scores:
                for contribution in record.people:
                    if contribution.person_id in allowed:
                        grouped.setdefault(contribution.person_id,[]).append((record,score))
            candidates = [self.engine.candidate(self.corpus.people[pid],rows,topics,query) for pid,rows in grouped.items()]
            candidates.sort(key=lambda c:(-c['score_internal'],c['id']))
            for candidate in candidates:
                candidate.pop('score_internal',None)
                candidate['unverified_request_conditions'] = discovery.get('unsupported',[])
            result = self.blank('recommend',cards=candidates[:7])
            result.update(mode=mode,mode_label='기록에서 찾은 인물',field=field,topic_ids=list(topics),record_count=len(scores),ranking_source='규칙')
        excluded = set(excluded or ()) | self.excluded(query)
        result['candidates'] = [c for c in result['candidates'] if c['id'] not in excluded]
        record_count = len(result['candidates'])
        if discovery is None and result['mode'] in ('advice', 'member') and not self.requires_performance(query):
            seen = {c['id'] for c in result['candidates']} | excluded
            for row in self.engine.profile_matches(query):
                if len(result['candidates']) >= 7:
                    break
                if row['person_id'] not in seen:
                    result['candidates'].append(self.profile_candidate(row))
                    seen.add(row['person_id'])
        result['intent'] = 'recommend'
        count = len(result['candidates'])
        profile_ids = [c['id'] for c in result['candidates'] if c.get('profile_only')]
        result['record_candidate_count'] = record_count
        result['profile_match_count'] = len(profile_ids)
        if profile_ids:
            result['empty_message'] = ''
            result['closest_topics'] = []
            reply = (f'기록과 연결된 인물 {record_count}명, 등록 기술·관심에서 찾은 인물 {len(profile_ids)}명입니다. '
                     '등록 항목만 일치한 분은 해당 조건의 수행 경험이 미확인이므로 이력 조회만 제공합니다.')
        elif count:
            reply = f'현재 열람 가능한 기록에서 관련 인물 {count}명을 찾았습니다. 먼저 근거를 살펴보고 필요한 조건을 더 좁힐 수 있어요.'
            if result['field'] == 'ai_foundations':
                reply += ' AI 분야는 수록된 공개 연구 사례이며 전체 전문가 명단이나 협업 가능 인원은 아닙니다.'
        else:
            reply = '현재 열람 가능한 자료에서는 이 요청과 연결할 근거를 찾지 못했습니다. 자료에 없다는 뜻이며, 해당 분야의 전문가가 없다는 뜻은 아닙니다.'
        if count:
            explanations = [f"{c['name']}: {c['reason']}" for c in result['candidates'][:3]]
            reply += '\n\n' + '\n'.join(explanations)
            reply += '\n\n기간·자원·현재 가용성은 요청 조건이며, 해당 인물이 모두 충족한다는 확인은 아닙니다. 근거의 출처와 확인 범위를 카드에서 확인해 주세요.'
        if discovery and discovery.get('unsupported'):
            reply += '\n\n추가 확인할 요청: ' + ' · '.join(dict.fromkeys(discovery['unsupported'])) + '. 충족 여부는 아직 확인되지 않았습니다.'
        return {'reply': reply, 'result': result,
                'context': {'kind': 'recommend', 'ids': [c['id'] for c in result['candidates']],
                            'query': query, 'profile_only_ids': profile_ids},
                'can_propose': any(not c.get('lookup_only') for c in result['candidates']),
                'query': query, 'mode': result['mode']}

    def resolve(self, session, text, selected=None, allow_recommend=True):
        def route(value, excluded=None):
            return self.recommend(session,value,excluded) if allow_recommend else {'discovery_request':True}
        context = session.get('search_context') or {}
        if self.cancelled(text):
            return {'reply': '알겠습니다. 여기서 멈출게요.', 'result': None,
                    'context': {'kind': 'stopped', 'ids': [], 'query': ''}, 'can_propose': False}
        if selected:
            if context.get('kind') != 'person_choice' or selected not in context.get('ids', []) or selected not in self.corpus.people:
                raise ValueError('표시된 인물 선택지에서 다시 선택해 주세요.')
            return self.profiles([selected], context.get('query', ''))
        if self.discussion_request(text):
            return None
        ids, remaining = self.matches(text)
        # A narrated reading experience followed by a methods question is free conversation.
        lookup_request = re.search(r'보여\s*(?:줘|주|달)|찾아\s*(?:줘|주|달)|알려\s*(?:줘|주|달)|누구|있니|있나|궁금|어때|비교', text)
        background = re.search(r'읽었|배웠|봤어|봤습니다|공부했|언급했|말했|라고\s*(?:했|하던|합니다)', text)
        if ids and background:
            followup = text[background.end():]
            asks_for_profile = self.matches(followup)[0] or re.search(r'그\s*(?:사람|분)|이\s*사람|해당\s*인물|이력|프로필|경력', followup)
            if not (lookup_request and asks_for_profile):
                return None
        if ids and not lookup_request and self.engine.mode_for(text) == 'verify':
            return None
        excluded = self.excluded(text)
        ids = [pid for pid in ids if pid not in excluded]
        if not ids and excluded:
            return route(remaining, excluded)
        explicit_name = re.search(r'(?:이?라는|이라고\s*하는)\s*(?:사람|연구자|분)|교수|박사|프로필|이력', text)
        if ids and self.people_request(text) and not explicit_name and all(self.engine.profile_query_terms(self.corpus.people[pid].name) for pid in ids):
            # An acronym used as a topic ("APC 전문가") does not select its namesake.
            return route(text, excluded)
        if ids:
            # Affiliation narrows a duplicate-name group, never a distinct named person.
            groups = {}
            for pid in ids:
                groups.setdefault(normalized(self.corpus.people[pid].name), []).append(pid)
            resolved = []
            ambiguous = False
            for group in groups.values():
                narrowed = [pid for pid in group if self.corpus.people[pid].org not in ('소속 미확인', '')
                            and normalized(self.corpus.people[pid].org) in normalized(text)]
                if len(group) > 1 and len(narrowed) == 1:
                    group = narrowed
                ambiguous = ambiguous or len(group) > 1
                resolved.extend(group)
            ids = resolved
            if ambiguous:
                return self.clarification(ids, '같은 이름의 기록이 여러 개 있습니다. 소속을 확인해 인물을 골라 주세요.', remaining)
            return self.profiles(ids, self.profile_followup(context, ids, remaining))
        # Follow-up ordinals are resolved only against explicitly displayed choices.
        ordinal = re.search(r'(첫\s*번째|두\s*번째|세\s*번째|[1-9]\s*번)', text)
        if ordinal and context.get('kind') == 'person_choice':
            raw = re.sub(r'\s', '', ordinal.group())
            index = {'첫번째': 0, '두번째': 1, '세번째': 2}.get(raw)
            if index is None:
                index = int(raw[0]) - 1
            choices = context.get('ids', [])
            if index < len(choices):
                return self.profiles([choices[index]], context.get('query', '') + '\n' + text)
            return self.clarification(choices, '표시된 인물 중에서 선택해 주세요.', context.get('query', ''))
        if re.search(r'그\s*(?:사람|분|연구자)|이\s*(?:사람|분)(?:의|이|은|는|을|를|\s|$)|해당\s*(?:인물|연구자)', text):
            previous = [pid for pid in context.get('ids', []) if pid in self.corpus.people]
            if len(previous) == 1:
                return self.profiles(previous, self.profile_followup(context, previous, text))
            return self.clarification(previous, '어느 분을 말씀하시는지 이름이나 소속을 알려 주세요.' if not previous
                                      else '여러 인물을 보여드렸어요. 이력을 볼 사람을 골라 주세요.',
                                      self.profile_followup(context, previous, text))
        # A registered technical term plus a search request is not an unknown person's name.
        technical_search = self.engine.profile_query_terms(text) and (self.people_request(text) or re.search(r'찾아\s*(?:줘|주)|보여\s*(?:줘|주)', text))
        if technical_search and not explicit_name and self.engine.mode_for(text) in ('advice', 'member'):
            return route(text)
        unknown = self.unknown_name(text)
        if unknown:
            message = f'현재 열람 가능한 자료에서 {unknown} 님을 찾지 못했습니다. 이름의 다른 표기나 소속이 있으면 확인할 수 있어요.'
            return {'reply': message, 'result': self.blank('person_lookup', message),
                    'context': {'kind': 'person_lookup', 'ids': [], 'query': ''}, 'can_propose': False}
        people_request = self.people_request(text)
        refine = self.search_refinement(context, text)
        if people_request or refine:
            return route(text)
        return None
