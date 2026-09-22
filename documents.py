"""Bounded read-only document extraction in a timeout-controlled child process."""
import json
import secrets
import string
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET
from safe_net import Rejected, safe_name

TEXT_EXT={'.txt','.md','.csv','.json','.log','.py','.js','.ts','.yaml','.yml','.ini','.xml','.html','.css','.sql','.toml'}

def extract(path, original_name, limit=40000):
    p=Path(path);ext=Path(original_name).suffix.lower()
    if p.stat().st_size>30*1024*1024:raise Rejected('文件超过 30MB')
    if ext in TEXT_EXT:
        raw=p.read_bytes()[:1024*1024]
        for enc in ('utf-8-sig','gb18030'):
            try:text=raw.decode(enc);break
            except UnicodeError:pass
        else:raise Rejected('无法识别文本编码')
    elif ext=='.pdf':
        from pypdf import PdfReader
        reader=PdfReader(p,strict=True)
        if reader.is_encrypted:raise Rejected('请先解密 PDF 再上传')
        parts=[];n=0
        for page in reader.pages[:30]:
            s=page.extract_text() or '';parts.append(s);n+=len(s)
            if n>=limit:break
        text='\n'.join(parts)
        if len(reader.pages)>30:text+='\n[仅分析前30页]'
    elif ext in {'.docx','.xlsx','.pptx'}:
        with zipfile.ZipFile(p) as z:
            infos=z.infolist()
            if len(infos)>3000 or sum(i.file_size for i in infos)>60*1024*1024:raise Rejected('文档展开大小超限')
            if any(i.file_size>10*1024*1024 or i.file_size/max(1,i.compress_size)>200 for i in infos):raise Rejected('拒绝异常压缩比文档')
            if '[Content_Types].xml' not in z.namelist():raise Rejected('不是有效 Office 文档')
            if ext=='.docx':names=['word/document.xml']
            elif ext=='.pptx':names=sorted(n for n in z.namelist() if n.startswith('ppt/slides/slide') and n.endswith('.xml'))
            else:names=sorted([n for n in z.namelist() if n=='xl/sharedStrings.xml' or (n.startswith('xl/worksheets/sheet') and n.endswith('.xml'))],key=lambda n:(n!='xl/sharedStrings.xml',n))
            parts=[];chars=0;shared=[]
            for name in names:
                raw=z.read(name)
                if b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():raise Rejected('文档包含不允许的实体声明')
                tree=ET.fromstring(raw)
                if name=='xl/sharedStrings.xml':
                    shared=[''.join(x.itertext()) for x in tree];continue
                if ext=='.xlsx':
                    for row in tree.iter('{http://schemas.openxmlformats.org/spreadsheetml/2006/main}row'):
                        vals=[]
                        for cell in row:
                            value=''.join(cell.itertext())
                            if cell.get('t')=='s':
                                try:value=shared[int(value)]
                                except (ValueError,IndexError):value='[无法解析单元格]'
                            vals.append(value)
                        parts.append(' | '.join(vals))
                else:parts.append(' '.join(x.text or '' for x in tree.iter() if x.tag.endswith('}t')))
                chars=sum(len(s) for s in parts)
                if chars>=limit:break
            text='\n'.join(parts)
    else:raise Rejected('暂不分析此格式。支持文本、PDF、docx、xlsx、pptx；压缩包只可转存，不自动解压执行。')
    if not text.strip():raise Rejected('未提取到文字，扫描图片 PDF 需要先 OCR')
    return text[:limit]+('\n[内容已截取，未分析剩余部分]' if len(text)>limit else '')

def encrypted_archive(source, name, directory):
    import pyzipper
    src=Path(source)
    password=''.join(secrets.choice(string.ascii_letters+string.digits) for _ in range(12))
    original=safe_name(name)
    target=Path(directory)/(safe_name(Path(original).stem)[:55]+'_密码-'+password+'.zip')
    with pyzipper.AESZipFile(target,'x',compression=zipfile.ZIP_DEFLATED,encryption=pyzipper.WZ_AES) as z:
        z.setpassword(password.encode());z.setencryption(pyzipper.WZ_AES,nbits=256);z.write(src,arcname=original)
    with pyzipper.AESZipFile(target) as z:
        z.setpassword(password.encode())
        if z.testzip() is not None:raise Rejected('加密压缩包校验失败')
    return target,password

if __name__=='__main__':
    try:print(json.dumps({'text':extract(sys.argv[1],sys.argv[2],int(sys.argv[3]))},ensure_ascii=False))
    except Exception as e:
        print(json.dumps({'error':str(e) if isinstance(e,Rejected) else '文件无法安全解析'},ensure_ascii=False));sys.exit(1)
