# Afandem pilot: free tool-calling model options (checked 5 Nov 2026)

All facts below were checked on **2026-11-05**. Each one is marked with how it was checked:

- **[official]**: read on the provider's own page or API.
- **[3rd-party]**: an aggregator or blog, not confirmed on an official page.
- **[forum]**: user posts.
- **[estimate]**: my own arithmetic.

Where a page would not load, the text says so. Limits change often, so re-check the console dashboards on sign-up day.

---

## 0. Recommendation in one table

The workload is 30 scenarios × 6 text columns = 180 conversations. With multi-round tool use that is about 360–720 calls per model, at 1.5–5k input tokens and about 0.2k output tokens per call (thinking off).

| # | Model (exact id) | Family | Endpoint (base URL) | Free limits | Pilot days (360 / 540 / 720 calls) | Card? |
|---|---|---|---|---|---|---|
| 1 | `gemini-3.5-flash-lite` | Google (closed) | `https://generativelanguage.googleapis.com/v1beta/openai/` (OpenAI-compatible, beta), or the native Gemini API | ~10 RPM, 250K TPM, **500 RPD** [3rd-party; Google shows the numbers only in the AI Studio console] | **1 / 2 / 2** | No |
| 2 | `qwen/qwen3.8-27b` on **Groq** (the same weights as the planned paid Qwen3.8-27B) | Alibaba Qwen (open) | `https://api.groq.com/openai/v1` | 30 RPM, 1K RPD, 8K TPM, **200K TPD** [official] | **3 / 9 / 19** using Groq alone. With the Cloudflare overflow (below): **2 / 5 / 9** [estimate] | No |
| 3 | `deepseek-ai/deepseek-v4.1-flash` on **NVIDIA build** (alternative: `mistralai/mistral-large-4-1t-a52b` for a Mistral family) | DeepSeek (open) | `https://integrate.api.nvidia.com/v1` | ~40 RPM, no daily cap reported [forum] | **1 / 1 / 1** | No card reported |
| 4 | `Fanar-2.0-Tools` (once access is granted) | QCRI Fanar (Arabic-centric) | `https://api.fanar.qa/v1` | 50 RPM [official]. No daily cap published; read the `ratelimit-policy` response header | **1 / 1 / 1** | No (request form) |
| 5 (optional) | Local `gpt-oss:20b` in Ollama (alternative: `gemma4:26b-a4b-it-qat`) | OpenAI open-weight, local | `http://localhost:11434/v1` | Unlimited (your machine) | 2,000 calls take about 4–8 h [estimate] | No |

**What sets the length of the pilot:** Qwen3.8-27B on Groq. Its 200K tokens/day cap allows only about 40–120 calls a day, depending on prompt size. Every other slot finishes within 1–2 days. All five slots can run in parallel, so the whole pilot takes about one week if prompts average 2.5k tokens or less. Start Qwen on day 1.

**Engineering:** all five slots accept the same OpenAI `chat.completions` + `tools` request, so one converter is enough. Four quirks need care:

- **Gemini 3.x:** each assistant `tool_calls` message has to go back exactly as it was received, including any Google `extra_content` or thought-signature field.
- **Fanar:** `tool_choice` accepts only `auto` or `none`, and the context window is 8K.
- **Ollama:** `tool_choice` is not supported.
- **Gemma via Google's API:** this route needs the native API (see §2), which is why Gemma 4 is a bench alternate rather than a slot.

---

## 1. Workload assumptions and quota arithmetic [estimate]

| Scenario | Calls per model | Tokens per call (in + out) | Tokens per model |
|---|---|---|---|
| low | 360 | 1.5k + 0.2k | 0.61 M |
| mid | 540 | 3.0k + 0.2k | 1.73 M |
| high | 720 | 5.0k + 0.2k | 3.74 M |

| Route | Binding limit | Calls/day (low / mid / high) | Days for that scenario's calls (low / mid / high) |
|---|---|---|---|
| AI Studio, gemini-3.5-flash-lite | 500 RPD | 500 | 1 / 2 / 2 |
| AI Studio, Gemma 4 31B | 1,500 RPD (3rd-party) | 1,500 | 1 / 1 / 1 |
| Groq, qwen3.8-27b | 200K TPD (no prompt caching on this model) | 118 / 62 / 38 | 3.1 / 8.6 / 18.7 |
| Cloudflare, @cf/qwen/qwen3.8-27b | 10,000 neurons/day | 84 / 55 / 38 | 4.3 / 9.8 / 18.9 |
| Groq + Cloudflare for Qwen together | both | 202 / 117 / 76 | 1.8 / 4.6 / 9.4 |
| Cloudflare, @cf/google/gemma-4-26b-a4b-it | 10,000 neurons/day | 524 / 306 / 196 | 0.7 / 1.8 / 3.7 |
| Cloudflare, @cf/openai/gpt-oss-120b (0.4k output for reasoning) | 10,000 neurons/day | 133 / 81 / 54 | 2.7 / 6.6 / 13.4 |
| Groq, gpt-oss-120b | 200K TPD, but cached tokens don't count toward rate limits | ~same as Qwen, up to ~2× better with a cache-friendly prefix | ~2–10 |
| NVIDIA build (any model) | ~40 RPM | ≫720 | ≤1 |
| Fanar | 50 RPM | ≫720 | ≤1 |
| OpenRouter `:free` with no credits bought | 50 requests/day, **shared across all free models** | 50 | 7 / 11 / 15 (one model) |
| OpenRouter `:free` after a one-time ≥10-credit purchase | 1,000/day | 1,000 | 1 / 1 / 1 |
| SambaNova free | 20 RPD | 20 | 18 / 27 / 36 |

