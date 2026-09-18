"""Local attachment ingestion. Files are data and never executed."""
import base64
import io
import json
import re
import uuid
import zipfile
from pathlib import Path
from xml.etree import ElementTree


MAX_BYTES=8*1024*1024
MAX_TEXT=16000


class Attachments:
    def __init__(self,directory):
        self.directory=Path(directory)/'attachments'
        self.directory.mkdir(parents=True,exist_ok=True)

    def upload(self,payload):
        name=payload.get('name','')
        if not isinstance(name,str) or not name or len(name)>240:
            raise ValueError('파일 이름을 확인해 주세요.')
        name=name.replace('\\','/').rsplit('/',1)[-1]
        name=re.sub(r'[\x00-\x1f]','',name)
        encoded=payload.get('data','')
        if not isinstance(encoded,str) or len(encoded)>MAX_BYTES*1.4:
            raise ValueError('첨부파일은 파일당 8MB까지 읽을 수 있어요.')
        try:raw=base64.b64decode(encoded,validate=True)
        except (ValueError,TypeError):raise ValueError('파일 전송 형식을 확인해 주세요.') from None
        if not raw or len(raw)>MAX_BYTES:
            raise ValueError('빈 파일이거나 8MB 제한을 넘었습니다.')
        suffix=Path(name).suffix.lower()
        text='';image='';mime='';limited=False
        if suffix in ('.txt','.md','.csv','.json','.log'):
            try:text=raw.decode('utf-8-sig')
            except UnicodeDecodeError:
                try:text=raw.decode('cp949')
                except UnicodeDecodeError:raise ValueError('UTF-8 또는 한글 텍스트 파일을 선택해 주세요.') from None
            if '\x00' in text:raise ValueError('텍스트 파일로 읽을 수 없습니다.')
        elif suffix=='.pdf':
            try:
                from pypdf import PdfReader
                reader=PdfReader(io.BytesIO(raw))
                if reader.is_encrypted:raise ValueError('암호가 걸린 PDF는 해제한 뒤 첨부해 주세요.')
                limited=len(reader.pages)>20
                for page in reader.pages[:20]:
                    text+=(page.extract_text() or '')+'\n'
                    if len(text)>MAX_TEXT:break
            except ImportError:raise ValueError('PDF 읽기에 pypdf가 필요합니다. 텍스트 파일로 첨부할 수도 있어요.') from None
            except ValueError:raise
            except Exception:raise ValueError('이 PDF를 읽지 못했습니다. 텍스트 PDF인지 확인해 주세요.') from None
        elif suffix=='.docx':
            try:
                with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                    info=archive.getinfo('word/document.xml')
                    if info.file_size>8*1024*1024:raise ValueError('문서 내용이 너무 큽니다.')
                    xml=archive.read(info)
                    if b'<!DOCTYPE' in xml or b'<!ENTITY' in xml:raise ValueError('지원하지 않는 문서 형식입니다.')
                    root=ElementTree.fromstring(xml)
                    ns={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
                    # Word stores these visible separators as empty XML elements.
                    separators={f'{{{ns["w"]}}}tab':'\t',f'{{{ns["w"]}}}br':'\n',f'{{{ns["w"]}}}cr':'\n'}
                    for element in root.iter():
                        if element.tag in separators:element.text=separators[element.tag]
                    text='\n'.join(''.join(p.itertext()) for p in root.findall('.//w:p',ns))
            except ValueError:raise
            except Exception:raise ValueError('DOCX 내용을 읽지 못했습니다.') from None
        elif suffix in ('.png','.jpg','.jpeg','.webp'):
            if raw.startswith(b'\x89PNG\r\n\x1a\n'):mime='image/png'
            elif raw.startswith(b'\xff\xd8\xff'):mime='image/jpeg'
            elif raw[:4]==b'RIFF' and raw[8:12]==b'WEBP':mime='image/webp'
            else:raise ValueError('PNG, JPEG, WebP 이미지 파일을 선택해 주세요.')
            image=encoded
        else:
            raise ValueError('TXT, MD, CSV, JSON, PDF, DOCX 또는 이미지를 첨부해 주세요.')
        if not image and not text.strip():
            raise ValueError('읽을 수 있는 텍스트가 없습니다. 스캔 PDF는 텍스트를 추출한 뒤 첨부해 주세요.')
        item={'id':uuid.uuid4().hex,'name':name,'size':len(raw),'text':text[:MAX_TEXT],
              'image':image,'mime':mime,'truncated':limited or len(text)>MAX_TEXT}
        path=self.directory/(item['id']+'.json')
        path.write_text(json.dumps(item,ensure_ascii=False),encoding='utf-8')
        return self.public(item)

    def load(self,identifier):
        if not isinstance(identifier,str) or not re.fullmatch(r'[a-f0-9]{32}',identifier):
            raise ValueError('첨부파일 식별자가 올바르지 않습니다.')
        path=self.directory/(identifier+'.json')
        if not path.exists():raise ValueError('첨부파일을 다시 선택해 주세요.')
        return json.loads(path.read_text(encoding='utf-8'))

    @staticmethod
    def public(item):
        return {k:item[k] for k in ('id','name','size','truncated')} | {'kind':'image' if item['image'] else 'document','characters':len(item['text'])}
