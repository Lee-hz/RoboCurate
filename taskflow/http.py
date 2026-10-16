"""Local-only workflow routes. Uploaded videos never become executable files."""
import mimetypes
from pathlib import Path
import re
import uuid

from .media import VIDEO_EXTENSIONS


def byte_range(header, size):
    if not header:return 0,size-1,False
    match=re.fullmatch(r'bytes=(\d*)-(\d*)',header.strip())
    if not match or not any(match.groups()):raise ValueError('视频范围无效')
    a,b=match.groups()
    if not a:
        count=int(b)
        if count<1:raise ValueError('视频范围无效')
        start,end=max(0,size-count),size-1
    else:start,end=int(a),min(int(b),size-1) if b else size-1
    if not 0<=start<=end<size:raise ValueError('视频范围超出文件')
    return start,end,True


def upload(handler, query):
    flow=handler.library.taskflow
    name=Path(query.get('name',['video.mp4'])[0]).name
    suffix=Path(name).suffix.lower()
    size=int(handler.headers.get('Content-Length','0'))
    if suffix not in VIDEO_EXTENSIONS or not 0<size<=1024**3:
        handler.close_connection=True
        raise ValueError('支持常见视频文件，单个文件不超过1GB')
    folder=flow.root/'uploads'/uuid.uuid4().hex;folder.mkdir(parents=True)
    partial=folder/'upload.part';destination=folder/name
    try:
        handler.connection.settimeout(60)
        with partial.open('xb') as stream:
            remaining=size
            while remaining:
                block=handler.rfile.read(min(1024**2,remaining))
                if not block:raise ValueError('视频上传中断，请重试')
                stream.write(block);remaining-=len(block)
        partial.replace(destination)
        asset=flow.add_asset(dict(kind='video',path=str(destination)))
        return handler._json(asset,status=201)
    except Exception:
        partial.unlink(missing_ok=True);destination.unlink(missing_ok=True)
        folder.rmdir();handler.close_connection=True
        raise


def video(handler, asset):
    source=asset['source']
    if source['kind']!='video':raise ValueError('此记录通过逐帧预览播放')
    handler.library.taskflow.media.unchanged(asset)
    path=Path(source['path']);size=path.stat().st_size
    try:start,end,partial=byte_range(handler.headers.get('Range'),size)
    except ValueError:
        handler.send_response(416);handler.send_header('Content-Range',f'bytes */{size}')
        handler.send_header('Content-Length','0');handler.end_headers();return
    handler.send_response(206 if partial else 200)
    handler.send_header('Content-Type',mimetypes.guess_type(path.name)[0] or 'video/mp4')
    handler.send_header('Accept-Ranges','bytes');handler.send_header('Content-Length',str(end-start+1))
    handler.send_header('Cache-Control','private, no-cache')
    if partial:handler.send_header('Content-Range',f'bytes {start}-{end}/{size}')
    handler.end_headers()
    with path.open('rb') as stream:
        stream.seek(start);remaining=end-start+1
        while remaining:
            block=stream.read(min(256*1024,remaining))
            if not block:break
            handler.wfile.write(block);remaining-=len(block)


def get(handler, route, query):
    flow=handler.library.taskflow;identifier=query.get('id',[''])[0]
    if route=='/api/taskflow':return handler._json(flow.overview(),cache='no-store')
    if route=='/api/taskflow/connection':return handler._json(flow.vlm.connection_settings(),cache='no-store')
    if route in ('/api/taskflow/state','/api/taskflow/feedback'):
        from .signals import StateEvidence
        asset=flow.get('assets',identifier);flow.media.unchanged(asset)
        evidence=StateEvidence(flow.library,asset)
        return handler._json(evidence.playback() if route.endswith('/feedback') else evidence.public(),cache='no-store')
    if route=='/api/taskflow/run':return handler._json(flow.public_run(identifier),cache='no-store')
    if route=='/api/taskflow/frame-index':
        asset=flow.get('assets',identifier);flow.media.unchanged(asset)
        source=asset['source']
        if source['kind']!='recording' or source.get('snapshot'):raise ValueError('此素材不支持原始帧回放')
        return handler._json(flow.library.frame_store.public_index(source['id']),cache='private, no-cache')
    if route=='/api/taskflow/template':return handler._json(flow.get('templates',identifier),cache='no-store')
    if route=='/api/taskflow/job':return handler._json(flow.get('jobs',identifier),cache='no-store')
    if route=='/api/taskflow/frame':
        flow.valid_id(identifier)
        return handler._send((flow.media.frame_root/(identifier+'.jpg')).read_bytes(),'image/jpeg',cache='private, max-age=3600')
    if route=='/api/taskflow/preview':
        asset=flow.get('assets',identifier);flow.media.unchanged(asset)
        frame=flow.media.frame(asset,float(query.get('t',['0'])[0]),query.get('cam',[None])[0])
        return handler._send(Path(frame['path']).read_bytes(),'image/jpeg',cache='private, no-cache')
    if route=='/api/taskflow/video':return video(handler,flow.get('assets',identifier))
    return handler._json(dict(error='未知工作流请求'),status=404)


def post(handler, route, body):
    flow=handler.library.taskflow
    if route=='/api/taskflow/connection':return handler._json(flow.connection(body),cache='no-store')
    if route=='/api/taskflow/assets':return handler._json(flow.add_asset(body.get('source')),status=201)
    if route=='/api/taskflow/jobs':return handler._json(flow.submit(body),status=202)
    if route=='/api/taskflow/cancel':return handler._json(flow.cancel(body.get('id')))
    if route=='/api/taskflow/template':return handler._json(flow.update_template(body.get('id'),body))
    if route=='/api/taskflow/segments':return handler._json(flow.edit_segments(body.get('id'),body))
    if route=='/api/taskflow/review':return handler._json(flow.review_segment(body.get('id'),body))
    return handler._json(dict(error='未知工作流请求'),status=404)