The Cloudflare 10,000 neurons/day are shared by every Workers AI model on the account. Running Qwen overflow there leaves nothing for other Cloudflare models that day.

---

## 2. Google AI Studio (Gemini API) free tier

| Item | Finding | Source |
|---|---|---|
| gemini-3.5-flash-lite on the free tier | Yes. Input and output are "Free of charge". Context caching: "Not available". Search grounding: "Not available". **"Used to improve our products": Yes (free) / No (paid)** | [official] https://aistudio.google.com/docs/pricing (`ai.google.dev/gemini-api/docs/pricing` 301-redirects there) |
| Other free Gemini models | gemini-3.8-flash, gemini-3.6-flash and gemini-3.1-flash-lite are "Free of charge" on the free tier. gemini-3.5-flash does not appear on the pricing page | [official] same page |
| Gemma 4 | "Free of charge" for input, output and caching. The paid tier is "Not available", so Gemma 4 is free only | [official] same page |
| RPM / TPM / RPD | Google's rate-limit page no longer prints free-tier numbers: limits "can be viewed in Google AI Studio", and "RPD quotas reset at midnight Pacific time". Third-party figures: **3.5 Flash-Lite 10 RPM, 250K TPM, 500 RPD**; 3.8 Flash and 3.6 Flash 5 RPM, 250K TPM, **20 RPD** (too low for the pilot); 3.1 Flash-Lite 10–15 RPM, 500 RPD; **Gemma 4 31B and 26B: 15 RPM, unlimited TPM, 1,500 RPD** (Gemma figures from a July 2026 article). Limits are per project per model, so extra keys in one project add nothing | [official] https://aistudio.google.com/docs/rate-limits ; [3rd-party] https://www.scriptbyai.com/gemini-api-free-tier-limits/ ; [3rd-party] https://tilnote.io/pages/6a51b3398d9a59d14c1c174c (dated 2026-07-11) |
| Function calling | Supported for gemini-3.5-flash-lite (capability list: "Function calling", "Structured outputs", "Thinking"). Latest update: July 2026. Free vs paid gating is only shown for grounding and caching, not for function calling, so function calling should work on the free tier. Not tested here (no key); do a 1-call smoke test | [official] https://aistudio.google.com/docs/models/gemini-3.5-flash-lite |
| Thinking control | gemini-3.5-flash-lite: default "On (minimal)". Levels: minimal / low / medium / high (`thinking_level`). The docs do not say that `minimal` turns thinking off completely. On the OpenAI-compatible endpoint, `reasoning_effort` maps to `thinking_level`. Thinking cannot be fully disabled on Gemini 3 models | [official] https://aistudio.google.com/docs/thinking ; https://aistudio.google.com/docs/openai |
| OpenAI-compatible endpoint | `https://generativelanguage.googleapis.com/v1beta/openai/`, with `tools` and `tool_choice:"auto"`. Labelled "still in beta". Gemma is not mentioned on that page | [official] https://aistudio.google.com/docs/openai |
| Multi-turn function calling | Gemini 3 thinks internally while calling functions. "The SDKs automatically handle thought signatures". For stateless use you must send back the model's thought and function-call steps "exactly as received". Calling modes: auto / any / none / validated | [official] https://aistudio.google.com/docs/function-calling |
| Gemma 4 function calling | Supported on the Gemini API (`gemma-4-31b-it`, `gemma-4-26b-a4b-it`, "Define tools as function declarations"). Thinking can be switched on (`high`) or off (`minimal`). The examples use the native API, so plan on native `generateContent` for Gemma; test the OpenAI-compatible endpoint first | [official] https://ai.google.dev/gemma/docs/core/gemma_on_gemini_api |
| Data-use terms | Unpaid Services: content is used "to provide, improve, and develop" Google products, and "human reviewers may read, annotate, and process your API input and output". Do not send sensitive data. A special clause covers the EEA, Switzerland and the UK; read it if you are based there. You must be 18 or older. Terms effective 23 Mar 2026. **Acceptable for Afandem, since all data will be public** | [official] https://aistudio.google.com/docs/terms |
| Regions | Egypt, the UK and Qatar are all on the available-regions list | [official] https://aistudio.google.com/docs/available-regions |

---

## 3. OpenRouter `:free` models with `tools` (fetched from the API)

I downloaded `https://openrouter.ai/api/v1/models` on 2026-11-05: 455 models in total, 12 ending in `:free`, and 11 of those list `tools` in `supported_parameters`.

