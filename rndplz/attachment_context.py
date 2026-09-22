"""Current-session authority and bounded model previews for attachment tools."""
import copy
from .service import provider_scope, RUNTIME_DOCUMENT_SCOPE_ID, GEMINI_DOCUMENT_SCOPE_ID


def reader_items(conversation, session):
    if not any(m.get('role') == 'user' and m.get('kind') != 'self_profile'
               and m.get('attachments') for m in session.get('messages', [])):
        return []
    scope = provider_scope(session)
    if not scope or scope.get('id') not in (RUNTIME_DOCUMENT_SCOPE_ID, GEMINI_DOCUMENT_SCOPE_ID):
        return []
    result = {}; count = 0
    for message in session.get('messages', []):
        if message.get('role') != 'user' or message.get('kind') == 'self_profile':
            continue
        ids = [ref['id'] for ref in message.get('attachments', [])]
        # Existing provider policy validates each request's explicitly selected IDs.
        for item in conversation._scoped_attachment_items(ids, scope):
            if not item.get('image'):
                result[item['id']] = item
        count = len(result)
        if count > 64:
            raise ValueError('이 대화에서 읽을 수 있는 첨부 목록 범위를 넘었습니다.')
    return list(result.values())


def source_previews(sources):
    result = copy.deepcopy(sources)
    for row in result:
        texts = row.get('source_texts', [])
        row['source_texts'] = [text[:600] for text in texts]
        if texts:
            row['attachment_reading_scope'] = 'preview_only_use_attachment_tools_for_further_reading'
        for item in row.get('source_attachments', []):
            item.pop('positions', None)
    return result
