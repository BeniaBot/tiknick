"""
מודול אנטי-זיהוי בוטים עבור גרידת פורומי NodeBB.

המודול מספק מחלקת SmartSession שמדמה התנהגות דפדפן אמיתי
כדי למנוע חסימה על-ידי מערכות אנטי-בוט כגון Cloudflare, rate limiters ועוד.

תלויות: urllib, http.cookiejar, json, time, random בלבד — ללא תלויות חיצוניות.
"""

import gzip
import io
import json
import random
import time
import zlib
from collections import defaultdict
from http.cookiejar import CookieJar
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import (
    HTTPCookieProcessor,
    Request,
    build_opener,
    HTTPSHandler,
    HTTPHandler,
)

# ──────────────────────── חריגות מותאמות אישית ────────────────────────


class AntiDetectError(Exception):
    """חריגה בסיסית עבור כל שגיאות מודול האנטי-זיהוי."""
    pass


class CloudflareBlockError(AntiDetectError):
    """חריגה שנזרקת כאשר Cloudflare חוסם את הבקשה."""
    pass


# ──────────────────────── מאגר User-Agent ────────────────────────

# רשימת סוכני משתמש אמיתיים ומעודכנים — כ-15 סוכנים מדפדפנים שונים
_USER_AGENTS = [
    # Chrome על Windows 10/11
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    # Chrome על macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    # Firefox על Windows 10/11
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:120.0) Gecko/20100101 Firefox/120.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 Firefox/126.0",
    # Firefox על macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:122.0) Gecko/20100101 Firefox/122.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:125.0) Gecko/20100101 Firefox/125.0",
    # Edge על Windows 10/11
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36 Edg/123.0.0.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36 Edg/126.0.0.0",
    # Edge על macOS
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 Edg/124.0.0.0",
]


def _parse_ua(ua: str) -> dict:
    """
    מחלץ מידע מתוך מחרוזת User-Agent לצורך בניית כותרות sec-ch-ua.

    מחזיר מילון עם שם הדפדפן, גרסה, ופלטפורמה.
    """
    info = {"browser": "Chromium", "version": "120", "platform": "Windows"}

    # זיהוי פלטפורמה
    if "Macintosh" in ua or "Mac OS X" in ua:
        info["platform"] = "macOS"
    else:
        info["platform"] = "Windows"

    # זיהוי דפדפן וגרסה
    if "Edg/" in ua:
        info["browser"] = "Microsoft Edge"
        # חילוץ גרסת Edge
        idx = ua.index("Edg/")
        ver_str = ua[idx + 4:].split(" ")[0].split(".")[0]
        info["version"] = ver_str
    elif "Firefox/" in ua:
        info["browser"] = "Firefox"
        idx = ua.index("Firefox/")
        ver_str = ua[idx + 8:].split(" ")[0].split(".")[0]
        info["version"] = ver_str
    elif "Chrome/" in ua:
        info["browser"] = "Google Chrome"
        idx = ua.index("Chrome/")
        ver_str = ua[idx + 7:].split(" ")[0].split(".")[0]
        info["version"] = ver_str

    return info


def _build_sec_ch_ua_headers(ua: str) -> dict:
    """
    בונה כותרות sec-ch-ua תואמות ל-User-Agent שנבחר.

    Firefox לא שולח כותרות sec-ch-ua — במקרה כזה מוחזר מילון ריק.
    """
    info = _parse_ua(ua)

    # Firefox לא שולח כותרות Client Hints
    if info["browser"] == "Firefox":
        return {}

    version = info["version"]
    platform = info["platform"]

    # בניית מחרוזת sec-ch-ua בפורמט הנכון
    if info["browser"] == "Microsoft Edge":
        sec_ch_ua = (
            f'"Chromium";v="{version}", '
            f'"Microsoft Edge";v="{version}", '
            f'"Not_A Brand";v="8"'
        )
    else:
        # Chrome רגיל
        sec_ch_ua = (
            f'"Chromium";v="{version}", '
            f'"Google Chrome";v="{version}", '
            f'"Not_A Brand";v="8"'
        )

    return {
        "sec-ch-ua": sec_ch_ua,
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": f'"{platform}"',
    }


# ──────────────────────── מגביל קצב בקשות ────────────────────────


