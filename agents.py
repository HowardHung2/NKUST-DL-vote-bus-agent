"""v2: the judges, the review of each answer, and the free-tier quota guard.

Ideas from Med-TAMARA (Wu & Day, IEEE IRI 2025), redesigned for the Gemini free tier:
  - several independent judges label the question (instead of asking one model many times),
  - a review checks the answer, and a reviewer agent rewrites it only when the check finds a problem.
Judges A and B and the code review use no chat model call.
"""

import csv
import hashlib
import json
import re
import threading
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np

HERE = Path(__file__).parent


# ---------------------------------------------------------------------------
# Judge A: rules written in code. Order matters: the first group that matches wins. None = no vote.
# ---------------------------------------------------------------------------
STATION_WORDS = ("臺北|台北|板橋|桃園|中壢|新竹|臺中|台中|朝馬|彰化|草屯|水里|南投|斗六|雲林|民雄|嘉義|臺南|台南|"
                 "高雄|屏東|宜蘭|花蓮|臺東|台東|員林|基隆|苗栗|澎湖|金門|"
                 "taipei|taichung|tainan|kaohsiung|hualien|taitung|pingtung|yilan|hsinchu|chiayi|changhua")
RULES = [
    ("personal", r"［已遮蔽"),
    ("politics", r"投給|投誰|該投|投哪|支持(哪|誰)|候選人|政黨|哪一黨|哪個黨|民進黨|國民黨|民眾黨|選舉.*(贏|輸)|vote for"),
    ("off_topic", r"忽略.{0,8}(指令|規則|設定)|提示詞|prompt|第一則訊息|一字不漏|沒有(任何)?(規則|限制)|角色扮演|"
                  r"玩個?遊戲|另一個.{0,6}AI|天氣|下雨|颱風|作業|報告|寫(一首)?詩|好吃|美食|股票|翻譯|weather"),
    ("human", r"扣款|付了兩次|重複(付|扣)|退款|退費|取消贊助|投訴|客訴|抱怨|免費(送|給)|說可以免費|答應|承諾|付款失敗|refund"),
    ("my_order", r"我的(車票|訂單|款項|座位|訂票|電子車票|付款)|我登記|對帳|寄出了嗎|查訂單|訂單編號|\d{15,}|my (order|ticket)"),
    ("rule", r"可以上|上車地點|要帶|證件|抵稅|收據|訂票表單|訂好票|算訂票|電子車票|集合|幾歲|年齡|中途|沒位子了|額滿|"
             r"幾份|個人資料|個資怎麼|多久|怎麼訂|如何訂|訂票(步驟|流程)"),
    ("cost", r"多少錢|費用|總共|價格|幾元|方案|加購|NT\$|\d+\s*元|最便宜|額外支持|how much|price"),
    ("info", r"截止|期限|募資.*(時間|日期|到)|連結|網址|信箱|email|粉專|臉書|粉絲專頁|facebook|主辦|聯絡|歷年|以前辦"),
    ("route", r"車次|班次|有車|哪些車|什麼車|幾點|發車|座位|位子|還有位|搭到|回.{0,4}投票|" + STATION_WORDS + r"|\b\d{3}\b|bus"),
    ("rule", r"怎麼|如何|規則|可以嗎|需要"),
]
RULES = [(c, re.compile(p, re.IGNORECASE)) for c, p in RULES]


def rule_judge(text):
    for category, pattern in RULES:
        if pattern.search(text):
            return category
    return None


