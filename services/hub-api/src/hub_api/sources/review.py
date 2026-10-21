from .base import Adapter


class Review:
    def __init__(self, client, settings):
        self.client, self.settings = client, settings

    async def request(self, method, path, **kwargs):
        return await self.client.request(method, self.settings.review_url.rstrip('/')+path,
            headers={'Authorization':'Bearer '+self.settings.review_token.get_secret_value()}, **kwargs)

    async def fetch(self):
        response=await self.request('GET','/v1/stage')
        response.raise_for_status()
        raw=response.json()
        data={key:raw[key] for key in ('mainline','cycle','goals','reviews','close')}
        if (not isinstance(data['reviews'],dict) or not isinstance(data['close'],dict)
            or not isinstance(data['goals'],list) or data['close']['status'] not in ('none','preclose','awaiting_close','closed')):
            raise ValueError('invalid review payload')
        for kind in ('daily','weekly'):
            row=data['reviews'][kind]
            if row is not None:
                for key in ('id','label','status','prepared_at','expires_at'): row[key]
        return {**data, '_partial':response.headers.get('X-Review-Partial')=='true'}

    def adapter(self):
        return Adapter('review','Personal Review',60,self.fetch if self.settings.review_token else None)