class _RateLimiter:
    """
    מגביל קצב בקשות לפי דומיין.

    עוקב אחרי חותמות זמן של בקשות ומשהה אוטומטית
    אם מתקרבים למגבלת הבקשות לדקה.
    """

    def __init__(self, max_per_min: int = 20):
        """
        אתחול מגביל הקצב.

        :param max_per_min: מספר בקשות מקסימלי לדקה לכל דומיין
        """
        self._max_per_min = max_per_min
        # מילון: דומיין -> רשימת חותמות זמן של בקשות
        self._history: dict[str, list[float]] = defaultdict(list)

    def _cleanup(self, domain: str) -> None:
        """מנקה בקשות ישנות מלפני יותר מ-60 שניות."""
        cutoff = time.monotonic() - 60.0
        self._history[domain] = [
            ts for ts in self._history[domain] if ts > cutoff
        ]

    def wait_if_needed(self, domain: str) -> None:
        """
        בודק אם צריך להמתין לפני ביצוע בקשה נוספת.

        אם מספר הבקשות בדקה האחרונה מתקרב למגבלה,
        ממתין עד שפג תוקפה של הבקשה הישנה ביותר.
        """
        self._cleanup(domain)
        timestamps = self._history[domain]

        if len(timestamps) >= self._max_per_min:
            # חישוב זמן ההמתנה עד שהבקשה הישנה ביותר תפוג
            oldest = timestamps[0]
            wait_time = 60.0 - (time.monotonic() - oldest)
            if wait_time > 0:
                # הוספת ריצוד קטן כדי לא לפגוע ברגע המדויק שהמגבלה מתאפסת
                wait_time += random.uniform(0.5, 1.5)
                time.sleep(wait_time)
                # ניקוי מחדש אחרי ההמתנה
                self._cleanup(domain)

    def record(self, domain: str) -> None:
        """מתעד בקשה חדשה עבור הדומיין הנתון."""
        self._history[domain].append(time.monotonic())


# ──────────────────────── מחלקת SmartSession ────────────────────────