| id | Context | Max output | Notes (from the API description) |
|---|---|---|---|
| `google/gemma-4-31b-it:free` | 262,144 | 32,768 | Gemma 4 31B dense; reasoning toggle; tools and tool_choice |
| `google/gemma-4-26b-a4b-it:free` | 262,144 | 32,768 | Gemma 4 MoE, 3.8B active |
| `nvidia/nemotron-3-ultra-550b-a55b:free` | 1,000,000 | 65,536 | 550B MoE; `reasoning_effort` |
| `nvidia/nemotron-3.5-super-vl:free` | 1,000,000 | 131,072 | 120B-A12B multimodal |
| `nvidia/nemotron-3.5-lightning:free` | 1,000,000 | 65,536 | 30B-A3B |
| `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free` | 256,000 | 65,536 | omni 30B-A3B |
| `cohere/north-mini-code:free` | 256,000 | 64,000 | coding-agent MoE 30B-A3B |
| `dots-studio/dots-3-note-preview:free` | 512,000 | 460,800 | 280B-A16B; **expires 2026-12-31** |
| `xingchen-agi/xing4.0-29b-a4b:free` | 262,144 | 235,929 | China Telecom TeleAI |
| `recursive/flint-v1.0:free` | 262,144 | 235,929 | 40B-A2.5B coding; **no `tool_choice`** listed |
| `liquid/lfm-2.5-2.6b:free` | 65,536 | 8,192 | 2.6B |
| (`nvidia/nemotron-3.5-content-safety:free`: no tools) | 128,000 | | guard model |

Zero-price entries without the `:free` suffix, both unsuitable:

- `openrouter/free`: a router that **picks a free model at random**, which is useless for a benchmark.
- `stealth/crouton-alpha`: a stealth model, so expect logging and a short life.

None of the free variants is Qwen, Llama, gpt-oss, DeepSeek, Kimi or Mistral. Those exist on OpenRouter as paid ids only.

