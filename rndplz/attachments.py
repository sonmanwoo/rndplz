"""Local attachment ingestion. Files are data and never executed."""
import base64
import io
import hashlib
import threading
import json
import re
import uuid
import zipfile
from pathlib import Path
from xml.etree import ElementTree
from .https_documents import FetchError, fetch_document, extract_web_text


# MAX_BYTES remains the legacy profile limit imported by Profiles.
MAX_BYTES=8*1024*1024
MAX_FILE_BYTES=10*1024*1024
MAX_BASE64_CHARS=4*((MAX_FILE_BYTES+2)//3)
MAX_UPLOAD_BODY=MAX_BASE64_CHARS+4096
MAX_TEXT=16000
MAX_PDF_PAGES=100
MAX_SLIDES=100
MAX_UNITS=1000
MAX_XML_BYTES=8*1024*1024
MAX_XML_TOTAL=32*1024*1024
MAX_ARCHIVE_BYTES=64*1024*1024
MAX_ARCHIVE_ENTRIES=4096
MAX_HTTPS_BODY=4096
_HTTPS_SLOTS=threading.BoundedSemaphore(2)


class AttachmentError(ValueError):
    MESSAGES={
        'busy':'다른 자료를 읽는 중입니다. 잠시 후 다시 시도해 주세요.',
        'invalid_name':'파일 이름을 확인해 주세요.',
        'invalid_encoding':'파일 전송 형식을 확인해 주세요.',
        'too_large':'첨부파일은 파일당 10MiB까지 읽을 수 있어요.',
        'empty_file':'빈 파일입니다. 내용이 있는 파일을 선택해 주세요.',
        'empty_text':'읽을 수 있는 본문이 없습니다. 텍스트가 포함된 문서를 선택해 주세요.',
        'locked':'암호가 걸린 문서입니다. 잠금을 해제한 사본을 첨부해 주세요.',
        'corrupt':'문서 내용을 읽지 못했습니다. 정상적으로 열리는 파일을 다시 선택해 주세요.',
        'unsupported':'PDF, TXT, MD, HTML, HTM, PPTX, DOCX 또는 기존 지원 파일 형식을 선택해 주세요.',
        'unsupported_text':'UTF-8 또는 한글 텍스트 파일을 선택해 주세요.',
        'resource_limit':'문서 내부 내용이 안전한 처리 범위를 넘었습니다. 문서를 나누어 첨부해 주세요.',
        'parser_unavailable':'문서 읽기 기능을 사용할 수 없습니다. 잠시 후 다시 시도해 주세요.',
    }
    def __init__(self,reason):
        self.code='attachment_'+reason
        self.status=429 if reason=='busy' else 413 if reason in ('too_large','resource_limit') else 415 if reason=='unsupported' else 503 if reason=='parser_unavailable' else 400
        super().__init__(self.MESSAGES[reason])


def _collect(units,total,kind,unit_limit,method,joiner='\n'):
    """Offsets refer to saved extracted text, never guessed document layout."""
    chunks=[]; spans=[]; size=0; processed=0; reasons=[]
    for index,part in units:
        if processed>=unit_limit:
            reasons.append(kind+'_limit');break
        processed+=1
        separator=joiner if chunks else ''
        available=max(0,MAX_TEXT-size-len(separator))
        kept=part[:available]
        if separator and size<MAX_TEXT:
            chunks.append(separator);size+=len(separator)
        start=size
        chunks.append(kept);size+=len(kept)
        if kept:spans.append({'kind':kind,'index':index,'start':start,'end':size})
        if len(part)>available or (size>=MAX_TEXT and processed<total):
            reasons.append('text_limit');break
    if processed<total and not reasons:reasons.append(kind+'_limit')
    text=''.join(chunks)
    return text,spans,{'status':'partial' if reasons else 'complete','method':method,
        'unit':kind,'total_units':total,'processed_units':processed,
        'character_limit':MAX_TEXT,'unit_limit':unit_limit,'limits':reasons,
        'location_basis':'extracted_text_offsets','ocr':False}


def _archive(raw):
    try:archive=zipfile.ZipFile(io.BytesIO(raw))
    except (zipfile.BadZipFile,OSError,ValueError):raise AttachmentError('corrupt') from None
    infos=archive.infolist()
    if len(infos)>MAX_ARCHIVE_ENTRIES or sum(i.file_size for i in infos)>MAX_ARCHIVE_BYTES:
        archive.close();raise AttachmentError('resource_limit')
    if len({i.filename for i in infos})!=len(infos):
        archive.close();raise AttachmentError('corrupt')
    if any(i.flag_bits&1 for i in infos):
        archive.close();raise AttachmentError('locked')
    return archive


def _xml(archive,name,budget):
    try:
        info=archive.getinfo(name)
        budget[0]+=info.file_size
        if info.file_size>MAX_XML_BYTES or budget[0]>MAX_XML_TOTAL:
            raise AttachmentError('resource_limit')
        raw=archive.read(info)
        # Reject entity declarations in UTF-8/16/32. No external resolution or extraction to disk.
        declaration=raw.replace(b'\x00',b'').upper()
        if b'<!DOCTYPE' in declaration or b'<!ENTITY' in declaration:
            raise AttachmentError('unsupported')
        return ElementTree.fromstring(raw)
    except AttachmentError:raise
    except NotImplementedError:raise AttachmentError('unsupported') from None
    except Exception:
        raise AttachmentError('corrupt') from None


def _paragraphs(root,namespace,limitations=None):
    ns='{'+namespace+'}'
    math='{http://schemas.openxmlformats.org/officeDocument/2006/math}'
    if limitations is not None and any(element.tag.startswith(math) and element.tag not in
            {math+'oMath',math+'oMathPara',math+'r',math+'t'} for element in root.iter()):
        limitations.append('math_structure')
    paragraphs=[]
    for paragraph in root.iter(ns+'p'):
        pieces=[]
        for element in paragraph.iter():
            if element.tag in (ns+'t',math+'t'):pieces.append(element.text or '')
            elif element.tag==ns+'tab':pieces.append('\t')
            elif element.tag in (ns+'br',ns+'cr'):pieces.append('\n')
        paragraphs.append(''.join(pieces))
    return paragraphs


def _office_limitations(collected,limitations):
    # Math text is preserved; layout-dependent operators are never invented.
    if limitations:
        collected[2]['status']='partial'
        collected[2]['limits']=list(dict.fromkeys(collected[2]['limits']+limitations))
    return collected


def _office(raw,suffix):
    with _archive(raw) as archive:
        budget=[0];limitations=[]
        if suffix=='.docx':
            root=_xml(archive,'word/document.xml',budget)
            if root.tag!='{http://schemas.openxmlformats.org/wordprocessingml/2006/main}document':
                raise AttachmentError('corrupt')
            paragraphs=_paragraphs(root,'http://schemas.openxmlformats.org/wordprocessingml/2006/main',limitations)
            return _office_limitations(_collect(enumerate(paragraphs,1),len(paragraphs),'paragraph',MAX_UNITS,'ooxml_word_paragraphs'),limitations)
        ns={'p':'http://schemas.openxmlformats.org/presentationml/2006/main',
            'r':'http://schemas.openxmlformats.org/officeDocument/2006/relationships'}
        root=_xml(archive,'ppt/presentation.xml',budget)
        if root.tag!='{'+ns['p']+'}presentation':raise AttachmentError('corrupt')
        rels=_xml(archive,'ppt/_rels/presentation.xml.rels',budget)
        links={}
        for rel in rels:
            key=rel.get('Id')
            if key in links:raise AttachmentError('corrupt')
            links[key]=rel
        ids=root.findall('./p:sldIdLst/p:sldId',ns)
        def slides():
            for index,slide in enumerate(ids[:MAX_SLIDES],1):
                rel=links.get(slide.get('{'+ns['r']+'}id'))
                if rel is None:raise AttachmentError('corrupt')
                if rel.get('TargetMode','Internal')!='Internal':raise AttachmentError('unsupported')
                if rel.get('Type')!=ns['r']+'/slide':raise AttachmentError('corrupt')
                target=rel.get('Target','')
                # Only package-owned slide XML referenced in presentation order is readable.
                match=re.fullmatch(r'(?:/ppt/)?(slides/slide[0-9]+\.xml)',target)
                if match is None:raise AttachmentError('unsupported')
                slide_root=_xml(archive,'ppt/'+match.group(1),budget)
                if slide_root.tag!='{'+ns['p']+'}sld':raise AttachmentError('corrupt')
                yield index,'\n'.join(_paragraphs(slide_root,'http://schemas.openxmlformats.org/drawingml/2006/main',limitations))
        return _office_limitations(_collect(slides(),len(ids),'slide',MAX_SLIDES,'ooxml_slide_paragraphs'),limitations)


def _html(raw):
    # Reuse static HTTPS extraction; local files never fetch embedded resources.
    try:
        try:text=extract_web_text(raw,'text/html')
        except FetchError as exc:
            if exc.code!='https_invalid_response':raise
            text=extract_web_text(raw,'text/html; charset=cp949')
    except FetchError as exc:
        raise AttachmentError('empty_text' if exc.code=='https_empty' else 'unsupported_text') from None
    lines=text.splitlines(keepends=True)
    return _collect(enumerate(lines,1),len(lines),'line',MAX_UNITS,'html_static_text_lines',joiner='')


def _pdf(raw):
    try:
        from pypdf import PdfReader
        from pypdf.errors import DependencyError
    except ImportError:raise AttachmentError('parser_unavailable') from None
    if b'%PDF-' not in raw[:1024]:raise AttachmentError('corrupt')
    try:
        reader=PdfReader(io.BytesIO(raw))
        if reader.is_encrypted:raise AttachmentError('locked')
        total=len(reader.pages)
        units=((n+1,(reader.pages[n].extract_text() or '')+'\n') for n in range(min(total,MAX_PDF_PAGES)))
        return _collect(units,total,'page',MAX_PDF_PAGES,'pdf_text',joiner='')
    except AttachmentError:raise
    except DependencyError:raise AttachmentError('parser_unavailable') from None
    except Exception:raise AttachmentError('corrupt') from None


class Attachments:
    def __init__(self,directory):
        self.directory=Path(directory)/'attachments'
        self.directory.mkdir(parents=True,exist_ok=True)

    def upload(self,payload):
        # User-supplied source/provenance is never accepted as an authority.
        return self._upload(payload)

    def upload_url(self,payload):
        if not isinstance(payload,dict) or set(payload)!={'url'}:
            raise FetchError('https_invalid_url')
        if not _HTTPS_SLOTS.acquire(blocking=False):raise AttachmentError('busy')
        try:
            document=fetch_document(payload['url'])
            raw=document['raw'];source=dict(document['source'])
            if not isinstance(raw,bytes) or not 0<len(raw)<=MAX_FILE_BYTES:
                raise FetchError('https_invalid_response')
            if source.get('sha256')!=hashlib.sha256(raw).hexdigest() or source.get('bytes')!=len(raw):
                raise FetchError('https_invalid_response')
            decoded=None;name=document['name']
            if document['document_kind'] in ('html','text'):
                decoded=document['text']
                if not isinstance(decoded,str) or not decoded.strip():raise FetchError('https_empty')
                if document['document_kind']=='html':name=Path(name).stem+'.txt'
                converted=decoded.encode('utf-8')
                source['conversion']={'method':'html_static_text' if document['document_kind']=='html' else 'charset_decoded_text',
                    'encoding':'utf-8','sha256':hashlib.sha256(converted).hexdigest(),'bytes':len(converted)}
            return self._upload({'name':name,'data':base64.b64encode(raw).decode('ascii')},
                                _source=source,_decoded_text=decoded)
        finally:
            _HTTPS_SLOTS.release()

    def _upload(self,payload,*,_source=None,_decoded_text=None):
        name=payload.get('name','')
        if not isinstance(name,str) or not name or len(name)>240:
            raise AttachmentError('invalid_name')
        name=name.replace('\\','/').rsplit('/',1)[-1]
        name=re.sub(r'[\x00-\x1f]','',name)
        if not name:raise AttachmentError('invalid_name')
        encoded=payload.get('data','')
        if not isinstance(encoded,str):raise AttachmentError('invalid_encoding')
        if len(encoded)>MAX_BASE64_CHARS:raise AttachmentError('too_large')
        try:raw=base64.b64decode(encoded,validate=True)
        except (ValueError,TypeError):raise AttachmentError('invalid_encoding') from None
        if not raw:raise AttachmentError('empty_file')
        if len(raw)>MAX_FILE_BYTES:raise AttachmentError('too_large')
        suffix=Path(name).suffix.lower()
        text='';image='';mime='';spans=[];extraction=None
        if suffix in ('.txt','.md','.csv','.json','.log'):
            if _decoded_text is not None:
                text=_decoded_text
            else:
                try:text=raw.decode('utf-8-sig')
                except UnicodeDecodeError:
                    try:text=raw.decode('cp949')
                    except UnicodeDecodeError:raise AttachmentError('unsupported_text') from None
            if '\x00' in text:raise AttachmentError('unsupported_text')
            lines=text.splitlines(keepends=True)
            text,spans,extraction=_collect(enumerate(lines,1),len(lines),'line',MAX_UNITS,'decoded_text_lines',joiner='')
        elif suffix in ('.html','.htm'):text,spans,extraction=_html(raw)
        elif suffix=='.pdf':text,spans,extraction=_pdf(raw)
        elif suffix in ('.docx','.pptx'):text,spans,extraction=_office(raw,suffix)
        elif suffix in ('.png','.jpg','.jpeg','.webp'):
            if raw.startswith(b'\x89PNG\r\n\x1a\n'):mime='image/png'
            elif raw.startswith(b'\xff\xd8\xff'):mime='image/jpeg'
            elif raw[:4]==b'RIFF' and raw[8:12]==b'WEBP':mime='image/webp'
            else:raise AttachmentError('unsupported')
            image=encoded
        else:raise AttachmentError('unsupported')
        if not image and not text.strip():raise AttachmentError('empty_text')
        item={'id':uuid.uuid4().hex,'name':name,'size':len(raw),'text':text,
              'image':image,'mime':mime,'truncated':bool(extraction and extraction['status']=='partial')}
        if extraction is not None:item.update(extraction=extraction,source_spans=spans)
        if _source is not None:
            item['source']={**_source,'extracted_text_sha256':hashlib.sha256(text.encode('utf-8')).hexdigest()}
        path=self.directory/(item['id']+'.json')
        path.write_text(json.dumps(item,ensure_ascii=False),encoding='utf-8')
        return self.public(item)

    def load(self,identifier):
        if not isinstance(identifier,str) or not re.fullmatch(r'[a-f0-9]{32}',identifier):
            raise ValueError('첨부파일 식별자가 올바르지 않습니다.')
        path=self.directory/(identifier+'.json')
        if not path.exists():raise ValueError('첨부파일을 다시 선택해 주세요.')
        return json.loads(path.read_text(encoding='utf-8'))

    def source(self,identifier):
        item=self.load(identifier)
        return {**self.public(item),'text':item['text'],'image':item['image'],'mime':item['mime'],
                'source_spans':item.get('source_spans',[])}

    @staticmethod
    def public(item):
        view={k:item[k] for k in ('id','name','size','truncated')} | {'kind':'image' if item['image'] else 'document','characters':len(item['text'])}
        if isinstance(item.get('extraction'),dict):view['extraction']=item['extraction']
        if isinstance(item.get('source'),dict):view['source']=item['source']
        return view