class SmartSession:
    """
    סשן חכם עם הגנות אנטי-זיהוי בוטים.

    מדמה התנהגות דפדפן אמיתי באמצעות:
    - רוטציית User-Agent
    - כותרות דפדפן מלאות ומציאותיות
    - השהיות דמויות-אדם בין בקשות
    - backoff מעריכי עם ריצוד (jitter) על שגיאות שרת
    - ניהול עוגיות אוטומטי
    - הגבלת קצב בקשות לפי דומיין
    - זיהוי חסימת Cloudflare
    """

    def __init__(self, base_url: str, max_requests_per_min: int = 20):
        """
        אתחול הסשן החכם.

        :param base_url: כתובת הבסיס של הפורום (לדוגמה: https://forum.example.com)
        :param max_requests_per_min: מגבלת בקשות לדקה לכל דומיין (ברירת מחדל: 20)
        """
        # וידוא שכתובת הבסיס מסתיימת ב-/
        self.base_url = base_url.rstrip("/") + "/"
        self._domain = urlparse(self.base_url).netloc

        # מאגר עוגיות — שומר ושולח עוגיות אוטומטית
        self._cookie_jar = CookieJar()
        cookie_handler = HTTPCookieProcessor(self._cookie_jar)
        self._opener = build_opener(cookie_handler, HTTPSHandler(), HTTPHandler())

        # מגביל קצב בקשות
        self._rate_limiter = _RateLimiter(max_per_min=max_requests_per_min)

        # מונה בקשות כללי (לצורכי לוגים ומעקב)
        self._request_count = 0

    # ──────────── בניית כותרות ────────────

    def _select_ua(self) -> str:
        """בוחר User-Agent אקראי מהמאגר."""
        return random.choice(_USER_AGENTS)

    def _build_headers(self, ua: str, is_json: bool = True) -> dict:
        """
        בונה סט כותרות HTTP מציאותיות המדמות דפדפן אמיתי.

        :param ua: מחרוזת User-Agent שנבחרה
        :param is_json: האם הבקשה מצפה לתשובת JSON (משפיע על Accept)
        :returns: מילון כותרות
        """
        headers = {
            "User-Agent": ua,
            "Accept-Language": "he,en-US;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate, br",
            "Referer": self.base_url,
            "Connection": "keep-alive",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
        }

        # סוג תוכן מצופה — JSON או HTML
        if is_json:
            headers["Accept"] = "application/json, text/plain, */*"
        else:
            headers["Accept"] = (
                "text/html,application/xhtml+xml,application/xml;"
                "q=0.9,image/avif,image/webp,*/*;q=0.8"
            )

        # הוספת כותרות Client Hints (רלוונטי רק ל-Chrome ו-Edge)
        sec_headers = _build_sec_ch_ua_headers(ua)
        headers.update(sec_headers)

        return headers

    # ──────────── השהיות דמויות-אדם ────────────

    @staticmethod
    def smart_delay() -> None:
        """
        השהיה אקראית המדמה התנהגות גלישה אנושית.

        ברוב המקרים (~80%): השהיה של 0.8-2.5 שניות.
        מדי פעם (~20%): "פרץ" מהיר של 0.3-0.6 שניות,
        כמו שמשתמש אמיתי לוחץ מהר על כמה קישורים ברצף.
        """
        if random.random() < 0.2:
            # פרץ מהיר — מדמה לחיצות רצופות מהירות
            delay = random.uniform(0.3, 0.6)
        else:
            # גלישה רגילה — השהיה טבעית
            delay = random.uniform(0.8, 2.5)

        time.sleep(delay)

    # ──────────── פירוק תגובה דחוסה ────────────

    @staticmethod
    def _decompress(data: bytes, encoding: str | None) -> bytes:
        """
        מפרק נתונים דחוסים לפי סוג הקידוד.

        תומך ב-gzip, deflate וכן br (brotli) — אם הספרייה זמינה.
        אם הקידוד לא מזוהה, מחזיר את הנתונים כמות שהם.
        """
        if not encoding:
            return data

        encoding = encoding.strip().lower()

        if encoding == "gzip":
            try:
                return gzip.decompress(data)
            except OSError:
                # ניסיון חלופי עם zlib במקרה שהכותרת שגויה
                return zlib.decompress(data, zlib.MAX_WBITS | 16)

        elif encoding == "deflate":
            try:
                return zlib.decompress(data)
            except zlib.error:
                # ניסיון עם raw deflate
                return zlib.decompress(data, -zlib.MAX_WBITS)

        elif encoding == "br":
            # ניסיון לייבא brotli — ספריית צד שלישי אופציונלית
            try:
                import brotli  # type: ignore[import-untyped]
                return brotli.decompress(data)
            except ImportError:
                # brotli לא מותקן — מחזירים את הנתונים כמו שהם
                # ומקווים שהשרת שלח פורמט אחר
                return data

        # קידוד לא מוכר — מחזירים כמו שהוא
        return data

    # ──────────── זיהוי חסימת Cloudflare ────────────

    @staticmethod
    def _check_cloudflare(body: str) -> None:
        """
        בודק אם התגובה מכילה אתגר Cloudflare.

        אם מזוהה חסימה, זורק חריגת CloudflareBlockError.
        """
        # סימנים מובהקים של דף אתגר Cloudflare
        cf_indicators = [
            "<title>Just a moment</title>",
            "cf-challenge",
            "cf-browser-verification",
            "cf_chl_opt",
        ]
        body_lower = body.lower()
        for indicator in cf_indicators:
            if indicator.lower() in body_lower:
                raise CloudflareBlockError(
                    "🚫 Cloudflare חסם את הגישה. "
                    "הבקשה זוהתה כבוט ונחסמה על-ידי מערכת ההגנה. "
                    "נסה שוב מאוחר יותר, השתמש בפרוקסי אחר, "
                    "או הפחת את קצב הבקשות."
                )

    # ──────────── backoff מעריכי ────────────

    @staticmethod
    def _calc_backoff(attempt: int, base: float = 1.0) -> float:
        """
        מחשב זמן המתנה עם backoff מעריכי וריצוד אקראי.

        הנוסחה: min(base * 2^attempt + jitter, 60)
        הריצוד מונע מצב של "עדר רועם" — הרבה לקוחות שמנסים בו-זמנית.

        :param attempt: מספר הניסיון (מתחיל מ-0)
        :param base: זמן בסיס בשניות
        :returns: זמן המתנה בשניות
        """
        exponential = base * (2 ** attempt)
        jitter = random.uniform(0, exponential * 0.5)
        return min(exponential + jitter, 60.0)

    # ──────────── שליחת בקשה ────────────

    def _do_request(self, url: str, headers: dict, timeout: int) -> tuple[bytes, str]:
        """
        מבצע בקשת HTTP בודדת ומחזיר את גוף התגובה הגולמי וסוג הקידוד.

        :param url: כתובת URL מלאה
        :param headers: מילון כותרות HTTP
        :param timeout: זמן המתנה מקסימלי בשניות
        :returns: טאפל של (גוף התגובה כ-bytes, סוג קידוד דחיסה)
        :raises HTTPError: בכל שגיאת HTTP
        """
        req = Request(url, headers=headers)
        response = self._opener.open(req, timeout=timeout)
        raw_data = response.read()
        content_encoding = response.headers.get("Content-Encoding")
        return raw_data, content_encoding

    # ──────────── מתודה ראשית: get_json ────────────

    def get_json(
        self,
        path: str,
        cookie: str | None = None,
        timeout: int = 20,
    ) -> dict:
        """
        מבצע בקשת GET ומחזיר את התגובה כ-JSON.

        זוהי המתודה הראשית של הסשן. היא מטפלת אוטומטית ב:
        - בחירת User-Agent ובניית כותרות מציאותיות
        - הגבלת קצב בקשות
        - ניסיונות חוזרים עם backoff מעריכי (429/503)
        - פירוק תגובות דחוסות (gzip/deflate)
        - זיהוי חסימת Cloudflare
        - ניהול עוגיות אוטומטי

        :param path: נתיב יחסי לכתובת הבסיס (לדוגמה: /api/users?page=1)
        :param cookie: מחרוזת עוגייה אופציונלית להוספה (לדוגמה: express.sid=abc123)
        :param timeout: זמן המתנה מקסימלי לבקשה בשניות
        :returns: מילון JSON מפורסר
        :raises AntiDetectError: בכל כשלון שאינו ניתן לתיקון
        :raises CloudflareBlockError: כשמזוהה חסימת Cloudflare
        """
        # בניית כתובת URL מלאה מהנתיב היחסי
        url = urljoin(self.base_url, path.lstrip("/"))

        max_retries = 5

        for attempt in range(max_retries):
            # בחירת User-Agent אקראי ובניית כותרות
            ua = self._select_ua()
            headers = self._build_headers(ua, is_json=True)

            # הוספת עוגייה ידנית אם סופקה
            if cookie:
                headers["Cookie"] = cookie

            # המתנה אם מתקרבים למגבלת הקצב
            self._rate_limiter.wait_if_needed(self._domain)

            try:
                raw_data, content_encoding = self._do_request(
                    url, headers, timeout
                )

                # תיעוד הבקשה במגביל הקצב
                self._rate_limiter.record(self._domain)
                self._request_count += 1

                # פירוק נתונים דחוסים
                body_bytes = self._decompress(raw_data, content_encoding)
                body_str = body_bytes.decode("utf-8", errors="replace")

                # בדיקת חסימת Cloudflare
                self._check_cloudflare(body_str)

                # ניסיון לפרסר כ-JSON
                try:
                    return json.loads(body_str)
                except json.JSONDecodeError as exc:
                    raise AntiDetectError(
                        f"השרת החזיר תגובה שאינה JSON חוקי. "
                        f"תחילת התגובה: {body_str[:200]!r}"
                    ) from exc

            except HTTPError as exc:
                # תיעוד הבקשה גם במקרה של שגיאה (כי הבקשה כן יצאה)
                self._rate_limiter.record(self._domain)
                self._request_count += 1

                status = exc.code

                # שגיאות אימות — אין טעם לנסות שוב
                if status in (401, 403):
                    raise AntiDetectError(
                        f"שגיאת אימות (HTTP {status}). "
                        f"ייתכן שנדרשת הרשאה או שהגישה נחסמה לצמיתות. "
                        f"כתובת: {url}"
                    ) from exc

                # שגיאות קצב / שרת עמוס — ניסיון חוזר עם backoff
                if status in (429, 503):
                    if attempt < max_retries - 1:
                        wait_time = self._calc_backoff(attempt)
                        time.sleep(wait_time)
                        continue
                    else:
                        raise AntiDetectError(
                            f"השרת ממשיך להחזיר HTTP {status} "
                            f"גם אחרי {max_retries} ניסיונות. "
                            f"כתובת: {url}"
                        ) from exc

                # בדיקת Cloudflare גם בתוך גוף שגיאת HTTP
                try:
                    err_body_raw = exc.read()
                    err_encoding = exc.headers.get("Content-Encoding")
                    err_body = self._decompress(
                        err_body_raw, err_encoding
                    ).decode("utf-8", errors="replace")
                    self._check_cloudflare(err_body)
                except CloudflareBlockError:
                    raise
                except Exception:
                    # לא הצלחנו לקרוא את גוף השגיאה — ממשיכים
                    pass

                # שגיאת HTTP אחרת — זורקים חריגה
                raise AntiDetectError(
                    f"שגיאת HTTP {status} בבקשה ל-{url}"
                ) from exc

            except URLError as exc:
                # שגיאת רשת (DNS, חיבור, timeout וכו')
                if attempt < max_retries - 1:
                    wait_time = self._calc_backoff(attempt)
                    time.sleep(wait_time)
                    continue
                raise AntiDetectError(
                    f"שגיאת רשת בבקשה ל-{url}: {exc.reason}"
                ) from exc

            except CloudflareBlockError:
                # חסימת Cloudflare — זורקים מיד ללא ניסיון חוזר
                raise

            except AntiDetectError:
                # חריגות שלנו — מעבירים הלאה
                raise

            except Exception as exc:
                # שגיאה בלתי צפויה
                if attempt < max_retries - 1:
                    wait_time = self._calc_backoff(attempt)
                    time.sleep(wait_time)
                    continue
                raise AntiDetectError(
                    f"שגיאה בלתי צפויה בבקשה ל-{url}: {exc}"
                ) from exc

        # לא אמור להגיע לכאן, אבל ליתר ביטחון
        raise AntiDetectError(
            f"מוצו כל {max_retries} הניסיונות לבקשה ל-{url}"
        )


