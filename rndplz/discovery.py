"""Evidence-backed search readiness; independent of recommendation ranking."""
from dataclasses import asdict
import hashlib
import json
import re
import unicodedata


# Navigation scopes over existing tags, not new paper classifications.
FAMILIES = {
    'catalysis': ('촉매·에너지 전환', {
        'GS-SURFACE', 'CE-CCU', 'CE-H2', 'CE-CAT', 'CE-SAF', 'CE-BIO',
        'CE-FAC', 'GS-ELECTRO', 'BIO-ENZYME', 'GS-BIOCAT'}),
    'process': ('공정 개발·해석', {
        'PE-SEP', 'PE-MODEL', 'PE-BIO', 'PE-POLYMER', 'PE-VISION',
        'PE-OPT', 'GS-PROCESS-AI', 'EXP02-CONTROL'}),
    'materials': ('소재·분리·순환', {
        'GS-POLYMER', 'GS-TRIBOLOGY', 'GS-CIRCULAR', 'GS-POROUS',
        'GS-CO2-CAPTURE', 'PE-POLYMER', 'PE-SEP'}),
}
BROAD = {'GS-SURFACE', 'CE-CAT'}
BROAD_TERMS = {'촉매', 'catalyst', 'catalysis', 'catalytic', '촉매 설계',
               '고분자', '중합', 'polymer', 'polymerization', '공정',
               '소재', '재료', 'ai', '인공지능'}
EXECUTE = re.compile(r'현재\s*정보로\s*수소문|바로\s*(?:찾아|추천|수소문)|(?:그|이)\s*(?:조건|내용|정보)(?:으로|로)\s*(?:찾아|추천|수소문)')


DEFER_SEARCH = re.compile(r'(?:수소문|찾기|검색|추천)(?:은|는|을|를)?\s*(?:하지\s*(?:마|말|않)|말고|나중|안\s*해)|(?:아직|나중).{0,30}(?:수소문|검색|추천)')

CONTROL_ONLY = re.compile(r'(?:(?:좋아|네|응|알겠어)[.!?\s]*)?(?:현재\s*정보로\s*수소문|바로\s*(?:찾아|추천|수소문)|(?:그|이)\s*(?:조건|내용|정보)(?:으로|로)\s*(?:찾아|추천|수소문))\s*(?:해\s*)?(?:줘|주세요|줄래|주겠니)?[.!?\s]*')


class DiscoveryError(ValueError):
    code = 'discovery_not_ready'
    def __init__(self):
        super().__init__('현재 조건을 새 메시지로 확인한 뒤 수소문을 눌러 주세요.')


def normal(value):
    return unicodedata.normalize('NFKC', str(value or '')).casefold()


def pattern(term):
    value = normal(term)
    escaped = re.escape(value)
    return r'(?<![a-z0-9])' + escaped + r'(?![a-z0-9])' if re.fullmatch(r'[a-z0-9-]{1,4}', value) else escaped


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(',', ':')).encode()).hexdigest()


