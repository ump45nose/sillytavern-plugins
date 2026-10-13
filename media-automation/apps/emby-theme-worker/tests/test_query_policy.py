from pathlib import Path
from emby_theme_worker.models import MediaItem
from emby_theme_worker.search_pipeline import queries
from emby_theme_worker.ytdlp_runner import _writable_cookie

def test_movie_queries_are_source_specific_and_bounded():
    item=MediaItem('1','角斗士','Gladiator',2000,'Movie','/Media/movie')
    assert queries(item,provider='bilibili')==['角斗士 主题曲']
    assert queries(item,provider='youtube')==['角斗士 原声','Gladiator main title','角斗士 主题曲']
    assert 'Gladiator soundtrack' in queries(item,provider='qqmusic')
    assert not any('end credits' in q or q.endswith(' music') for q in queries(item,provider='netease'))
    item.search_text='Now We Are Free Hans Zimmer'
    values=queries(item,provider='youtube')
    assert values[0]==item.search_text and len(values)<=4

def test_missing_optional_cookie_does_not_prevent_download(tmp_path):
    with _writable_cookie(str(tmp_path/'not-provided.txt')) as cookie:
        assert cookie is None

def test_platform_cookies_are_not_shared(monkeypatch,tmp_path):
    from emby_theme_worker.audio import AudioProcessor
    import emby_theme_worker.audio as module
    captured=[]
    def download(url,**kwargs):
        captured.append(kwargs['cookie_file'])
        Path(str(kwargs['output_template']).replace('%(ext)s','mp3')).write_bytes(b'fake')
    monkeypatch.setattr(module,'ytdlp_download',download)
    audio=AudioProcessor(45,'192k',30,{'youtube':'private-youtube-cookie'})
    audio._ytdlp('https://music.163.com/#/song?id=1','netease',tmp_path)
    assert captured==[None]

def test_bilibili_resolves_flat_entries_without_titles(monkeypatch):
    import httpx
    from emby_theme_worker.models import Candidate
    from emby_theme_worker.providers import Providers
    p=Providers([],5,None,{})
    monkeypatch.setattr(p,'_ytdlp_search',lambda *args:[Candidate('bilibili','','https://www.bilibili.com/video/BV1test')])
    monkeypatch.setattr(p.http,'get',lambda *args,**kwargs:httpx.Response(200,request=httpx.Request('GET','https://api.bilibili.com/'),json={'code':0,'data':{'result':[{'bvid':'BV1test','title':'角斗士 <em>主题曲</em> &amp; 原声','duration':'4:15'}]}}))
    item=MediaItem('1','角斗士','Gladiator',2000,'Movie','/Media/movie')
    try:
        found=p.bilibili(item)
        assert found[0].title=='角斗士 主题曲 & 原声' and found[0].duration==255
    finally:p.close()
