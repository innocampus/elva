import anyio

from elva.component import Component


class TextRenderer(Component):
    def __init__(self, ytext, path):
        self.ytext = ytext
        self.modified = False
        self.path = anyio.Path(path)

    def _callback(self, event):
        self.modified = True

    async def before(self):
        mode = "r+" if await self.path.exists() else "w"
        self.file = await anyio.open_file(self.path, mode)
        self.log.info(f"opened file {self.path}")

    async def run(self):
        self.ytext.observe(self._callback)

    async def cleanup(self):
        await self.write()
        await self.file.aclose()
        self.log.info(f"saved and closed file {self.path}")

    async def write(self):
        if self.modified:
            self.log.info(f"writing to file {self.path}")
            await self.file.truncate(0)
            await self.file.seek(0)
            await self.file.write(str(self.ytext))
            self.modified = False
