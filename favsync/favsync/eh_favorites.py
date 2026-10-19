"""EH favorites listing with checked pagination and the pinned gallery-dl transport."""
import argparse
from html import unescape
import logging
import re
from urllib.parse import parse_qsl, urljoin, urlsplit

from gallery_dl import config, exception, job, output, text
from gallery_dl.extractor.common import Message
from gallery_dl.extractor.exhentai import (
    ExhentaiFavoriteExtractor, ExhentaiGalleryExtractor,
)


class FavoritesExtractor(ExhentaiFavoriteExtractor):
    def items(self):
        self.login()
        url = self.search_url + "?page=0"
        visited = set()
        while True:
            parts = urlsplit(url)
            if (parts.scheme != "https" or parts.netloc != urlsplit(self.root).netloc
                    or parts.path != "/favorites.php"):
                raise exception.ExtractionError("Invalid favorites pagination URL")
            cursor = tuple(sorted(parse_qsl(parts.query, keep_blank_values=True)))
            if cursor in visited:
                raise exception.ExtractionError("Repeated favorites pagination cursor")
            visited.add(cursor)
            page = self.request(url).text
            next_url = text.extr(page, 'nexturl="', '"', None)
            if next_url is None:
                # Never guess another page from an unrecognized response. That
                # makes login/error pages loop until the subprocess timeout.
                if '>No hits found</p>' not in page and 'class="ptdd">&gt;<' not in page:
                    raise exception.ExtractionError("Missing favorites pagination")
                next_url = ""
            seen = set()
            for match in re.finditer(ExhentaiGalleryExtractor.pattern, page):
                gid, token = match[2], match[3]
                if gid in seen:
                    continue
                seen.add(gid)
                yield Message.Queue, match[0].rstrip("/") + "/", {
                    "gallery_id": int(gid), "gallery_token": token,
                    "_extractor": ExhentaiGalleryExtractor,
                }
            if not next_url:
                return
            url = urljoin(url, unescape(next_url))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config-ignore", action="store_true")
    parser.add_argument("-c", required=True)
    parser.add_argument("-j", action="store_true")
    parser.add_argument("url")
    args = parser.parse_args(argv)
    output.initialize_logging(logging.WARNING)
    config.clear()
    config.load((args.c,), strict=True)
    return job.DataJob(FavoritesExtractor.from_url(args.url)).run()


if __name__ == "__main__":
    raise SystemExit(main())
