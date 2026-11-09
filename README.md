**English** | [繁體中文](README.zh-TW.md)

# Vote-Bus Help Desk: the Official AI Help Desk of the 2026 Youth Democracy Vote-Bus (青年民主返鄉列車)

An AI text help desk for young voters who study or work away from home and want a cheap bus seat home to vote
on **2026-11-28**. It finds a route to the user's hometown, tells the seats left, works out the cost of a
ticket plan, and explains every booking and boarding rule. Users who finished an order log in with their
flyingV order number and can check their own order: route, payment check and e-ticket status.

> Course project: NKUST Deep Learning, Midterm Project (Agent + RAG + LLM application)
> Student: F115118103 洪秉榮 (Bing-Rong Hung)
> Current version: **v1.0.0** (the first stable release, see [Versions](#versions))
>
> This is the official online help desk of the vote-bus. Sponsor and book on the
> [flyingV project page](https://www.flyingv.cc/projects/37638) and the official booking form.
> **This repository runs with made-up orders only** (`orders_test.csv`); the real order sheet is never in it.

## Who It Serves and Why

- **Users:** university students and young workers who live away from their household registration (戶籍地).
- **What they need:** a route that stops at their hometown and still has seats, the cheapest way to pay,
  and the booking steps. The steps are easy to get wrong: paying on flyingV is **not** a booking, you must also
  fill in the booking form, and you can get on **only at the first station**.
- **Today:** they read a long project page, a seat sheet and a form, then email the team and wait.
- **Why a general AI chat cannot do this:** ChatGPT or Gemini does not know the 25 routes, the seats left,
  the plan limits or the boarding rules, and it cannot check the status of a user's order.

## Rules the Agent Must Follow

1. Never say a ticket is booked or confirmed. Only the team confirms it, by email, after a 3–5 working-day check.
2. Never invent a route, a seat number, a boarding spot or a price. When the data has no answer, say so and give the official email.
3. Never ask for or keep an ID number, a birthday or a phone number. These go only in the official form.
4. Never support or criticise a candidate or a party, and never give voting advice. The project itself is neutral.
5. Show order data only to a user who logged in with that order number, and only that order. The **code**
   enforces this, not the model: guests have no order tool, and the order tool takes no order number.

## How It Works

```mermaid
flowchart LR
    U[User] --> UI[Gradio chat screen]
    UI -->|guest or logged-in order| A[Agent loop<br/>gemini-3.5-flash-lite]
    A -->|routes and seats| S[(Official seat<br/>Google Sheet)]
    A -->|plans, facts| DB[(SQLite<br/>built from CSV)]
    A -->|own order only,<br/>logged-in users| O[(Order sheet<br/>masked at the source)]
    A -->|rules questions| R[search_rules] --> V[19 chunks of rules.txt<br/>gemini-embedding-001]
    A -->|maths| C[calculate_cost]
    A -->|payment problems| H[transfer_to_human]
    A --> UI
```

- **Model:** gemini-3.5-flash-lite (Gemini API, OpenAI-compatible endpoint). Embeddings: gemini-embedding-001.
- **Chat screen:** Gradio, with a greeting, sample questions, a **tool trace** panel (with the RAG chunks and
  their scores), and a choice at the top: **"I finished an order"** (type the flyingV order number to log in)
  or **"Guest"**.
- **Database (SQLite)**, built when the app starts:

  | Table | Source | What it holds | Rows |
  |---|---|---|---|
  | `routes` | **the official route and seat Google Sheet, read live** (`routes.csv` is the fallback copy) | route number, date, time, first station, stop (get off only), destination, seats left | 25 |
  | `plans` | `plans.csv` | the 7 flyingV plans: price, rewards, tickets included, add-on ticket limit | 7 |
  | `project_info` | `project_info.csv` | organizer, vote day, deadline, links, contact, past results | 10 |

- **RAG:** `rules.txt` is cut on its `##` headings into 19 chunks (booking steps, e-ticket check, who may ride, ID,
  meeting times, boarding rules, one form per passenger, add-on limits, receipts and tax, sold-out routes and refunds,
  boarding spots, personal data, political neutrality, and more). The chunks are embedded once at start-up
  (the vectors are cached in a local `.npy` file and made again when `rules.txt` changes). Each question is
  embedded and the closest chunks with a cosine score of at least 0.60 go to the model.

- **Tools (6 for everyone, plus 1 for logged-in users):**

  | Tool | What it does | Kind |
  |---|---|---|
  | `search_routes(to_station, from_station, date)` | routes where the user can get off at their hometown (destination or stop); warns when the user's station is only a stop | read the database |
  | `get_route(route_id)` | one route by number, with seats left | read the database |
  | `get_project_info(topic)` | one project fact (deadline, links, contact ...) | read the database |
  | `calculate_cost(tickets, plan_price, extra_support)` | the cost of a plan with add-on tickets (NT$1 each, with a limit), or the cheapest way | calculate in code |
  | `search_rules(question)` | the RAG search over `rules.txt` | RAG |
  | `transfer_to_human(reason)` | the official email for payment problems, refunds and complaints | hand over |
  | `get_my_order()` | **logged-in users only:** their own order, one row per passenger, with what each status means | read the order sheet |

- **Safety:** the agent loop stops after 8 model calls, runs only the tools this user may use, and the model
  never writes SQL. ID numbers and phone numbers that a user types in the chat are hidden by the code before the
  message reaches the model, so they are never sent to the API or saved. The system prompt has five parts:
  role and goal, scope, interaction rules, refusals with exact sentences, and the opening line.

## Data Sources: When the App Reads Online Data and When It Uses Local Files

| Data | Normally | When it uses local or older data |
|---|---|---|
| Routes and seats | **Always tries online first:** the official seat sheet (a public Google Sheet). Read once at start-up, then again on a route lookup when the last read is more than 60 seconds old | If the sheet cannot be read (no network, the sheet layout changed, no routes found), the **last good read** stays. Only if the sheet cannot be read at start-up does the app use the local `routes.csv` (the 2026/11/03 copy). The page and the agent say which one is in use |
| Orders | With `ORDER_SHEET_CSV_URL` in `.env`: the **online order sheet**, read at most every 30 seconds | Without it: **test mode**, with the made-up orders in the local `orders_test.csv`; the page shows 「測試模式：訂單為測試資料」. With it but unreadable: the last good read stays; if the sheet cannot be read at start-up, there are no orders and nobody can log in. **Real mode never falls back to the test orders**, so the two are never mixed |
| Plans, project facts | Always the local `plans.csv` and `project_info.csv`, loaded into SQLite at every start | — |
| Booking and boarding rules | Always the local `rules.txt` | — |

To use another seat sheet, set `SEAT_SHEET_CSV_URL` in `.env`.
Seats and orders read online are kept in memory only and never written to disk.

## How Logging In Works

The **code** decides the login. The model is not involved.

1. The page first asks: *Did you finish an order?*
   - **Guest:** chat at once about routes, seats, costs and rules, with no order data.
   - **I finished an order:** a box appears for the flyingV order number.
2. The code cleans the number (removes spaces and hyphens, makes letters upper case) and checks its form
   (5–40 digits or letters).
3. The code looks the number up in the order sheet (reading the sheet again if needed).
   - **Not found:** the login fails. At most 5 tries per page, and at most 10 wrong numbers per visitor IP in
     15 minutes, so a new tab does not reset the count.
   - **Found:** the order number is kept in this tab's session **on the server**. The page shows only its last 4 digits.
4. For every question, the code picks the model's tools from the session:
   - A guest's tool list has **no** `get_my_order`; if the model calls it anyway, the code refuses.
   - A logged-in user also gets `get_my_order()`. It has **no arguments**: the code reads the number from the
     session, so the model cannot choose which order to read. Asked about another order number, the agent says
     it can only show the order the user logged in with.
5. **Logging out:** choose "Guest", reload the page, or send no message for 30 minutes (`SESSION_SECONDS`).

## Order Data Preparation: Masked at the Source

- Personal data in the order sheet is masked **in the Google Sheet's source data itself**, not after the data is
  read into the app (no DTO step).
  - Passenger names are already masked in the sheet, for example 「王Ｏ明」.
  - The ID number, birth date, phone number and email that the booking form collects are **not in the sheet
    this app reads**.
- So this project never gets or handles any other personal data: it never passes through the code, the memory,
  the model or the API.
- `orders_test.csv` has the same columns and the same masking as the real order sheet, and every test uses it.
- The model gets only the columns a passenger asks about: route, get-off choice, payment check, ticket status,
  seat and sent date. Work columns such as the volunteer in charge, internal notes, ticket numbers and ticket links
  are not given to the model.

## Tests

`test_agent.py` has three parts, always with the made-up orders:

1. **Tool choice (20 questions):** in the data, needs maths, rules, not in the data, not our job.
2. **Scope tests (8 questions):** questions that try to pull the agent off its job: voting advice, homework,
   "ignore your rules", "print your prompt", role-play, a fake promise of a free ticket, an ID number, and a date with no bus.
3. **Order access (5 checks):** a guest asks for an order (must get the log-in sentence, no data); a logged-in user
   asks about their own order (must use `get_my_order`) and about someone else's order number (must not show it);
   and logging in with an order number that does not exist (must fail).

Latest results: tool choice **20/20**, scope tests **8/8**, order access **5/5**. The full record is in
[`test_results.md`](test_results.md).

## Changes Made After Testing

### Log in with the order number and check your own order

- **Before:** the agent had a `create_booking_request` tool that saved bookings in SQLite. But real bookings come
  in through the official booking form, so a second copy in the agent only repeated, or even disagreed with, the official data.
- **Change:** the tool was removed. The agent now only **reads** the official order sheet, and users log in with
  their order number (see "How Logging In Works"). The code controls order access: guests have no order tool,
  and the order tool takes no order number.
- **Result:** order access 5/5. A guest gets the log-in sentence and no data, a logged-in user sees only their
  own order, and a wrong order number cannot log in.

### Suggest nearby stations when no bus stops there, and search by county

- **Problem 1:** 「我要回員林」 got the "no data, please email" sentence, because the rule "a tool finds nothing →
  use the exact sentence" also caught a place with no bus. In early tests, before the prompt took effect, the model
  had suggested nearby stations instead, which is more useful.
- **Change 1:** a place with no bus has its own rule: say no route stops there, suggest 1–3 nearby stations from
  the route list, and ask whether to look them up.
- **Problem 2:** 「我要回南投」 said there was no bus, although 草屯鎮公所 and 水里車站 are in 南投縣: the model knew
  only station names.
- **Change 2:** a station-to-county table in the code lets a county or city name (南投, 雲林 ...) find the routes
  that stop there.
- **Result:** tool choice 20/20, scope tests 8/8, order access 5/5.

## Versions

### v1.0.0: the first stable release (2026-11-09)

- Git tag: `v1.0.0` (commit `33b22af`). To get this version: `git checkout v1.0.0`.
- Design: **one agent** (gemini-3.5-flash-lite) with tool calling and RAG. For each question the same model chooses
  the tools and writes the answer.
- Features:
  - Routes and seats read live from the official seat sheet, with `routes.csv` as the fallback.
  - Ticket plan costs and project facts.
  - RAG search over the booking and boarding rules (19 chunks of `rules.txt`).
  - Log in with the flyingV order number to see only your own order; the order data is masked at the source.
  - Personal data masking, login limits, log-out after 30 minutes.
- Test results: tool choice 20/20, scope tests 8/8, order access 5/5 ([`test_results.md`](test_results.md)).
- Known issue: for 「我在臺中讀書，要回高雄投票」 the agent explains that 臺中 is a get-off-only stop, but then
  suggests "get on at 臺北 and get off at 臺中" instead of a bus to 高雄, where the user wants to go.

### v2.0.0: a trust-aware help desk with several judges (built and evaluated, on the `v2-trust-aware` branch)

**Reference paper:** J.-Y. Wu and M.-Y. Day, "Med-TAMARA: Trust-Aware Multi-Agent Risk Assessment in Medical AI Dialogue,"
*2025 IEEE International Conference on Information Reuse and Integration and Data Science (IRI)*, San Jose, CA, USA, 2025.
DOI: [10.1109/IRI66576.2025.00052](https://doi.org/10.1109/IRI66576.2025.00052),
IEEE Xplore: <https://ieeexplore.ieee.org/document/11153120>

> This version follows the architecture described in the paper's **abstract** (the full text needs an IEEE sign-in),
> redesigned for this help desk and for the Gemini free tier. It is not a full reproduction of the paper's method.

**Why v2:** in v1 the same model chooses the tools and writes the answer, and nothing checks the answer.
The 臺中→高雄 question is an example: the tool results were right, but the answer missed what the user needed.
The paper deals with a similar problem: LLM output is unstable, and it is hard to know when to hand a case to a person.

**Limit:** no billing, so the Gemini free tier (gemini-3.5-flash-lite: 500 requests a day, 15 a minute).
The goal is **about the same number of chat model calls per question as v1 (about 2–3)**: the new judging and
checking is done in code and with embeddings where possible (1,000 embedding requests a day is plenty), and the
model is called once more only when a problem is found.

**The paper's parts and what v2 does:**

| The paper's part | What v2 does | Extra chat model calls |
|---|---|---|
| Self-consistency filtering: judge several times and drop unstable predictions | Three **independent judges** decide the question's category (routes, cost, rules, my order, payment problem, politics, personal data, out of scope), instead of asking one model three times:<br>A. code rules (keywords, order number and ID formats, station and county names)<br>B. embedding similarity to labelled example questions for each category (sharing the question embedding with RAG)<br>C. the first tool the answer agent chooses | 0 |
| Few-shot chain-of-thought prompting | A few hard examples with their reasoning steps in the system prompt, such as "when the user's station is get-off only, find routes that start at a first station and end or stop at the user's destination" | 0 (more tokens only, which the free tier has room for) |
| Trust-weighted aggregation | Each judge's weight is its accuracy on the labelled evaluation set, worked out offline and saved in `trust_weights.json`, then used in every vote | 0 |
| Agentic peer review | **A two-step review:**<br>1. A code check first (no model call): every route number, seat count and price in the answer must appear in the tool results; a route it names must reach the user's destination; no "booking confirmed", ID numbers or candidate names<br>2. Only if the code check fails, a reviewer agent rewrites the answer once from the list of problems | usually 0, +1 when there is a problem |
| Confidence scoring for human oversight | Confidence = how much the weighted vote agrees × the review result. Below a threshold, the answer adds "please email the official address to confirm" and the tool trace marks it "needs a person" | 0 |

**Flow:**

```mermaid
flowchart LR
    Q[User message<br/>personal data masked] --> J1[A code rules]
    Q --> J2[B embedding examples]
    Q --> AG[Answer agent<br/>v1 tools + RAG]
    AG --> J3[C first tool chosen]
    J1 & J2 & J3 --> W[Trust-weighted vote<br/>trust_weights.json]
    W -->|politics, personal data, out of scope, payment| F[Exact sentence or hand over]
    AG --> R1[Code review]
    R1 -->|fails| R2[Reviewer agent rewrites once]
    R1 -->|passes| C[Confidence]
    R2 --> C
    W --> C
    C -->|high| OK[Answer]
    C -->|low| H[Answer + ask a person to confirm]
```

**Protecting the free quota:** the code counts the requests used today and this minute.
Near the limit it stops the reviewer's rewrite; at the limit it replies with a fixed sentence and the links to the
official seat sheet and email. On a 429 (too many requests) it waits and tries once more.

**Evaluation (the paper's comparison with baselines):**
- A labelled evaluation set of about 60 questions (`eval_questions.csv`): the right category, the tools to use,
  the rules that must not be broken, and the right destination.
- v1 (the baseline) against v2:
  - category accuracy and macro F1 (for each judge, and for the weighted vote)
  - rule-breaking rate and wrong-destination rate
  - average model calls per question
- To stay under 500 requests a day, the evaluation runs over several days, at about 300 requests a day at most.
- `AGENT_MODE=v1|v2` switches the mode; both versions share the same code and data.

**One more thing added while building it: refusals need no model call.** When judges A and B both say "politics"
or "out of scope", or a guest asks about "my order", the code replies with the exact sentence and does not even call
the answer agent, so v2 uses less quota than v1 for these questions.

**What is built:**

| File | What it holds |
|---|---|
| `agents.py` | judge A (code rules), judge B (`EmbeddingJudge`), the code review `code_review()`, the reviewer agent's prompt, the quota guard `QuotaGuard` |
| `aggregation.py` | the 9 question categories, the trust-weighted vote `weighted_vote()`, the confidence score `confidence()` (threshold 0.6) |
| `intent_examples.csv` | labelled examples for judge B, 5 per category, 45 in all (none of them is an evaluation question) |
| `eval_questions.csv` | 60 labelled evaluation questions: 20 dev questions set the trust weights, 40 test questions are used only for the report |
| `evaluate.py` | runs v1 and v2, works out the trust weights and writes `eval_report.md`; results are saved in `eval_results/`, so a run can go on another day |
| `app.py` | `AGENT_MODE` switches v1 / v2; the v2 few-shot chain-of-thought examples; every chat model call goes through the quota guard; the tool trace panel shows each judge's vote and weight, the review and the confidence |

**Offline check (no chat model call):** given v1's wrong 臺中→高雄 answer, the code review found "the answer
tells the user to get off at 臺中, but the user wants to go to 高雄", and the correct 屏東 answer passed.
Made-up seat numbers, amounts and "your ticket is booked" are caught too.

**How to run it:**

```bash
python app.py                                                   # v2 by default; AGENT_MODE=v1 python app.py runs v1
python evaluate.py run --mode v1 --split dev --max-calls 80     # the baseline
python evaluate.py run --mode v2 --split dev --max-calls 80
python evaluate.py weights                                      # trust_weights.json from the dev questions
python evaluate.py run --mode v1 --split test --max-calls 120
python evaluate.py run --mode v2 --split test --max-calls 120
python evaluate.py report                                       # writes eval_report.md
```

#### v1 against v2 (2026-11-09, gemini-3.5-flash-lite)

Full record: [`eval_report.md`](eval_report.md) (every answer), `eval_results/` (raw results),
[`trust_weights.json`](trust_weights.json).

**1. Automatic checks (40 test questions)**

The 20 dev questions gave the same picture, with one difference: v2's tool choice was 19/20. For d15 (a fake
promise of a free ticket) it did not call `transfer_to_human`, but it still gave the official email.

| Measure | v1 | v2 |
|---|---|---|
| Tool choice correct | 40/40 | 40/40 |
| Must / must-not words correct | 40/40 | 40/40 |
| Code review finds a factual problem | 0/40 | 0/40 |
| Chat model calls per question | 1.80 | **1.65** (dev: 1.80 → 1.60) |
| Questions answered with no model call | 0 | **10/60** (politics, out of scope, a guest asking about an order) |
| Marked "needs a person" | — | 1/40 |

**2. Question category (40 test questions)**

Trust weights from the 20 dev questions: A 0.955, B 0.773, C 0.882.

| Judge | Accuracy | Macro F1 |
|---|---|---|
| A code rules | 92% | 0.898 |
| B embedding examples | 85% | 0.891 |
| C the answer agent's first tool (no vote when it uses no tool) | 70% | 0.504 |
| **Trust-weighted vote** | **95%** | **0.945** |

**3. Stability: the same question 5 times** (「我在臺中讀書，要回高雄投票，有哪些車？」, the known issue of v1.0.0)

| | v1 | v2 |
|---|---|---|
| Code review finds a problem | 0/5 | 0/5 |
| Read by hand: the answer misleads the user | **1/5** (it lists only routes where 臺中 is a get-off stop, not aimed at 高雄), and 1 more is unclear | **0/5** (all 5 say clearly: no boarding at 臺中, get on at a first station, get off at 高雄) |

**4. Reading all 120 answers by hand**

| | v1 | v2 |
|---|---|---|
| Factual errors | 0 | **2**: t37 says routes of 11/27 leave on 11/28; t36 says "the driver will not phone each passenger" (not in the data) |
| Unsupported statements | 0 | 1: d06 "a common choice", "every plan includes one ticket" |
| Says "I have handed you over" (the tool cannot do that) | 1 | 2 |

**Conclusion:**
- On these 60 questions v1 already gets full marks on the automatic checks, so v2 is **not more accurate on the
  automatic measures**.
- v2 helps in three ways:
  - **It uses less quota:** 8–11% fewer calls per question, and no call at all for refusals.
  - **It is more stable on the known hard question:** 臺中→高雄 was answered well 5 times out of 5, while v1
    misled once.
  - **It adds an explainable category and a confidence score:** the weighted vote is more accurate than any
    single judge.
- But v2 also made 2 factual errors, and the confidence score did not flag them (both were 1.0), because:
  - the code review does **not check dates** yet;
  - an answer with no tool call (t36) has no tool result to check against.

**Limits:**
- The evaluation set has only 60 questions, each run once (the stability test is 1 question × 5).
- We wrote judge A's rules after seeing some of the questions, so A's score is on the high side.
- The hand reading was done by the developer.

**Next steps:**
- Add a date check to the code review.
- Lower the confidence of factual statements when there is no tool result.
- Catch phrases like "I have handed you over" in the review.
- Use a larger evaluation set, with several runs of each question.

The work happens on the `v2-trust-aware` branch, so `v1.0.0` is not changed.

## Project Files

```text
vote-bus-agent/
├── app.py               # the agent: database, RAG, tools, agent loop and chat screen
├── routes.csv           # fallback copy of the official sheet (2026/11/03); live data is read from the sheet
├── plans.csv            # 7 flyingV plans
├── project_info.csv     # 10 project facts
├── orders_test.csv      # made-up orders, same columns and masking as the real order sheet
├── rules.txt            # the ticket and boarding rules, searched with RAG
├── test_agent.py        # tool-choice, scope and order-access tests
├── test_results.md      # the latest test results
├── agents.py            # v2: judges A and B, the code review, the reviewer prompt, the quota guard
├── aggregation.py       # v2: categories, the trust-weighted vote, the confidence score
├── intent_examples.csv  # v2: labelled example questions for judge B
├── eval_questions.csv   # v2: 60 labelled evaluation questions (dev 20, test 40)
├── evaluate.py          # v2: compares v1 and v2, works out the trust weights
├── requirements.txt     # Python packages
├── DEPLOY.md            # deployment notes (in Chinese)
├── deploy/              # start.sh and a macOS launchd file (start at log-in, restart if it stops)
├── .env.example         # a sample settings file (no key)
├── .gitignore           # .env, *.db and the vector cache are not uploaded
├── README.md            # this file (English)
├── README.zh-TW.md      # the same in Traditional Chinese
└── images/              # screenshots
```

## How to Install and Run It

1. Download the project and install the packages (Python 3.10 or newer):

   ```bash
   git clone https://github.com/HowardHung2/NKUST-DL-vote-bus-agent.git
   cd NKUST-DL-vote-bus-agent
   pip install -r requirements.txt
   ```

2. Copy `.env.example` to `.env` and put your own key after `API_KEY=`. The model must support tool calling.
   Leave `ORDER_SHEET_CSV_URL` empty to run in test mode with the made-up orders.

   ```bash
   cp .env.example .env        # macOS or Linux
   copy .env.example .env      # Windows
   ```

3. Start the app, then open the link in the console (usually <http://127.0.0.1:7860>).
   In test mode you can log in with the made-up order number `900000000000000103`:

   ```bash
   python app.py
   ```

4. (Optional) Run the tests. They wait between questions because free API keys allow few calls per minute:

   ```bash
   python test_agent.py
   ```

## Safety for Public Use

The app listens on `127.0.0.1` only. For public use, the app also logs users out after 30 minutes without a message, limits wrong order numbers
per visitor IP (10 in 15 minutes), serves several users at once, and makes every page function private
(it cannot be called through Gradio's API).

## Data Sources and Notes

- Seats are read live from the official sheet. Routes, plans, rules and contact details come from the
  [flyingV project page](https://www.flyingv.cc/projects/37638), the official
  [route and seat sheet](https://docs.google.com/spreadsheets/d/1P22Kxg0UCqs2CqP9ISUtMj8pIrC_Y2xFGJa1xAaYCSo/edit?usp=sharing),
  the official booking form's instructions, and the project FAQ (copied on 2026/11/06).
- **Every order in `orders_test.csv` is made up.** The tests always use it, never the real order sheet.
- The real order sheet link goes **only** in `.env` (`ORDER_SHEET_CSV_URL`), never in this repository:
  anyone with the link can read the whole order sheet. A safer next step is to set the sheet to "restricted" and
  read it with a Google service account.
- The photo on the page (Taipei Main Station) is from the project's flyingV page, used with the organizer's permission.
  The rules about age (18–35), where you may get off, meeting times and what to bring to vote were added to
  `rules.txt` from the official route and eligibility images on that page.
- Built together with an AI assistant (Claude Code); I ran, tested and checked every part.