class Discovery:
    def __init__(self, actions):
        self.actions = actions
        self.engine = actions.engine
        self.corpus = actions.corpus

    def matches(self, text):
        topic_text=normal(text).replace('수소문',' ')
        spans = [(m.start(), m.end(), topic['id'], term)
                 for topic in self.corpus.topics for term in topic['keywords']
                 for m in re.finditer(pattern(term), topic_text)]
        # A short generic word inside a more specific phrase is not another
        # independent condition (e.g. CO2 inside CO2 포집).
        spans = [row for row in spans if not any(a <= row[0] and b >= row[1]
                 and b-a > row[1]-row[0] for a,b,_,_ in spans)]
        grouped = {}
        for _,_,tid,term in spans:
            grouped.setdefault(tid, set()).add(normal(term))
        return grouped

    def _links(self, topic_ids):
        wanted = set(topic_ids)
        return {record.id: sorted({p.person_id for p in record.people
                    if p.person_id in self.corpus.people})
                for record in self.corpus.records.values()
                if not record.virtual and wanted.intersection(record.tags)
                and any(p.person_id in self.corpus.people for p in record.people)}

    def _record_control_concepts(self, record):
        """Topic evidence with explicit non-use/comparison-only exclusions.

        These bounded text rules do not certify execution or classify papers.
        An explicit exclusion wins over a bare title mention in the same record.
        """
        content = re.sub(r'(?<=[a-zA-Z])[-\u2010\u2011\u2013](?=[a-zA-Z])', ' ',
                         normal(record.title + '\n' + record.text))
        mentions = self.engine._profile_mentions(content)
        positive, denied = set(), set()
        for mention in mentions:
            tail = re.split(r'[.!?;\n]', content[mention['end']:], maxsplit=1)[0]
            non_use = re.match(
                r'^\s*(?:(?:was|were|is|are|has|have|had)\s+)?(?:not|never)\s+'
                r'(?:been\s+)?(?:used|applied|implemented|evaluated|employed)\b'
                r'|^\s*(?:은|는|을|를|이|가)?\s*(?:사용|적용|구현|평가|도입)'
                r'(?:하지\s*않|되지\s*않|하지\s*못|되지\s*못)', tail)
            comparison_only = re.match(
                r'^\s*(?:(?:is|was|are|were)\s+)?(?:only|just|merely)\s+'
                r'(?:(?:a|an|the|as)\s+)*(?:comparison|reference)\b'
                r'|^\s*(?:은|는|을|를|이|가)?\s*비교\s*(?:대상|목적|참고)(?:으로|로)?만', tail)
            if mention['negated'] or non_use or comparison_only:
                denied.add(mention['concept'])
            else:
                positive.add(mention['concept'])
        return positive - denied

    def _control_links(self, concept):
        """Actual control records, separately from declared profile interests."""
        links = {}
        for record in self.corpus.records.values():
            if record.virtual or not (record.field == 'process_control' or any(
                    self.corpus.topic_by_id.get(tid, {}).get('field') == 'process_control'
                    for tid in record.tags)):
                continue
            concepts = self._record_control_concepts(record)
            supports = bool(concepts) if concept == 'process_control' else concept in concepts
            people = sorted({p.person_id for p in record.people
                             if p.person_id in self.corpus.people
                             and not self.corpus.people[p.person_id].virtual})
            if supports and people:
                links[record.id] = people
        return links

    def _conditions(self, request):
        """Use accepted source clauses; never infer facts from assistant prose."""
        sources = request.get('sources') or [{'text':request.get('query',''), 'kind':'user_text'}]
        active = []; issues = []; excluded = set()
        for source in sources:
            text = source.get('text','').strip()
            if not text or DEFER_SEARCH.search(text) or CONTROL_ONLY.fullmatch(text):
                continue
            if re.fullmatch(r'(?:좋아|네|응|알겠어|모르겠어|아직\s*몰라|괜찮아|현재\s*정보로\s*수소문|바로\s*찾아줘)[.!\s]*', text):
                continue
            if re.fullmatch(r'(?:(?:조건|요청|방향)(?:을|를)?\s*)?(?:(?:조금|좀|더)\s*)*생각(?:해\s*볼게|할게|하겠어)(?:요)?[.!?\s]*', text):
                continue
            if re.search(r'조건.{0,8}(?:철회|취소|없애|빼)|(?:처음|원래)(?:으로|대로)', text):
                active = []; issues = []; continue
            generic_search=bool(re.fullmatch(r'(?:전문가|사람|연구자|연구원|인물)(?:를|을)?\s*(?:찾아\s*(?:줘|주세요)|추천해\s*(?:줘|주세요)|필요해)[.!?\s]*',text))
            if self.actions.people_request(text) and active and not generic_search and not re.search(r'추가|함께|모두|그중|그\s*조건',text):
                incoming=set(self.matches(text)); prior=set().union(*(set(row['tags']) for row in active))
                same_family=any(incoming.intersection(tags) and prior.intersection(tags) for _,tags in FAMILIES.values())
                if not incoming or (not same_family and not incoming.intersection(prior)):
                    active=[];issues=[];excluded=set()
            replacement = re.search(r'말고|아니라|아니고|대신|→|->', text)
            if replacement:
                old = self.matches(text[:replacement.start()])
                new = text[replacement.end():].strip()
                if not old or not self.matches(new):
                    issues.append('어떤 조건을 무엇으로 바꿀지 아직 확인하지 못했어요. 바꿀 대상과 새 조건을 함께 알려 주세요.')
                    continue
                old_ids = set(old)
                # A replaced clause is withdrawn as a unit. Its other words
                # cannot silently survive as constraints of a new task.
                if old_ids.intersection(BROAD):
                    old_ids |= set().union(*(tags for _,tags in FAMILIES.values() if old_ids.intersection(tags)))
                active = [entry for entry in active if not old_ids.intersection(entry['tags'])]
                excluded |= old_ids
                text = new
                issues = []
            elif re.search(r'빼고|제외|아니(?:야|에요)|아닌|취소|철회|원하지|않|하지\s*마', text):
                removed = set(self.matches(text))
                if removed:
                    active = [entry for entry in active if not removed.intersection(entry['tags'])]
                    excluded |= removed
                    continue
                issues.append('정정할 조건을 아직 구분하지 못했어요. 바꿀 대상과 새 조건을 함께 알려 주세요.')
                continue
            tags = self.matches(text)
            if tags:
                excluded.difference_update(tags)
            # Explicit alternatives/hypotheses are not accepted conjuncts.
            if re.search(r'또는|혹은|아니면|\bor\b|만약|가정|할까|어떨까|둘\s*중', text, re.I):
                issues.append('대안 중 이번에 찾아볼 조건이 아직 정해지지 않았어요. 사용할 대상을 알려 주세요.')
                continue
            if re.search(r'같은\s*(?:프로젝트|공정|기록)|동일\s*(?:프로젝트|공정|기록)|동시에', text):
                issues.append('같은 작업에서 함께 수행했는지는 현재 등록 기록만으로 확인하지 못했어요.')
            active.append({'text':text, 'tags':tags, 'source':source})
        return active, issues, excluded

    def evaluate(self, request, previous=None, text=''):
        active, issues, excluded = self._conditions(request)
        issues = list(request.get('unresolved') or []) + issues
        query = '\n'.join(row['text'] for row in active)
        matched = {}
        for row in active:
            for tid,terms in row['tags'].items():
                if tid not in excluded:
                    matched.setdefault(tid, set()).update(terms)
        family_ids = [key for key,(_,tags) in FAMILIES.items() if set(matched).intersection(tags)]
        if not family_ids and (re.search(r'공정', query) or self.engine.profile_query_terms(query)):
            family_ids = ['process']
        parent_topics = set().union(*(FAMILIES[key][1] for key in family_ids)) if family_ids else set()
        # Other registered fields remain searchable using their own evidence
        # scope. A missing navigation family is not a missing expert.
        other = set(matched) - parent_topics
        fields = {record.field for record in self.corpus.records.values()
                  if other.intersection(record.tags)}
        for record in self.corpus.records.values():
            if record.field in fields:
                parent_topics.update(record.tags)
        parent_links = self._links(parent_topics)
        parent_ids = {pid for ids in parent_links.values() for pid in ids}
        conditions = []
        unsupported = []
        groups = []
        for tid,terms in matched.items():
            if tid in BROAD or all(normal(term) in BROAD_TERMS for term in terms):
                continue
            overlap = [g for g in groups if g['terms'].intersection(terms)]
            group = {'topic_ids':{tid}, 'terms':set(terms)}
            for old in overlap:
                group['topic_ids'].update(old['topic_ids']); group['terms'].update(old['terms']); groups.remove(old)
            groups.append(group)
        requested_controls = set(self.engine.profile_query_terms(query))
        requested_controls = requested_controls - {'process_control'} or requested_controls
        control_records = {rid for concept in requested_controls for rid in self._control_links(concept)}
        for group in groups:
            control_topics = {tid for tid in group['topic_ids']
                              if self.corpus.topic_by_id[tid].get('field') == 'process_control'}
            if requested_controls and control_topics:
                # Do not reintroduce sibling or unrelated records through a
                # broad control tag. Separate required methods still retain
                # the union of their own supporting records below.
                links = self._links(group['topic_ids'] - control_topics)
                links.update({rid: people for rid, people in self._links(control_topics).items()
                              if rid in control_records})
            else:
                links = self._links(group['topic_ids'])
            conditions.append({'topic_ids':sorted(group['topic_ids']),
                'name':' / '.join(self.corpus.topic_by_id[tid]['name'] for tid in sorted(group['topic_ids'])),
                'terms':sorted(group['terms']), 'candidate_ids':sorted({pid for ids in links.values() for pid in ids}),
                'record_ids':sorted(links)})
        # User qualifiers apply to their own current condition, irrespective
        # of whether it is numeric or qualitative. They are never evidence.
        for row in active:
            raw=row['text']
            concepts = self.engine.profile_query_terms(raw)
            knownterms = [term for terms in row['tags'].values() for term in terms]
            knownterms.extend(m['query_term'] for m in self.engine._profile_mentions(raw)
                              if not m['negated'] and m['concept'] in concepts)
            notes=condition_notes(row,knownterms)
            unsupported.extend(notes['unverified']); issues.extend(notes['blocking'])
            # A specific requested controller must have its own linked records.
            # Broad process-control records do not establish MPC/APC/PID siblings.
            labels = {'process_control':'공정 제어', 'mpc':'MPC', 'apc':'APC', 'pid':'PID'}
            for concept in [c for c in concepts if c != 'process_control'] or concepts:
                links = self._control_links(concept)
                if not links:
                    if self.engine.profile_matches(labels[concept]):
                        issues.append(f'{labels[concept]}는 등록 기술·관심에서 확인되지만 연결된 연구·경력 기록은 아직 없어요.')
                    else:
                        issues.append(f'{labels[concept]} 조건을 뒷받침하는 등록 연구·경력 기록을 찾지 못했어요.')
                    continue
                ids = sorted({pid for people in links.values() for pid in people})
                if not any(c['record_ids'] == sorted(links) and c['candidate_ids'] == ids for c in conditions):
                    topic_ids = sorted({tid for rid in links for tid in self.corpus.records[rid].tags})
                    conditions.append({'topic_ids':topic_ids, 'name':labels[concept] + ' 연구 근거',
                        'terms':[labels[concept]], 'candidate_ids':ids, 'record_ids':sorted(links)})
            if not row['tags'] and not notes['unverified'] and not re.search(r'공정|찾아|수소문|전문가|연구자|사람|모르겠|알겠|좋아',raw):
                unsupported.append(raw[:100])
        if 'CE-CCU' in matched and not re.search(r'전환|ccu|메탄올|saf|항공연료', normal(query)):
            issues.append('CO₂ 포집과 화학적 전환 중 어느 쪽을 찾고 계신가요?')
        candidate_ids = set(parent_ids)
        for condition in conditions:
            candidate_ids.intersection_update(condition['candidate_ids'])
        if not conditions:
            candidate_ids.clear()
        candidate_ids.difference_update(self.actions.excluded(query))
        record_ids = {rid for condition in conditions for rid in condition['record_ids']
                      if candidate_ids.intersection(self._links(condition['topic_ids']).get(rid, []))}
        ready = bool(conditions and candidate_ids and candidate_ids < parent_ids and not issues)
        if issues:
            status = 'unresolved'; question = issues[0]
        elif conditions and not candidate_ids:
            status = 'no_evidence'; question = ''
        elif not parent_topics:
            status = 'unsupported_scope'; question = ''
        elif not conditions:
            status = 'broad'; question = ('촉매를 어떤 반응이나 제품에 쓰려는지 알려 주실래요?' if 'catalysis' in family_ids else '어떤 공정이나 해결할 문제의 경험이 필요한가요?')
        elif not candidate_ids:
            status = 'no_evidence'; question = ''
        elif not ready:
            status = 'not_narrowed'; question = '현재 기록에서는 아직 후보가 구분되지 않아요. 가장 중요한 반응이나 제품을 알려 주실래요?'
        else:
            status = 'ready'; question = ''
        labels = [c['name'] for c in conditions]
        summary = ' · '.join(labels) or ' · '.join(FAMILIES[key][0] for key in family_ids) or query[:120]
        reasons = {
            'ready':'말씀하신 주제와 연결된 기록을 기준으로 찾아볼 범위가 좁혀졌어요. 개인의 실제 수행 범위와 현재 협업 가능성은 추가 확인이 필요해요.',
            'broad':'지금은 분야가 넓어서 하려는 일을 조금 더 이해하고 싶어요.',
            'no_evidence':'현재 등록 자료에서 이 조건들을 함께 뒷받침하는 인물을 찾지 못했어요. 조건을 풀거나 다른 주제로 바꾸면 다시 살펴볼 수 있어요.',
            'unsupported_scope':'현재 등록 자료로는 이 요청을 충분히 구분할 수 없어요. 확인할 수 없는 조건을 남긴 채 인물을 제안하지 않겠습니다.',
            'not_narrowed':'등록 기록에 조건을 적용했지만 아직 범위를 구분하기 어려워요.',
            'unresolved':'확정되지 않았거나 기록으로 확인할 수 없는 조건이 남아 있어요.',
        }
        basis = {'query':query, 'sources':request.get('sources',[]), 'unresolved':issues,
                 'conditions':conditions, 'unsupported':unsupported, 'parent':sorted(parent_ids),
                 'records':sorted(record_ids), 'evidence':{rid:asdict(self.corpus.records[rid]) for rid in sorted(parent_links)},
                 'pool':getattr(self.corpus,'demo_pool',{}).get('version')}
        revision = fingerprint(basis)
        repeated = bool(previous and previous.get('status') == status and previous.get('summary') == summary and previous.get('question') == question)
        show_question = bool(question and not (repeated and not ready))
        reply = (f'「{summary}」 경험이 있는 분을 찾으시는 것으로 이해했어요.\n\n' if summary else '') + reasons[status]
        hint_given=bool(previous and previous.get('hint_given'))
        if repeated and status=='broad':
            if hint_given:
                reply='원하는 반응이나 제품이 떠오르면 이어서 말씀해 주세요. 그 내용을 바탕으로 다시 살펴볼게요.'
            else:
                example='예를 들어 CO₂ 전환처럼 다루는 반응이나 SAF처럼 만들려는 제품을 한 가지만 말씀해 주세요.' if 'catalysis' in family_ids else '예를 들어 증류처럼 다루는 공정이나 해결하려는 문제를 한 가지만 말씀해 주세요.'
                reply='아직 반응·제품 또는 구체적인 문제가 없어 범위를 좁히기 어려워요. '+example
                hint_given=True
        if unsupported and ready:
            reply += '\n\n추가 확인할 요청: ' + ' · '.join(dict.fromkeys(unsupported)) + '. 이 부분을 충족한다는 의미는 아니에요.'
        if show_question:
            reply += '\n\n' + question
        return {'ready':ready, 'status':status, 'summary':summary, 'reason':reasons[status],
                'question':question, 'query':query, 'revision':revision, 'reply':reply,
                'candidate_ids':sorted(candidate_ids), 'record_ids':sorted(record_ids),
                'conditions':conditions, 'parent_ids':sorted(parent_ids), 'hint_given':hint_given,
                'unsupported':unsupported, 'unresolved':issues}

    @staticmethod
    def public(state):
        return {key:state[key] for key in ('ready','status','summary','reason','question','revision','hint_given')}