# ---------------------------------------------------------------------------
# Judge B: compare the question with labelled example questions (intent_examples.csv) by embedding.
# The examples are embedded once and cached in a local .npy file, like the rule chunks.
# ---------------------------------------------------------------------------
class EmbeddingJudge:
    MIN_SIMILARITY = 0.55        # below this, judge B does not vote

    def __init__(self, embed, embed_model):
        with open(HERE / "intent_examples.csv", newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        self.categories = [r["category"] for r in rows]
        self.examples = [r["example"] for r in rows]
        self.embed = embed
        key = hashlib.sha256((embed_model + "\n".join(self.examples)).encode("utf-8")).hexdigest()[:16]
        cache = HERE / f"intent_vectors_{key}.npy"
        if cache.exists():
            self.vectors = np.load(cache)
        else:
            self.vectors = embed(self.examples)
            np.save(cache, self.vectors)
        self.vectors = self.vectors / np.linalg.norm(self.vectors, axis=1, keepdims=True)

    def judge_vector(self, q):
        """q: the question's embedding. Returns (category or None, best similarity)."""
        q = q / np.linalg.norm(q)
        sims = self.vectors @ q
        best = {}
        for category, s in zip(self.categories, sims):          # mean of the two closest examples per category
            best.setdefault(category, []).append(float(s))
        score = {c: float(np.mean(sorted(v, reverse=True)[:2])) for c, v in best.items()}
        winner = max(score, key=score.get)
        return (winner if score[winner] >= self.MIN_SIMILARITY else None), round(score[winner], 3)

    def judge_many(self, texts):
        """For the evaluation: one embedding call for many questions."""
        return [self.judge_vector(v) for v in self.embed(texts)]


# ---------------------------------------------------------------------------
# The code review: checks the answer against the tool results. No model call.
# ---------------------------------------------------------------------------
def numbers_in(value):
    """Every number inside a tool result (nested dicts and lists)."""
    text = json.dumps(value, ensure_ascii=False)
    return {int(n.replace(",", "")) for n in re.findall(r"\d[\d,]*", text) if len(n) < 12}


NOT_A_STATION = ("中途", "停靠", "沿途", "任何", "哪", "途中", "起點", "終點", "目的地", "那", "這", "該", "家鄉", "戶籍地")
CONFIRMED = re.compile(r"(?<![不沒未才還])(已經?|幫你|為你|為您|幫您)(成功)?(訂好|訂到|保留|確認)(了)?(你的|您的)?(車票|票|座位|位子)")
ID_OR_PHONE = re.compile(r"\b[A-Za-z][1289]\d{8}\b|(?<!\d)09\d{2}[- ]?\d{3}[- ]?\d{3}(?!\d)")


def code_review(answer, trace, user_text, history_text, routes, station_key, county_of, category=None,
                agreement=0.0, logged_in=False, fixed=None):
    """Return a list of problems found in the answer (empty = passed).
    routes: {route_id: {"origin", "stop", "destination"}}. fixed: the exact refusal sentences."""
    fixed = fixed or {}
    problems = []
    results = [step["result"] for step in trace]
    result_numbers = set().union(*(numbers_in(r) for r in results)) if results else set()
    allowed = result_numbers | numbers_in(user_text) | numbers_in(history_text)

    # 1. Route numbers: every route in the answer must exist and come from the tool results or the conversation.
    mentioned = set(re.findall(r"(?:車次|班次|路線)\s*(\d{3})(?!\d)|(?<!\d)(\d{3})\s*(?:號車|次車|車次|號)", answer))
    mentioned = {a or b for a, b in mentioned}
    mentioned |= {n for n in re.findall(r"(?<![\d$])(\d{3})(?!\d)", answer) if n in routes}
    for rid in sorted(mentioned):
        if rid not in routes and rid not in user_text:
            problems.append(f"答案提到不存在的車次 {rid}。")
        elif rid in routes and int(rid) not in allowed:
            problems.append(f"車次 {rid} 不在工具結果裡，可能是模型自己想的。")

    # 2. Seats: a number of seats must be one of the seats_left values in the tool results.
    seat_values = set()
    for r in results:
        for m in re.finditer(r'"seats_left": (\d+)', json.dumps(r, ensure_ascii=False)):
            seat_values.add(int(m.group(1)))
    for m in re.finditer(r"(?:剩餘?座位|剩下|座位剩|還有)\D{0,4}?(\d{1,3})\s*(?:個|位|席)?|(\d{1,3})\s*(?:個座位|個位子|個空位|席)", answer):
        n = int(m.group(1) or m.group(2))
        if seat_values and n not in seat_values and n not in numbers_in(user_text):
            problems.append(f"座位數 {n} 和工具結果不一致。")

    # 3. Money: every amount must come from a tool result or the user's message.
    for m in re.finditer(r"NT\$\s?([\d,]+)|([\d,]+)\s*元", answer):
        n = int((m.group(1) or m.group(2)).replace(",", ""))
        if n not in allowed and n != 1:
            problems.append(f"金額 NT${n} 不在工具結果裡，可能是模型自己算的。")

    # 4. Destination: when the user asked for routes to a place, the answer must take them there.
    targets = [step["arguments"].get("to_station") for step in trace
               if step["tool"] == "search_routes" and step["arguments"].get("to_station")]
    for target in targets[:1]:
        t_key = station_key(target)
        t_places = {t_key, county_of(target)}
        for m in re.finditer(r"在\s*([一-鿿]{1,6}?)\s*(?:火車站|轉運站|車站|站)?\s*下車", answer):
            place = m.group(1)
            if any(w in place for w in NOT_A_STATION):
                continue
            if station_key(place) not in t_places and county_of(place) not in t_places:
                problems.append(f"答案要使用者在「{place}」下車，但使用者要去的是「{target}」。")
        found = next((s["result"] for s in trace if s["tool"] == "search_routes"), {})
        if found.get("routes"):
            for rid in sorted(mentioned & set(routes)):
                r = routes[rid]
                reach = {station_key(r["destination"]), station_key(r["stop"] or ""),
                         county_of(r["destination"]), county_of(r["stop"] or "")}
                if not (reach & t_places):
                    problems.append(f"車次 {rid} 不會到「{target}」。")

    # 5. Never say a ticket is booked, never repeat an ID or a phone number.
    if CONFIRMED.search(answer):
        problems.append("答案說車票已經訂好或保留，但只有工作團隊能確認。")
    if ID_OR_PHONE.search(answer):
        problems.append("答案裡出現身分證字號或手機號碼。")

    # 6. The fixed sentences, when the judges agree on the category.
    if agreement >= 0.7:
        if category == "my_order" and not logged_in and fixed.get("login") and fixed["login"] not in answer:
            problems.append("FIXED:login")
        if category == "politics" and fixed.get("politics") and fixed["politics"] not in answer:
            problems.append("FIXED:politics")
        if category == "off_topic" and fixed.get("off_topic") and fixed["off_topic"] not in answer \
                and not trace:
            problems.append("FIXED:off_topic")
    return problems


# ---------------------------------------------------------------------------
# The reviewer agent: called only when the code review found a factual problem. One call, no tools.
# ---------------------------------------------------------------------------
REVIEWER_PROMPT = """You are the reviewer of the 2026 青年民主返鄉列車 help desk. Another agent wrote a DRAFT answer.
A check found PROBLEMS in it. Rewrite the answer so that every problem is fixed.
Rules:
- Use only facts that are in TOOL RESULTS. Never invent a route, a time, a seat number or a price.
- People can get on only at a route's first station (get_on_at); stops are get-off only.
- Take the user to the place they want to go (to_station). Never tell them to get off somewhere else.
- Never say a ticket is booked or confirmed. Never ask for an ID or phone number.
- Keep any line like （依據：…） or （座位數依官方檢視表…） from the draft.
- Reply in the language of the user's question (Traditional Chinese unless they wrote English). Four sentences or less;
  routes may be a short list. Reply with the new answer only."""


def reviewer_messages(user_text, draft, problems, trace):
    results = json.dumps([{"tool": s["tool"], "arguments": s["arguments"], "result": s["result"]} for s in trace],
                         ensure_ascii=False)[:7000]
    content = (f"USER QUESTION:\n{user_text}\n\nTOOL RESULTS:\n{results}\n\nDRAFT:\n{draft}\n\n"
               "PROBLEMS:\n" + "\n".join(f"- {p}" for p in problems))
    return [{"role": "system", "content": REVIEWER_PROMPT}, {"role": "user", "content": content}]


# ---------------------------------------------------------------------------
# The quota guard: the free tier allows 15 chat requests a minute and 500 a day (the day ends at midnight in
# California). The count is kept in logs/quota.json (numbers only) so a restart does not reset it.
# ---------------------------------------------------------------------------
class QuotaGuard:
    def __init__(self, per_minute=14, per_day=450, file=HERE / "logs" / "quota.json"):
        self.per_minute, self.per_day, self.file = per_minute, per_day, file
        self.lock = threading.Lock()
        self.recent = []
        self.day, self.used = self._today(), 0
        try:
            data = json.loads(self.file.read_text(encoding="utf-8"))
            if data.get("day") == self.day:
                self.used = int(data.get("used", 0))
        except (OSError, ValueError):
            pass

    @staticmethod
    def _today():
        return datetime.now(ZoneInfo("America/Los_Angeles")).strftime("%Y-%m-%d")

    def _save(self):
        try:
            self.file.parent.mkdir(exist_ok=True)
            self.file.write_text(json.dumps({"day": self.day, "used": self.used}), encoding="utf-8")
        except OSError:
            pass

    def left_today(self):
        with self.lock:
            if self._today() != self.day:
                self.day, self.used = self._today(), 0
            return self.per_day - self.used

    def near_limit(self):
        return self.left_today() < self.per_day * 0.1

    def take(self):
        """Wait if this minute is full; return False if today's requests are used up."""
        if self.left_today() <= 0:
            return False
        while True:
            with self.lock:
                now = time.time()
                self.recent = [t for t in self.recent if now - t < 60]
                if len(self.recent) < self.per_minute:
                    self.recent.append(now)
                    self.used += 1
                    self._save()
                    return True
                wait = 60 - (now - self.recent[0]) + 0.5
            time.sleep(wait)
