from dataclasses import dataclass

from .sources.base import SourceManager
from .store import Store


@dataclass
class HubContext:
    sources: SourceManager
    store: Store
    module_sources: dict
    media_links: dict

    @property
    def now(self):
        return self.sources.now
