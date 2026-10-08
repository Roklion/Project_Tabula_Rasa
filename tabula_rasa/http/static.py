"""Vite emits content-hashed assets; missing assets retain their real 404."""

from starlette.staticfiles import StaticFiles


class HashedAssets(StaticFiles):
    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        if response.status_code == 200:
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return response
