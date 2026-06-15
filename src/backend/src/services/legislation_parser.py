#!/usr/bin/env python3
"""
Search official legislation portals by keyword and return links to law texts.

Examples:
  python legislation_parser.py "ochrona zdrowia" --countries pl --limit 10
  python legislation_parser.py "salud publica" --countries es --limit 10
  python legislation_parser.py "Gesundheitsschutz" --countries de --limit 10
  python legislation_parser.py "sante publique" --countries fr --limit 10
  python legislation_parser.py "health protection" --countries uk --limit 10

France/Legifrance requires PISTE credentials:
  set LEGIFRANCE_CLIENT_ID=...
  set LEGIFRANCE_CLIENT_SECRET=...
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import asdict, dataclass
from html import unescape
from html.parser import HTMLParser
from typing import Any
from urllib.error import HTTPError
from urllib.parse import quote, urlencode, urljoin
from urllib.request import Request, urlopen


USER_AGENT = "legislation-keyword-parser/0.1 (+research; contact: local)"
TIMEOUT = 30


@dataclass
class LegalResult:
    country: str
    title: str
    html_url: str | None = None
    pdf_url: str | None = None
    api_url: str | None = None
    source_id: str | None = None
    date: str | None = None
    status: str | None = None
    note: str | None = None


class HttpResponse:
    def __init__(self, url: str, status: int, headers: Any, body: bytes) -> None:
        self.url = url
        self.status_code = status
        self.headers = headers
        self.content = body
        content_type = headers.get("Content-Type", "") if headers else ""
        charset_match = re.search(r"charset=([\w-]+)", content_type, re.I)
        self.encoding = charset_match.group(1) if charset_match else "utf-8"

    @property
    def text(self) -> str:
        try:
            return self.content.decode(self.encoding, errors="replace")
        except LookupError:
            return self.content.decode("utf-8", errors="replace")

    def json(self) -> Any:
        return json.loads(self.text)

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code} for {self.url}: {self.text[:300]}")


class HttpSession:
    def __init__(self) -> None:
        self.headers = {
            "User-Agent": USER_AGENT,
            "Accept": "application/json, application/xml, text/html;q=0.9, */*;q=0.8",
        }

    def request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | bytes | None = None,
        json_body: Any | None = None,
        headers: dict[str, str] | None = None,
        auth: tuple[str, str] | None = None,
        timeout: int = TIMEOUT,
    ) -> HttpResponse:
        if params:
            separator = "&" if "?" in url else "?"
            url = url + separator + urlencode(params, doseq=True)

        body: bytes | None = None
        request_headers = dict(self.headers)
        if headers:
            request_headers.update(headers)

        if json_body is not None:
            body = json.dumps(json_body).encode("utf-8")
            request_headers["Content-Type"] = "application/json"
        elif isinstance(data, dict):
            body = urlencode(data).encode("utf-8")
            request_headers["Content-Type"] = "application/x-www-form-urlencoded"
        elif isinstance(data, bytes):
            body = data

        if auth:
            import base64

            token = base64.b64encode(f"{auth[0]}:{auth[1]}".encode("utf-8")).decode("ascii")
            request_headers["Authorization"] = f"Basic {token}"

        request = Request(url, data=body, headers=request_headers, method=method.upper())
        try:
            with urlopen(request, timeout=timeout) as response:
                return HttpResponse(
                    response.geturl(),
                    response.getcode(),
                    response.headers,
                    response.read(),
                )
        except HTTPError as exc:
            return HttpResponse(url, exc.code, exc.headers, exc.read())

    def get(self, url: str, **kwargs: Any) -> HttpResponse:
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> HttpResponse:
        return self.request("POST", url, **kwargs)


def get_session() -> HttpSession:
    return HttpSession()


def clean_text(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"\s+", " ", unescape(value)).strip()


def has_word(title: str, word: str) -> bool:
    return word.casefold() in title.casefold()


class LinkListParser(HTMLParser):
    """Small stdlib fallback for simple search result pages."""

    def __init__(self, base_url: str) -> None:
        super().__init__()
        self.base_url = base_url
        self.links: list[tuple[str, str, str | None]] = []
        self._href: str | None = None
        self._title: str | None = None
        self._chunks: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        attr = dict(attrs)
        self._href = attr.get("href")
        self._title = attr.get("title")
        self._chunks = []

    def handle_data(self, data: str) -> None:
        if self._href:
            self._chunks.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "a" or not self._href:
            return
        text = clean_text(" ".join(self._chunks)) or clean_text(self._title)
        href = urljoin(self.base_url, self._href)
        self.links.append((text, href, self._title))
        self._href = None
        self._title = None
        self._chunks = []


def parse_links(html: str, base_url: str) -> list[tuple[str, str, str | None]]:
    parser = LinkListParser(base_url)
    parser.feed(html)
    return parser.links


def search_poland(keyword: str, limit: int, session: HttpSession) -> list[LegalResult]:
    url = "https://api.sejm.gov.pl/eli/acts/search"
    params = {"keyword": keyword, "type": "Ustawa"}
    response = session.get(url, params=params, timeout=TIMEOUT)
    response.raise_for_status()
    data = response.json()

    results: list[LegalResult] = []
    for item in data.get("items", [])[:limit]:
        eli = item.get("ELI") or f"{item.get('publisher')}/{item.get('year')}/{item.get('pos')}"
        html_url = f"https://api.sejm.gov.pl/eli/acts/{eli}/text.html" if item.get("textHTML") else None
        pdf_url = f"https://api.sejm.gov.pl/eli/acts/{eli}/text.pdf" if item.get("textPDF") else None
        results.append(
            LegalResult(
                country="pl",
                title=clean_text(item.get("title")),
                html_url=html_url,
                pdf_url=pdf_url,
                api_url=f"https://api.sejm.gov.pl/eli/acts/{eli}",
                source_id=eli,
                date=item.get("announcementDate") or item.get("promulgation"),
                status=item.get("status") or item.get("inForce"),
            )
        )
    return results


def search_spain(keyword: str, limit: int, session: HttpSession) -> list[LegalResult]:
    # BOE has an official OpenData endpoint for consolidated legislation, but it is
    # strict and can return 500 for free text. The public legislation search page is
    # stable and exposes direct HTML and consolidated-text links.
    params = {
        "texto": keyword,
        "campo[0]": "tit",
        "sort_field[0]": "PESO",
        "sort_order[0]": "desc",
        "accion": "Buscar",
    }
    url = "https://www.boe.es/buscar/legislacion.php?" + urlencode(params)
    html = session.get(url, timeout=TIMEOUT).text
    results: list[LegalResult] = []
    seen: set[str] = set()

    blocks = re.findall(
        r'<li class="resultado-busqueda">(.*?)(?=<li class="resultado-busqueda">|</ul>\s*</div>)',
        html,
        flags=re.S,
    )
    for block in blocks:
        id_match = re.search(r"BOE-A-\d{4}-\d+", block)
        if not id_match:
            continue
        source_id = id_match.group(0)
        if source_id in seen:
            continue
        seen.add(source_id)

        title_match = re.search(r"<p>(.*?)</p>", block, flags=re.S)
        title = clean_text(re.sub(r"<.*?>", " ", title_match.group(1))) if title_match else source_id
        consolidated = re.search(r'href="([^"]*/buscar/act\.php\?id=[^"]+)"', block)
        official = re.search(r'href="([^"]*/buscar/doc\.php\?id=[^"]+)"', block)
        href = consolidated.group(1) if consolidated else official.group(1) if official else None
        if not href:
            continue
        href = urljoin(url, unescape(href))
        results.append(
            LegalResult(
                country="es",
                title=title,
                html_url=href,
                source_id=source_id,
                note="consolidated" if consolidated else "official BOE document",
            )
        )
        if len(results) >= limit:
            break
    return results


def search_germany(keyword: str, limit: int, session: HttpSession) -> list[LegalResult]:
    params = {"config": "Gesamt_bmjhome2005", "method": "and", "words": keyword}
    url = "https://www.gesetze-im-internet.de/cgi-bin/htsearch?" + urlencode(params)
    html = session.get(url, timeout=TIMEOUT).text

    results: list[LegalResult] = []
    seen: set[str] = set()
    for href, label in re.findall(r"<dt>.*?<a[^>]+href=\"([^\"]+)\"[^>]*>(.*?)</a>.*?</dt>", html, re.S):
        href = urljoin(url, unescape(href))
        if href in seen:
            continue
        seen.add(href)
        title = clean_text(re.sub(r"<.*?>", " ", label))
        html_url = href if href.endswith(".html") else href.rstrip("/") + "/index.html"
        results.append(
            LegalResult(
                country="de",
                title=title,
                html_url=html_url,
                source_id=href.rstrip("/").split("/")[-1],
            )
        )
        if len(results) >= limit:
            break
    return results


def search_italy(keyword: str, limit: int, session: HttpSession) -> list[LegalResult]:
    # Normattiva is mostly form-driven. This uses the public simple-search route and
    # extracts /uri-res/ links when they are present in the returned page.
    url = "https://www.normattiva.it/ricerca/semplice"
    html = session.post(url, data={"testoRicerca": keyword}, timeout=TIMEOUT).text
    links = parse_links(html, url)

    results: list[LegalResult] = []
    seen: set[str] = set()
    for text, href, title in links:
        if "normattiva.it" not in href or href in seen:
            continue
        if "/uri-res/" not in href and "/atto/" not in href and "/eli/" not in href:
            continue
        seen.add(href)
        results.append(
            LegalResult(
                country="it",
                title=clean_text(title or text) or href,
                html_url=href,
                source_id=href.rstrip("/").split("/")[-1],
            )
        )
        if len(results) >= limit:
            break
    if not results:
        results.append(
            LegalResult(
                country="it",
                title=f"Normattiva search page for: {keyword}",
                html_url="https://www.normattiva.it/ricerca/semplice?queryString=" + quote(keyword),
                note="Normattiva may require form/session parsing; check dati.normattiva.it for RDF/OpenData integration.",
            )
        )
    return results[:limit]


def get_legifrance_token(session: HttpSession) -> str:
    client_id = os.getenv("LEGIFRANCE_CLIENT_ID")
    client_secret = os.getenv("LEGIFRANCE_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise RuntimeError("Set LEGIFRANCE_CLIENT_ID and LEGIFRANCE_CLIENT_SECRET for Legifrance/PISTE.")
    token_url = "https://oauth.piste.gouv.fr/api/oauth/token"
    response = session.post(
        token_url,
        data={"grant_type": "client_credentials", "scope": "openid"},
        auth=(client_id, client_secret),
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    return response.json()["access_token"]


def search_france(keyword: str, limit: int, session: HttpSession) -> list[LegalResult]:
    token = get_legifrance_token(session)
    url = "https://api.piste.gouv.fr/dila/legifrance/lf-engine-app/search"
    body: dict[str, Any] = {
        "fond": "LODA_DATE",
        "recherche": {
            "champs": [
                {
                    "typeChamp": "ALL",
                    "criteres": [
                        {"typeRecherche": "UN_DES_MOTS", "valeur": keyword, "operateur": "ET"}
                    ],
                    "operateur": "ET",
                }
            ],
            "filtres": [{"facette": "NATURE", "valeurs": ["LOI"]}],
            "sort": "PERTINENCE",
            "pageSize": limit,
            "pageNumber": 1,
            "operateur": "ET",
            "typePagination": "DEFAUT",
        },
    }
    response = session.post(url, headers={"Authorization": f"Bearer {token}"}, json_body=body, timeout=TIMEOUT)
    response.raise_for_status()
    data = response.json()

    raw_results = data.get("results") or data.get("resultats") or []
    results: list[LegalResult] = []
    for item in raw_results[:limit]:
        text_id = item.get("id") or item.get("cid") or item.get("textId")
        title = item.get("title") or item.get("titre") or item.get("textTitle") or str(item)
        results.append(
            LegalResult(
                country="fr",
                title=clean_text(title),
                api_url=f"https://api.piste.gouv.fr/dila/legifrance/lf-engine-app/consult/getText?id={text_id}"
                if text_id
                else None,
                html_url=f"https://www.legifrance.gouv.fr/loda/id/{text_id}/" if text_id else None,
                source_id=text_id,
                note="Legifrance requires PISTE OAuth credentials.",
            )
        )
    return results


def search_uk(keyword: str, limit: int, session: HttpSession) -> list[LegalResult]:
    # legislation.gov.uk exposes stable HTML pages and machine-readable variants
    # for acts. The public title search is enough to get canonical act links.
    params = {"title": keyword, "type": "primary"}
    url = "https://www.legislation.gov.uk/search?" + urlencode(params)
    html = session.get(url, timeout=TIMEOUT).text
    links = parse_links(html, url)

    results: list[LegalResult] = []
    seen: set[str] = set()
    for text, href, title in links:
        if "legislation.gov.uk" not in href or href in seen:
            continue
        if not re.search(r"/(ukpga|asp|anaw|nia|ukla|uksi|wsi|ssi)/\d{4}/", href):
            continue
        href = re.sub(r"/data\.(xml|rdf|json)$", "", href)
        href = href.rstrip("/")
        seen.add(href)
        html_url = href + "/contents" if not href.endswith("/contents") else href
        api_url = href.replace("/contents", "") + "/data.xml"
        results.append(
            LegalResult(
                country="uk",
                title=clean_text(title or text),
                html_url=html_url,
                api_url=api_url,
                source_id="/".join(href.split("/")[-3:]),
            )
        )
        if len(results) >= limit:
            break
    return results


SEARCHERS = {
    "pl": search_poland,
    "es": search_spain,
    "de": search_germany,
    "it": search_italy,
    "fr": search_france,
    "uk": search_uk,
}


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="Search official legislation portals by keyword.")
    parser.add_argument("keyword", help="Keyword or phrase, e.g. 'ochrona zdrowia'")
    parser.add_argument("--countries", nargs="+", default=["pl"], choices=sorted(SEARCHERS))
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()

    session = get_session()
    all_results: list[dict[str, Any]] = []
    for country in args.countries:
        try:
            results = SEARCHERS[country](args.keyword, args.limit, session)
            all_results.extend(asdict(result) for result in results)
        except Exception as exc:
            all_results.append(
                asdict(
                    LegalResult(
                        country=country,
                        title=f"ERROR while searching {country}",
                        note=str(exc),
                    )
                )
            )

    print(json.dumps(all_results, ensure_ascii=False, indent=2 if args.pretty else None))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