**Limits** (official: https://openrouter.ai/docs/api/reference/limits, no last-updated date shown):

- Fewer than 10 credits purchased (all time): **20 requests/minute, 50 requests/day**.
- At least 10 credits purchased: **20 requests/minute, 1,000 requests/day**.
- The page says "10 credits", not "$10". It also contains an unrendered placeholder, `{FREE_MODEL_CREDITS_THRESHOLD - 1}`, so the exact threshold wording is slightly broken on the live page.
- A negative balance blocks free models as well.
- Cloudflare DDoS protection blocks extreme bursts.

**Data use:** account settings for training and logging are separate for paid and free models. If you opt out of training, OpenRouter will not route to providers that train, which can hide some free endpoints (https://openrouter.ai/docs/guides/privacy/provider-logging). For Afandem, enable the free-model setting, since the data is public anyway.

**Verdict:** without buying credits, 50/day shared across all models is too little for a primary slot. It works as a 1-model backup or for smoke tests. If a single 10-credit purchase ever becomes possible, it raises the cap 20× to 1,000/day.

---

## 4. Other free API tiers (checked 2026-11-05)

| Provider | Free tool-capable models (relevant) | Limits | Card needed? | OpenAI-compatible | Data use | Verdict | Source |
|---|---|---|---|---|---|---|---|
| **Groq** (Free plan) | `qwen/qwen3.8-27b` (Preview; 131,072 context; max output 16,384; tools + parallel tools + JSON schema; `reasoning_effort` default **none**). `openai/gpt-oss-120b` and `openai/gpt-oss-20b` (Production; tools, no parallel tools; default effort medium). Llama 4 no longer appears in the models or limits tables | Free Plan table: qwen3.8-27b **30 RPM / 1K RPD / 8K TPM / 200K TPD**. gpt-oss-120b and 20b: same. Limits apply per organization. Prompt caching only on gpt-oss models, and "Cached tokens do not count towards your rate limits" | No. A payment method is required only to upgrade to Developer | Yes, `https://api.groq.com/openai/v1` | "By default, Groq does not retain customer data for inference requests" | **Use for Qwen3.8-27B.** It is the only no-card, high-quota host of the planned paid Qwen | [official] https://console.groq.com/docs/rate-limits (the default tab is "Free Plan Limits", verified in the HTML), https://console.groq.com/docs/models , https://console.groq.com/docs/tool-use , https://console.groq.com/docs/model/qwen/qwen3.8-27b , https://console.groq.com/docs/prompt-caching , https://console.groq.com/docs/your-data , https://console.groq.com/docs/billing-faqs |
| **Cerebras** (Free Trial) | `gpt-oss-120b` (free-tier context 65k), `qwen-3.8-27b` (64k). Both have tool use with parallel calls | 5 RPM, 30K uncached TPM, 90K total TPM, 1M TPH, **1M TPD** | **Yes.** "$5 in free credits after adding a verified payment method", which expire after 30 days. "not a permanently free tier" | Yes (base URL not shown on the pages I loaded; widely documented as `https://api.cerebras.ai/v1`, not re-verified) | Not checked | Fallback for Qwen if a card can be added (still $0 spent) | [official] https://inference-docs.cerebras.ai/support/rate-limits , https://inference-docs.cerebras.ai/models/overview , https://inference-docs.cerebras.ai/capabilities/tool-use |
| **Mistral** La Plateforme ("Experiment"/Free) | Mistral Small/Medium/Large (third-party list) | **Not verified.** Third-party sources give about 1 req/s, 500K TPM and 1B tokens/month, but say these may be stale 2024 figures and that real limits show per workspace in the Admin console | No card; verified phone number [3rd-party] | Mostly (`https://api.mistral.ai/v1`) | Free-plan inputs "may be used to train" [3rd-party] | Optional, unverified. **docs.mistral.ai failed to load (connection error) and the help-center articles returned 404**; mistral.ai/pricing shows no API free tier. For the Mistral family, use Mistral Large 4 on NVIDIA instead | [3rd-party] https://www.activepieces.com/blog/mistral-api-free-tier-limits-models-credits-2026 (checked 2026-10-30); [official, inconclusive] https://mistral.ai/pricing |
| **GitHub Models** | none | **Retired**: "As of July 30, 2026, GitHub Models has been fully retired" | n/a | n/a | n/a | Not available | [official] https://docs.github.com/en/github-models/use-github-models/prototyping-with-ai-models |
| **Cloudflare Workers AI** | Function calling confirmed on the model pages for `@cf/qwen/qwen3.8-27b` (262k context; reasoning low / medium / **xhigh default**), `@cf/google/gemma-4-26b-a4b-it` (256k), `@cf/openai/gpt-oss-120b` (128k), `@cf/openai/gpt-oss-20b`, `@cf/qwen/qwen3-30b-a3b-fp8` (32k), `@cf/meta/llama-4-scout-17b-16e-instruct`, `@cf/mistralai/mistral-small-3.1-24b-instruct` (128k). Also listed: glm-4.7-flash, glm-5.3, deepseek-v4.1-flash-1017. kimi-k2.6 and k2.7-code require paid billing | **10,000 Neurons/day** free, resetting at 00:00 UTC. Neurons per million tokens (in / out): qwen3.8-27b 40,909 / 290,909; gemma-4-26b-a4b 9,091 / 27,273; gpt-oss-120b 31,818 / 68,182 | Workers Free plan; the pricing page doesn't mention a card | Yes, `https://api.cloudflare.com/client/v4/accounts/<ACCOUNT_ID>/ai/v1` (page doesn't say whether `tools` passes through on this path; test it) | Model pages say "Zero data retention: Yes" | Good **overflow for Qwen3.8-27B**; Gemma 4 26B fits comfortably | [official] https://developers.cloudflare.com/workers-ai/platform/pricing/ , https://developers.cloudflare.com/workers-ai/models/qwen3.8-27b/ (and the other model pages), https://developers.cloudflare.com/workers-ai/configuration/open-ai-compatibility/ |
| **Hugging Face Inference Providers** | any routed model | **Free users: "None"** monthly credits. PRO users get $2.00/month. Pay-as-you-go needs purchased credits | Credits purchase required | Yes, `https://router.huggingface.co/v1` | Provider-dependent | **Not free any more** for free accounts | [official] https://huggingface.co/docs/inference-providers/pricing |
| **NVIDIA build / NIM API** | Public `GET https://integrate.api.nvidia.com/v1/models` (no auth) lists 84 models, including `google/gemma-4-31b-it` (card: function calling), `deepseek-ai/deepseek-v4.1-flash` (card: tool calling, thinking), `mistralai/mistral-large-4-1t-a52b` (card: native function calling, `tool_choice`, reasoning default **high**), `openai/gpt-oss-20b` (card: function calling), `moonshotai/kimi-k2.6` (card page did not render), `z-ai/glm-5.3-flash`, `minimaxai/minimax-m3.1-flash`, Nemotron 3/3.5. **No Qwen 3.x, no Llama 4 and no gpt-oss-120b** | **~40 RPM** per key; users describe it as "unlimited but RPM". Increases are not self-serve. Some threads mention credits ("Request More +4,000 credits"), so the scheme may vary | Free NVIDIA Developer account; "no credit card" [3rd-party]. Login required for keys (`isLoginRequired: true` in page data) | Yes, `https://integrate.api.nvidia.com/v1` | Governed by the "NVIDIA API Trial Terms of Service": for evaluation, not production. Data-use wording is contested in the forums, but fine for public data | **Use for an open-weight family** (DeepSeek or Mistral) | [official] model list from the API above; model cards at https://build.nvidia.com/deepseek-ai/deepseek-v4.1-flash/modelcard etc.; [forum] https://forums.developer.nvidia.com/t/is-nim-free/369368 (May 2026) |
| **SambaNova** | DeepSeek-V3.1, Meta-Llama-3.3-70B-Instruct, gpt-oss-120b (production); DeepSeek-V3.2, gemma-4-31B-it (preview) | Free tier: **20 RPM / 20 RPD / 200K TPD** per model ("Applied when there is no payment method linked") | No (Free tier = no payment method) | Yes | Not checked | Too little quota (20 RPD) | [official] https://docs.sambanova.ai/docs/en/models/rate-limits (the older docs.sambanova.ai/cloud/... URL is 404) |
| **Together AI** | – | "Together AI does not currently offer free trials"; "minimum $5 credit purchase" | Yes (prepay) | Yes | – | Not free | [official] https://support.together.ai/articles/1862638756-changes-to-free-tier-and-billing-july-2025 |
| **Fireworks** | – | The $1 sign-up credit was removed from the pricing page on 22 Oct 2026; accounts without a payment method are reportedly held to 10 RPM | Effectively yes | Yes | – | Not free | [3rd-party] https://www.usagepricing.com/blueprint/activity/fireworks-ai-2026-10-22-signup-credit-dropped (fireworks.ai itself not opened) |
| **DeepInfra** | – | "You have to add a card or pre-pay or you won't be able to use our services." 200-concurrent cap | Yes | Yes | – | Not free | [official] https://deepinfra.com/pricing |
| **Chutes** | – | The starter guide describes pay-as-you-go only. Third-party sources say the free tier ended 27 Feb 2026 | Yes (subscription or PAYG) | Yes, `https://llm.chutes.ai/v1` | – | Not free | [official] https://www.chutes.ai/docs/guides/starter-guide |
| **Ollama Cloud** | cloud models | No free plan; "Pay as you go" at $0 base plus per-token pricing; Pro $20/month. "Prompt or response data is never logged or trained on" | Yes for cloud | Yes (`https://ollama.com/v1`) | no training | Not free (local Ollama is) | [official] https://ollama.com/pricing |

---

## 5. Fanar (QCRI / HBKU) API

| Item | Finding | Source |
|---|---|---|
| Cost | Site FAQ: "Is Fanar free? Yes, it's completely free to use!" This is about the platform generally; no API price exists anywhere | [official] https://fanar.qa/en |
| Access | By request form: https://api.fanar.qa/request/en (embeds https://chat.fanar.qa/api-access/request/en). **The OpenAPI spec says: "Fanar-2.0-Tools requires additional authorization and is not allowed by default." Ask for it explicitly in the form** | [official] https://api.fanar.qa/openapi.json (the rendered docs at https://api.fanar.qa/docs load the reference from a CDN) |
| Rate limits | Default for all models: Fanar, Fanar-S-1-7B, Fanar-C-1-8.7B, **Fanar-C-2-27B, Fanar-2.0-Tools: 50 requests/minute each**; Sadiq-2 validate 200/min; several audio, image and translate models 20/day. No daily cap is listed for chat models. Response headers `x-ratelimit-*` and `ratelimit-policy` (e.g. `100;w=86400`) show the real window. Higher limits are available on request | [official] openapi.json `info.description` |
| Tool-calling rules (from the spec's Python example) | 8K context, and an over-long request gets **HTTP 413**. `tool_choice` accepts only `"auto"` or `"none"`; **`"required"`, a named function, and `parallel_tool_calls=false` are refused**. A system message, if sent, must come first. Return one `tool` message per call, in call order. "a reply that starts with '{' is taken for a tool call and lost". Each round trip counts against the rate limit | [official] openapi.json code samples |
| Endpoint | `https://api.fanar.qa/v1/chat/completions` (OpenAI-shaped). `/v1/models` returns 401 without a key | [official] |
| Data use | Not stated in the spec | – |
| Open weights | `QCRI/Fanar-2-27B-Instruct` (Apache-2.0, Gemma-3-27B base, **32K context**, "generic tool use", MSA plus Gulf, Levantine and **Egyptian** dialects). GGUF quants exist (e.g. mradermacher, Q4_K_M ≈16–17 GB). Whether the API's `Fanar-2.0-Tools` is the same checkpoint is not stated | [official] https://huggingface.co/QCRI/Fanar-2-27B-Instruct |

**Pilot impact:** 50 RPM, so the pilot fits in under a day. The 8K window is the main risk. Keep the Fanar tool list compact and count HTTP 413 as a separate "context overflow" outcome. Don't silently trim history for one model only.

---

## 6. Local inference on the M4 Pro with 24 GB

**Facts checked**

- **Ollama's OpenAI-compatible endpoint** `http://localhost:11434/v1/chat/completions` supports `tools` and `reasoning_effort`. **`tool_choice` is not supported**, nor are `logit_bias`, `n` or logprobs. [official] https://docs.ollama.com/api/openai-compatibility
- **Ollama library** (sizes from the tag pages, https://ollama.com/library/<name>/tags):

| Tag | Size | Context | Capabilities |
|---|---|---|---|
| `gpt-oss:20b` | 14 GB | 128K | tools, thinking |
| `gemma4:26b-a4b-it-qat` | 16 GB | 256K | tools, thinking, vision |
| `gemma4:26b-a4b-it-q4_K_M` | 18 GB | 256K | |
| `gemma4:12b-it-qat` | 7.2 GB | 256K | |
| `gemma4:31b-it-qat` | 19 GB | | |
| `qwen3.5:9b-q4_K_M` | 6.6 GB | | tools, thinking |
| `qwen3.8:27b` (Q4) | **18 GB** | | tools, thinking, vision |
| `qwen3.6:27b-q4_K_M` | 17 GB | | |
| `mistral-small3.2:24b` | 15 GB | | tools |
| `nemotron-3.5-lightning` | 19 GB | | MLX / nvfp4 only |

  No `jais`, `fanar` or `allam` entries exist in the Ollama library (404).
- **Measured speeds on an M4 Pro (16-core GPU, 24 GB) from community oMLX benchmarks:**
  - Gemma-4-26B-A4B 4-bit: **579.6 tok/s prompt processing, 66.2 tok/s generation, 14.3 GB peak at 1k context**; 424 PP / 37 TG / 18.5 GB at 64k. oMLX v0.4.0, 2026-06-03. https://omlx.ai/benchmarks/bgp3x8tq
  - Qwen3.5-9B 4-bit: about 362 PP / 46–50 TG.
  - Dense 27B, 6-bit, M4 Pro, on a 48 GB machine: about 122 PP / 11 TG.
  - No measured M4 Pro number was found for gpt-oss-20b.
  - [3rd-party] the omlx.ai community benchmark pages
- **Arabic-centric local options:**
  - **Jais-3 family** (released 29 Sep 2026; Apache-2.0; 0.9B / 3.7B / 7B / 32B / MoVA-36B-A4B / 375B-A23B). `inception42/Jais-3-7B` has a 512K context, an official GGUF (`IFM/Jais-3-7B-GGUF`, Q4_K_M…BF16) and official MLX 4-bit and 8-bit builds. It **supports tool calling, but only through vLLM or SGLang `--tool-call-parser k2_horizon`** (formats json / xml / xml_typed, default xml). It recommends `reasoning_effort="high"` and ≥32K output tokens, which is slow locally. Nothing in its docs suggests Ollama, llama.cpp or LM Studio can parse its tool calls, so treat it as **experimental**. [official] https://huggingface.co/inception42/Jais-3-7B
  - **Fanar-2-27B-Instruct**: dense 27B with tool calling. At Q4 (~16–17 GB) it is borderline for 24 GB and slow (dense 27B ≈ 11 tok/s generation).
  - **ALLaM-7B-Instruct-preview**: GGUF exists, no tool calling.

**Feasibility and wall-clock** [estimate]

Per call this assumes 3k tokens in and 0.2k out with thinking off. With thinking on, add (thinking tokens ÷ generation speed). Under 24 GB unified memory, macOS lets the GPU wire only part of RAM by default, so ≥18 GB models are risky.

| Model (local) | Fits 24 GB? | Speed basis | s/call (1.5k / 3k / 5k input) | 2,000 calls |
|---|---|---|---|---|
| `gemma4:26b-a4b-it-qat` or MLX 4-bit | Yes (14–18 GB peak) | measured ~550 PP / 60 TG | 6 / 9 / 12 | **~3.5–7 h** |
| `gpt-oss:20b` (MXFP4) | Yes (14 GB) | not measured; MoE ~3.6B active, assumed similar to Gemma 26B-A4B plus low-effort reasoning tokens | ~8 / 11 / 15 | **~4–8 h** |
| `qwen3.5:9b-q4_K_M` | Yes (6.6 GB) | measured ~360 PP / 48 TG | 8 / 12.5 / 18 | ~4.5–10 h |
| `qwen3.8:27b` / `Fanar-2-27B` Q4 | Borderline (17–18 GB plus KV cache) | ~120 PP / 11 TG | 31 / 43 / 60 | **~17–33 h**, plus swapping risk. Not recommended |
| `Jais-3-7B` Q4 | Yes | ~7B dense | ~8–12 (more with high reasoning) | ~5–7 h, if tool parsing can be made to work |

**Local caveats**

- Ollama does not support `tool_choice`, so "forced call" items can't be tested locally.
- Set the context length explicitly (for example via the `OLLAMA_CONTEXT_LENGTH` environment variable, or `num_ctx`) to ≥16K so 5k-token prompts plus history aren't truncated. I did not re-check Ollama's current default.
- Run requests sequentially so the KV-cache prefix (system prompt + tools) is reused.
- Install with the macOS app from ollama.com or `brew install ollama`.

---

## 7. Recommended free pilot set: details

### 7.1 Google: `gemini-3.5-flash-lite` (AI Studio free tier)

- **Endpoint:** `https://generativelanguage.googleapis.com/v1beta/openai/` with `model="gemini-3.5-flash-lite"`. The native fallback is `https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash-lite:generateContent`.
- **Limits:** ~10 RPM / 250K TPM / 500 RPD (3rd-party). Read the real numbers at https://aistudio.google.com/rate-limit after login. RPD resets at midnight Pacific.
- **Pilot:** 1–2 days. 500 calls at 10 RPM ≈ 50 min of runtime per day.
- **Sign-up:**
  1. Sign in at https://aistudio.google.com with a Google account (18+).
  2. Click "Get API key"; this auto-creates a Cloud project.
  3. Don't enable billing; staying unbilled is what keeps it free.
- **Caveats:**
  - Free-tier prompts are used to improve Google products and may be read by human reviewers. That's fine here because the data is public.
  - Thinking defaults to "minimal" and cannot be fully disabled on Gemini 3, so record `reasoning_effort` per run.
  - Gemini 3 needs the assistant tool-call turns echoed back unchanged (thought signatures).
  - Function calling on the free tier isn't explicitly gated, but do a 1-call smoke test.
  - The planned paid model is the same id, so pilot results carry over.

### 7.2 Qwen: `qwen/qwen3.8-27b` on Groq (Free plan)

- **Endpoint:** `https://api.groq.com/openai/v1`. Tools and parallel tool calls are supported. `reasoning_effort` defaults to `none`; `low`, `medium` and `high` (= native xhigh) are also accepted.
- **Limits:** 30 RPM / 1K RPD / **8K TPM / 200K TPD**, per organization. Prompt caching (which doesn't count toward limits) is not available for this model.
- **Pilot:** 3 / 9 / 19 days for the low / mid / high scenarios. This is the bottleneck. Options to fit about one week:
  1. Keep tool schemas and system prompts lean, aiming for ≤2.5k tokens per call.
  2. Add `@cf/qwen/qwen3.8-27b` on Cloudflare Workers AI as overflow (~40–85 calls/day; set `reasoning_effort` low or none because the default is **xhigh**). Combined that is 2 / 5 / 9 days. Log the provider on every row, since the hosts may quantize differently.
  3. Or run Qwen on one domain only in the pilot.
  4. If a card can be added at no cost, Cerebras `qwen-3.8-27b` (1M TPD on its $5 / 30-day trial) finishes in 1–4 days.
- **Sign-up:** https://console.groq.com → sign up (email, Google or GitHub) → API Keys → create. The free plan is the default, with no card. Don't create extra organizations to multiply quota; limits are per organization.
- **Caveats:**
  - The model is "Preview" on Groq and "may be discontinued at short notice".
  - Max output is 16,384 and context is 131,072.
  - Groq keeps no inference data by default.
  - **The planned paid Qwen3.8-27B is the same model**, so free and paid results are directly comparable. Note the host and quantization ("TruePoint Numerics").

### 7.3 Open-weight second family: `deepseek-ai/deepseek-v4.1-flash` on NVIDIA build (or `mistralai/mistral-large-4-1t-a52b`)

- **Endpoint:** `https://integrate.api.nvidia.com/v1` (OpenAI-compatible) with your `nvapi-…` key.
- **Limits:** ~40 RPM per key with no daily cap (forum reports, May 2026). Not officially documented.
- **Pilot:** under 1 day (720 calls ≈ 20 min at 40 RPM; allow a day for queueing).
- **Sign-up:** https://build.nvidia.com → log in or join the NVIDIA Developer Program (free) → "Get API Key". No card reported.
- **Caveats:**
  - The trial terms are for evaluation and testing; data-use wording is ambiguous but the data is public.
  - Free endpoints can queue, rate-limit, or get swapped or deprecated without notice.
  - Model choice:
    - **DeepSeek V4.1 Flash:** the card confirms tool calling and thinking, and DeepSeek recommends temperature=1.
    - **Mistral Large 4:** gives a Mistral family; its card confirms native function calling, `tool_choice` and strict JSON schema. Reasoning defaults to **high**, so set it low.
    - **Kimi K2.6:** also listed, but its card page didn't render.
  - Pick one after a 10-call smoke test.
- **Back-up for this slot:** `openai/gpt-oss-120b` on Groq (gpt-oss tokens get prompt caching relief) or Cloudflare. It pairs naturally with GPT-6 Luna later.

### 7.4 Arabic-centric: `Fanar-2.0-Tools` (when access arrives)

- **Endpoint:** `https://api.fanar.qa/v1`.
- **Limits:** 50 RPM. Daily cap unpublished; read the `ratelimit-policy` header on the first response.
- **Pilot:** under 1 day.
- **Sign-up:** fill in https://api.fanar.qa/request/en and **explicitly request Fanar-2.0-Tools authorization** (it is off by default). Mention a public research benchmark and the Egyptian and Arabizi focus.
- **Caveats:**
  - **8K context** (HTTP 413 above it).
  - `tool_choice` only `auto` or `none`, so it can't take part in any "forced tool" condition.
  - No `parallel_tool_calls=false`.
  - A reply starting with `{` is treated as a tool call.
  - Data-use terms are not published in the spec.
- **If access is slow:** the open `QCRI/Fanar-2-27B-Instruct` (32K context, tool calling) is too heavy to run well locally on 24 GB. Wait for the API.

### 7.5 Optional local: `gpt-oss:20b` (Ollama), or `gemma4:26b-a4b-it-qat`

- **Endpoint:** `http://localhost:11434/v1`.
- **Limits:** none.
- **Pilot:** 720 calls ≈ 1.5–3 h; 2,000 calls ≈ 4–8 h (estimate).
- **Setup:**
  1. Install Ollama (macOS app or `brew install ollama`).
  2. Run `ollama pull gpt-oss:20b`.
  3. Set the context length to ≥16K.
- **Caveats:**
  - `tool_choice` is unsupported.
  - gpt-oss emits reasoning, so set `reasoning_effort` to low.
  - Arabic quality is likely weaker than Gemma 4's. Choose `gemma4:26b-a4b-it-qat` if Arabic coverage matters more than adding the OpenAI open-weight family. Gemma 4 is also free via AI Studio (1,500 RPD), NVIDIA (`google/gemma-4-31b-it`) and OpenRouter `:free`.

### Bench alternates (all free)

- `gemma-4-31b-it` via AI Studio: 15 RPM, 1,500 RPD (3rd-party); probably native API.
- `google/gemma-4-31b-it` on NVIDIA build.
- `@cf/google/gemma-4-26b-a4b-it` on Cloudflare: ~200–520 calls/day.
- `nvidia/nemotron-3-ultra-550b-a55b:free` on OpenRouter: limited to 50/day.

---

## 8. Planned paid models: is there a genuinely free route?

| Planned model | Free route? | Details |
|---|---|---|
| Gemini 3.5 Flash-Lite | **Yes** | AI Studio free tier, ~500 RPD (prompts used for training) |
| Qwen3.8-27B | **Yes** | Groq free (`qwen/qwen3.8-27b`, 200K TPD); Cloudflare Workers AI free 10k neurons/day (`@cf/qwen/qwen3.8-27b`); Cerebras trial (`qwen-3.8-27b`, needs a payment method, $5 / 30 days); local `qwen3.8:27b` (18 GB, borderline and slow on 24 GB) |
| GPT-6 Luna | **No** | Only paid ids on OpenRouter (`openai/gpt-6-luna`, listed at $0.10 / $0.50 per M tokens) and no `:free` variant. Not hosted by Groq, Cerebras, NVIDIA or Cloudflare. The nearest free proxy is open-weight gpt-oss-120b/20b, which is a different model. OpenAI's own free offers were not checked |
| Claude Sonnet 5.5 | **No** | OpenRouter lists `anthropic/claude-sonnet-5.5` as paid only ($2 / $10 per M) and has no `:free` variant. No free host found. Anthropic's own console offers were not checked here |
| Claude Haiku 5.5 | **No** | OpenRouter lists `anthropic/claude-haiku-5.5` as paid only ($0.10 / $0.50 per M) and has no `:free` variant. No free host found |

---

## 9. Converter notes (one OpenAI-compatible adapter)

| Endpoint | `tools` | `tool_choice` | Parallel calls | Thinking control | Special handling |
|---|---|---|---|---|---|
| Gemini OpenAI-compatible endpoint | yes | auto (others not verified via the compatibility layer) | model supports | `reasoning_effort` → `thinking_level` | Echo assistant tool-call turns unchanged (thought signatures). Beta |
| Gemini native (Gemma 4) | functionDeclarations | auto / any / none / validated | – | `thinking_level` high or minimal | Separate small adapter |
| Groq qwen3.8-27b | yes | yes | yes | `reasoning_effort` none (default) / low / medium / high | 8K TPM: pace ≤1 large call per ~40 s |
| Groq gpt-oss | yes | yes | **no** | low / medium (default) / high | prompt caching helps quota |
| Cloudflare | yes (per model card) | – | – | qwen3.8 default **xhigh** | account-id in the URL |
| NVIDIA build | per model card | Mistral Large 4 card shows tool_choice | – | Mistral L4 default high; DeepSeek numeric effort | queueing |
| Fanar | yes | **auto / none only** | yes (cannot be disabled) | – | 8K context, 413 errors |
| Ollama local | yes | **unsupported** | – | `reasoning_effort` | set context ≥16K |

---

## 10. Page-load log (all 2026-11-05)

**Loaded OK**

- openrouter.ai/api/v1/models (JSON), openrouter.ai/docs/api/reference/limits, openrouter.ai/docs/guides/privacy/provider-logging
- Google, via 301 redirects to aistudio.google.com/docs/…: rate-limits, pricing, models/gemini-3.5-flash-lite, thinking, openai, function-calling, terms, available-regions
- ai.google.dev/gemma/docs/core/gemma_on_gemini_api
- Groq: console.groq.com/docs/{rate-limits, models, tool-use, model/qwen/qwen3.8-27b, prompt-caching, your-data, billing-faqs}
- Cerebras: inference-docs.cerebras.ai/{support/rate-limits, models/overview, capabilities/tool-use}
- Cloudflare: developers.cloudflare.com/workers-ai/{platform/pricing, models, models/<id>, configuration/open-ai-compatibility}
- huggingface.co/docs/inference-providers/pricing
- docs.github.com GitHub Models retirement page
- integrate.api.nvidia.com/v1/models and build.nvidia.com model cards. The kimi-k2.6 and glm-5.3-flash cards returned empty shells
- forums.developer.nvidia.com/t/is-nim-free/369368
- docs.sambanova.ai/docs/en/models/rate-limits
- support.together.ai article, deepinfra.com/pricing, chutes.ai starter guide
- Fanar: api.fanar.qa/openapi.json, fanar.qa/en
- Ollama: docs.ollama.com/api/openai-compatibility, ollama.com/pricing, ollama.com/library/*/tags
- Hugging Face model API and cards for Jais-3, Fanar-2 and ALLaM
- omlx.ai/benchmarks/bgp3x8tq

**Failed or inconclusive**

- docs.mistral.ai: connection failure, both through WebFetch and curl.
- help.mistral.ai articles 450104 and 455206: 404.
- mintlify free-llm-api-resources: 410; the cheahjs GitHub repo is 404.
- developersdigest Mistral page: 404.
- docs.sambanova.ai/cloud/docs/get-started/rate-limits: 404 (the new URL works).
- api.fanar.qa/request/en: a JS shell only.
- fireworks.ai: not opened directly (3rd-party snapshot only).
- docs-prod.sambanova.ai .md: "Disallowed origin host".

**Not verified**

- Gemini free RPM/RPD: only visible in the console.
- Mistral free limits.
- NVIDIA daily cap (forum only).
- Fanar daily cap and data terms.
- gpt-oss-20b speed on an M4 Pro.
- Whether tools pass through Cloudflare's `/ai/v1` OpenAI-compatible path.
- Ollama's default context length.