# ──────────────────────── פונקציית נוחות ברמת המודול ────────────────────────


def fetch_json(
    url: str,
    cookie: str | None = None,
    timeout: int = 20,
) -> dict:
    """
    בקשת JSON חד-פעמית עם הגנות אנטי-זיהוי (ללא session).

    יוצר סשן SmartSession זמני, מבצע בקשה אחת, ומחזיר את התוצאה.
    שימושי לבקשות בודדות שלא דורשות שמירת מצב בין בקשות.

    :param url: כתובת URL מלאה (לדוגמה: https://forum.example.com/api/users)
    :param cookie: מחרוזת עוגייה אופציונלית (לדוגמה: express.sid=abc123)
    :param timeout: זמן המתנה מקסימלי בשניות
    :returns: מילון JSON מפורסר
    :raises AntiDetectError: בכל כשלון
    :raises CloudflareBlockError: כשמזוהה חסימת Cloudflare
    """
    # פירוק הכתובת לבסיס ונתיב
    parsed = urlparse(url)
    base = f"{parsed.scheme}://{parsed.netloc}"
    path = parsed.path
    if parsed.query:
        path += f"?{parsed.query}"

    session = SmartSession(base)
    return session.get_json(path, cookie=cookie, timeout=timeout)


# ──────────────────────── הרצה ישירה לבדיקה ────────────────────────

if __name__ == "__main__":
    # דוגמת שימוש בסיסית
    print("מודול אנטי-זיהוי בוטים — בדיקה עצמית")
    print("=" * 50)
    print(f"מספר סוכני משתמש במאגר: {len(_USER_AGENTS)}")
    print()

    # הדגמת בחירת User-Agent ובניית כותרות
    ua = random.choice(_USER_AGENTS)
    print(f"User-Agent שנבחר:\n  {ua}")
    print()

    info = _parse_ua(ua)
    print(f"מידע שחולץ: {info}")
    print()

    sec_headers = _build_sec_ch_ua_headers(ua)
    if sec_headers:
        print("כותרות sec-ch-ua:")
        for key, val in sec_headers.items():
            print(f"  {key}: {val}")
    else:
        print("(Firefox — ללא כותרות Client Hints)")
    print()

    # הדגמת חישוב backoff
    print("דוגמאות backoff מעריכי:")
    for i in range(5):
        wait = SmartSession._calc_backoff(i)
        print(f"  ניסיון {i}: {wait:.2f} שניות")

    print()
    print("✅ המודול נטען בהצלחה ומוכן לשימוש.")
