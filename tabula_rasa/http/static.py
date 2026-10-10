"""Vite emits content-hashed assets; missing assets retain their real 404."""

from starlette.staticfiles import StaticFiles
from starlette.responses import FileResponse


class HashedAssets(StaticFiles):
    def __init__(self, *, asset_page_index=None, **kwargs):
        super().__init__(**kwargs)
        self.asset_page_index = asset_page_index

    async def get_response(self, path, scope):
        # The asset register shares /assets with Vite's static bundle namespace.
        # Only extensionless single-segment HTML routes can reach its SPA; real
        # bundle files and missing JS/CSS keep StaticFiles' behavior.
        accept = dict(scope.get('headers', [])).get(b'accept', b'').decode('latin-1')
        if (self.asset_page_index is not None and scope['method'] in {'GET', 'HEAD'}
                and 'text/html' in accept and (path == '.' or ('.' not in path and '/' not in path and '\\' not in path))):
            return FileResponse(self.asset_page_index, headers={'Cache-Control': 'no-cache'})
        response = await super().get_response(path, scope)
        if response.status_code == 200:
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response