def _normal(value):
    return unicodedata.normalize("NFKC", str(value or "")).casefold()

def _without_known(value, knownterms):
    value = _normal(value)
    for term in sorted({_normal(t) for t in knownterms if t}, key=len, reverse=True):
        escaped = re.escape(term)
        if re.fullmatch(r"[a-z0-9-]{1,4}", term):
            escaped = r"(?<![a-z0-9])" + escaped + r"(?![a-z0-9])"
        value = re.sub(escaped, " ", value)
    # Used only inside the noun phrase of an explicit experience/scope request.
    value = re.sub(r"생산|전환|합성|공정|관련|분야|그리고|경험|전문성|전문가|연구자|연구원", " ", value)
    value = re.sub(r"(?:에서|으로|하려는|하는|의|과|와|을|를|이|가|도|은|는)(?=\s|$)", " ", value)
    return re.sub(r"[\s·/+,-]+", "", value)

def condition_notes(row, knownterms):
    """Return original clause notes and at most one question per unresolved clause.

    This conservative draft recognizes scoped assertions/experience requirements.
    It does not certify that every free-form constraint has been interpreted.
    """
    knownterms = tuple(knownterms)
    active = str(row.get("text") or "").strip()
    if not active:
        return {"unverified": [], "blocking": []}
    source = row.get("source") or row
    quote = str(source.get("quote") or active).strip()
    # Keep exact substring wording; split only overt sentence/clause boundaries.
    clauses = re.split(r"[\n;]+|[.!?](?:\s+|$)|,\s*|\s+(?:그리고|하지만|반면)\s+|(?:이고|이며|하고)\s+", quote)
    notes, questions = [], []
    measure = re.compile(r"(?<![\d.])\d+(?:\.\d+)?\s*(?:도|℃|°c|bar|년|개월|만원|원|일|주|장|개|%)", re.I)
    attribute = re.compile(r"내구|성능|순도|선택도|수율|효율|가용|소속|장비|압력|온도|검증|확인된")
    required = re.compile(r"검증된|확인된|반드시|필수|충족해야|꼭")
    relaxed = re.compile(r"필수(?:는|가)?\s*(?:아님|아니(?:야|에요|고|라|다)?|않(?:아|고|는|다)?|없(?:어|고|는|다)?|해제|철회)|후보에게\s*확인(?:할|하(?:면|려고|는|기|고)|해)?(?:\s*사항)?|선호\s*(?:사항)?")
    scope = re.compile(r"(.+?)\s*(?:경험|분야|전문성)(?:도|이|가|은|는|을|를)?\s*(?:필요|있|함께|요구|필수)")
    active_values = {re.sub(r'\s+','',v) for v in measure.findall(_normal(active))}
    for raw in clauses:
        raw = raw.strip()
        if not raw:
            continue
        value = _normal(raw)
        values = {re.sub(r'\s+','',v) for v in measure.findall(value)}
        # A previous value quoted alongside a current normalized row is not active.
        if active_values and values and not active_values.intersection(values):
            continue
        unknown_scope = any(_without_known(m[1], knownterms) for m in scope.finditer(raw))
        has_attribute = bool(measure.search(value) or attribute.search(raw))
        asks_followup = bool(relaxed.search(raw))
        # Do not run "required" against a whole multi-clause quote. Explicit
        # negation of 필수 applies only here; another mandatory phrase still wins.
        non_relaxed_text = relaxed.sub("", raw)
        is_required = bool(required.search(non_relaxed_text))
        if not (unknown_scope or has_attribute or asks_followup):
            # Ordinary purposes connecting matched topics are not extra facts.
            continue
        if raw not in notes:
            notes.append(raw)
        if is_required:
            subject=raw
            for term in sorted(knownterms,key=len,reverse=True):
                subject=re.sub(re.escape(term),' ',subject,flags=re.I)
            subject=re.sub(r'^(?:\s+|(?:전환|생산|합성|공정|경험과|경험이|경험은|경험|관련|을|를|와|과)(?=\s|$))+','',subject).strip() or raw
            question = f"추가로 요구하신 「{subject}」의 충족 여부는 등록 기록으로 확인하지 못했어요. 이 조건을 후보에게 확인할 사항으로 남겨도 될까요?"
        elif unknown_scope and not asks_followup:
            question = f"「{raw}」의 추가 경험·분야는 등록 근거로 확인하지 못했어요. 이번 검색에 꼭 필요한 별도 경험인가요?"
        elif not asks_followup and attribute.search(raw) and not measure.search(value):
            question = f"「{raw}」는 충족이 필수인 조건인가요, 후보에게 확인할 사항인가요?"
        else:
            question = None
        if question and question not in questions:
            questions.append(question)
    return {"unverified": notes, "blocking": questions}
