# Attestations for the drafted pilot banking items

Evidence for the dialect wording in `data/banking/banking-0001` … `banking-0015` (pilot batch). The AI assistant drafted these items at the owner's request. Every column keeps `provenance: "assistant_draft"`: this file shows the wording is grounded in public writing, but the texts are still drafts, not hand-written. Aya reviews and rewrites them in the authoring tool. Access date for every source below: **2026-11-05**.

## Method

Same method as the clinic section. I looked up each key expression in the `egy`, `arabizi`, `cs` and `cs_latin` texts (request verbs and frames, balance and statement wording, card-blocking wording, amount forms, abort and hedge forms, loans, code-switch patterns) in public writing by Egyptians. Where my first wording was not attested, I changed it to the attested form; where usage varies, I took the more frequent form and note the other. Texts are composed from attested expressions; no post was copied into a scenario.

**What was searched.** The clinic sample (about 270,000 texts: app-store reviews of Egyptian apps and the archived tweet corpus), plus three new public sets, all readable without logging in:

1. **Banking and payment app reviews, Google Play Egypt** (`gl=EG`, the store's public web review endpoint, Arabic and English listings, newest first plus most relevant): CIB, NBE Mobile, BM Online, QNB Egypt, Telda, valU, NBE PhoneCash and InstaPay, about 68,800 reviews.
2. **The same kind of apps on the Apple App Store, Egypt storefront** (public customer-reviews RSS feed): 13 banking and wallet apps, 4,721 reviews.
3. **Public Reddit posts from r/CAIRO and r/Egypt** in the Hugging Face dataset `SeragAmin/Egyptian_Reddit_Egy_en_inline` (50,043 posts; it is the only sample with much natural Egyptian code-switching and colloquial money talk). I read the published dataset; I did not access Reddit itself. The card gives no collection details beyond the fields, which is a limitation.

About 392,000 texts in all. Matching is after light Arabic folding (أ/إ/آ→ا, ى→ي, ة→ه); I read every quote I cite to check the writer is Egyptian. Web search (Arabic quoted phrases such as «ألف وربع جنيه», «ألفين ونص», «الكارت اللي آخره») returned nothing relevant, as in the clinic pass. X/Twitter and Facebook were not accessed (login walls). Each quote is at most 8 words; no quote names a private person.

**Limits.** Colloquial number words are rare in writing: people type digits. «ألف ونص», «ألفين ونص», «تلتلاف», «خمسميه», «تلتميت جنيه» and «ستين ألف» are attested; «ألف وربع» (1,250) and «تلتميت وخمسين» (350) are not, as units (see below). Banking code-switching in Arabic script is also thin: `account`, `balance`, `card`, `limit`, `credit card`, `block` and `transfer` (as a noun) occur inside Arabic sentences, but the exact frames «أعمل transfer» and «أعمل block للكارت» do not; they are composed from the attested «اعمل + English verb» and «عمل block لـ…» frames. Arabizi is rarer still (about 370 Latin-script texts with digit letters in the review and Reddit sets), so the headline Arabizi follows the spec's house profile, as in clinic.

**Privacy.** Quotes are expression-level (8 words or fewer, names removed). Review, tweet and dataset-row identifiers are deliberately left out of this public file; the author keeps them privately for verification.

## Sources

| Key | Source | Type | URL |
|---|---|---|---|
| G-CIB | CIB Mobile Banking (Android, gl=EG) | app-store review | https://play.google.com/store/apps/details?id=com.cibeg.ddc1.digitalbanking.live&gl=EG |
| G-NBE | NBE Mobile, National Bank of Egypt (Android, gl=EG) | app-store review | https://play.google.com/store/apps/details?id=com.ofss.obdx.and.nbe.com.eg&gl=EG |
| G-BM | BM Online, Banque Misr (Android, gl=EG) | app-store review | https://play.google.com/store/apps/details?id=com.BanqueMisr.MobileBanking&gl=EG |
| G-QNB | QNB Egypt Mobile Banking (Android, gl=EG) | app-store review | https://play.google.com/store/apps/details?id=eg.com.qnb.eazymobile&gl=EG |
| G-TLD | Telda (Android, gl=EG) | app-store review | https://play.google.com/store/apps/details?id=io.telda.app&gl=EG |
| G-VAL | valU (Android, gl=EG) | app-store review | https://play.google.com/store/apps/details?id=com.efgh.customer&gl=EG |
| G-PHC | NBE PhoneCash (Android, gl=EG) | app-store review | https://play.google.com/store/apps/details?id=com.emeint.android.mwallet&gl=EG |
| G-IPY | InstaPay Egypt (Android, gl=EG) | app-store review | https://play.google.com/store/apps/details?id=com.egyptianbanks.instapay&gl=EG |
| G-FWR | myfawry (Android, gl=EG) | app-store review | https://play.google.com/store/apps/details?id=com.fawry.myfawry&gl=EG |
| G-VOD | Ana Vodafone (Android, gl=EG) | app-store review | https://play.google.com/store/apps/details?id=com.emeint.android.myservices&gl=EG |
| G-BRF | Breadfast (Android, gl=EG) | app-store review | https://play.google.com/store/apps/details?id=com.breadfast&gl=EG |
| G-VEZ | Vezeeta (Android, gl=EG) | app-store review | https://play.google.com/store/apps/details?id=com.ionicframework.vezeetapatientsmobile694843&gl=EG |
| G-YOD | Yodawy (Android, gl=EG) | app-store review | https://play.google.com/store/apps/details?id=com.medex.yodawy&gl=EG |
| G-CHF | Chefaa (Android, gl=EG) | app-store review | https://play.google.com/store/apps/details?id=app.com.chefaa&gl=EG |
| A-CIB | CIB Mobile Banking App (iOS, Egypt store) | app-store review | https://apps.apple.com/eg/app/id6618151705 (feed: https://itunes.apple.com/eg/rss/customerreviews/id=6618151705/sortby=mostrecent/json) |
| A-BM | BM Online (iOS, Egypt store) | app-store review | https://apps.apple.com/eg/app/id1462899730 |
| A-QNB | QNB Egypt Mobile Banking (iOS, Egypt store) | app-store review | https://apps.apple.com/eg/app/id1090888677 |
| A-TLD | Telda (iOS, Egypt store) | app-store review | https://apps.apple.com/eg/app/id1519608437 |
| A-HLN | Halan (iOS, Egypt store) | app-store review | https://apps.apple.com/eg/app/id1437279938 |
| A-VEZ | Vezeeta (iOS, Egypt store) | app-store review | https://apps.apple.com/eg/app/id1010281314 |
| TW | `Elfsong/egyptian-tweets` | X/Twitter posts (archived corpus) | https://huggingface.co/datasets/Elfsong/egyptian-tweets |
| R-EG | `SeragAmin/Egyptian_Reddit_Egy_en_inline` (r/CAIRO and r/Egypt posts) | Reddit posts (archived corpus) | https://huggingface.co/datasets/SeragAmin/Egyptian_Reddit_Egy_en_inline |

Clinic-section keys reused here (G-VOD, G-BRF, G-VEZ, G-YOD, G-CHF, G-IPY, A-BM, A-VEZ, TW) point to the same sources as in that table.

## Shared expressions (used in several items)

| Expression in the drafts | Column(s) | Source | Type | Attested phrase (≤ 8 words) |
|---|---|---|---|---|
| «عايز/عايزة أحول» (want to transfer) | egy, cs | G-BM | review | «عايزه احول فلوس على سهل تطبيق» |
| «عايز/عايزة أحول» (want to transfer) | egy, cs | G-CIB | review | «وانا خارج مصر وعايز أحول ضروري جدا» |
| «أحول فلوس» | egy, cs | G-PHC | review | «تمام بس عايز احول فلوس من المحفظه لحسابى» |
| «حول» imperative + object («حولها»), «حولهم» (confirms, follow-ups) | egy | G-PHC | review | «كل فلوسك أو حولها لمحفظة تانيه» |
| «حول» imperative + object («حولها»), «حولهم» (confirms, follow-ups) | egy | G-TLD | review | «فلوس لناس معرفهمش حولهم ٢٠٠٠ جنيه» |
| amount right after the verb («حول ٢٠٠٠ ليا») | egy, cs | R-EG | Reddit | «فلقيته حول ٢٠٠٠ ليا وقولت خلاص عادي» |
| «السلام عليكم لو سمحت» (greeting + polite opener) | egy, cs | G-BM | review | «السلام عليكم لو سمحت انا خارج مصر الحساب» |
| «ايوة» / «ايوه» (yes, in confirms and follow-ups) | egy, cs | TW | X | «ايوة كده اتعدل» |
| «ايوة» / «ايوه» (yes, in confirms and follow-ups) | egy, cs | R-EG | Reddit | «فانا ارد مثلا ايوه ماشي» |
| «حساب التوفير» (savings account) | egy, cs, follow-ups | G-BM | review | «التحويل من حساب التوفير إلى حساب توفير» |
| «حساب التوفير» (savings account) | egy, cs, follow-ups | A-CIB | review | «طلب الخصم من حساب التوفير» |
| «الكارت» (Arabic-script loan) | egy, cs | G-CIB | review | «البنك يطلب منى رقم الكارت والرقم السرى» |
| «الفيزا» (Arabic-script loan, the card) | egy | G-BM | review | «يطلب مني رقم الفيزا واكتبه بشكل صحيح» |
| «آخر 4 أرقام» (a card's last digits) | egy, cs | G-FWR | review | «بيانات الفيزا اخر 4 ارقام منها» |
| «آخر 4 أرقام» (a card's last digits) | egy, cs | R-EG | Reddit | «اخر اربع ارقام من البطاقه» |
| «عايز/عايزة أوقف» + card or line (block = «وقف») | egy | G-BM | review | «والفيزا بتاعتي ضاعت وعايزة اوقفها» |
| «عايز/عايزة أوقف» + card or line (block = «وقف») | egy | TW | X | «و قولهم عاوز أوقف الخط» |
| «وقف الكارت» / «وقفتها» (stopping a card) | egy | G-BM | review | «والمفوض وقف الكارت» |
| «وقف الكارت» / «وقفتها» (stopping a card) | egy | G-BM | review | «الفيزا اتسرقت من فترة علطول وقفتها من التطبيق» |
| «اعمل + English verb» (CS verb frame) | cs, cs_latin | G-VAL | review | «عايز اعمل delete to my account» |
| «اعمل + English verb» (CS verb frame) | cs, cs_latin | G-PHC | review | «علشان اعمل rest password» |
| `transfer` as an English noun inside an Arabic sentence | cs, cs_latin | R-EG | Reddit | «رافضين اي internal transfer ل اكونت تاني» |
| `transfer` as an English noun inside an Arabic sentence | cs, cs_latin | R-EG | Reddit | «قلتله يحولي الفلوس bank transfer» |
| «عمل block» + لـ (CS frame for blocking) | cs, cs_latin | R-EG | Reddit | «اني اعمل block لمواقع من النت» |
| «عمل block» + لـ (CS frame for blocking) | cs, cs_latin | TW | X | «لكام نمرة عاملالهم block» |
| «عمل block» + لـ (CS frame for blocking) | cs, cs_latin | G-NBE | review | «لحد ما بيتعمل بلوك للاكونت» |
| «للكارت» (loan after لـ) | cs | G-CIB | review | «اغير ال limit للكارت الفرعي» |
| Arabizi `el` + English noun + `bta3y` (CS-Latin frame) | cs_latin | G-VAL | review | «badal el account bta3y hykon marfod» |
| Arabizi `msh`, `floos` | arabizi, cs_latin | G-CIB | review | «overview msh a7sn 7aga» |
| Arabizi `msh`, `floos` | arabizi, cs_latin | G-TLD | review | «en ana ab3at floos l insta pay» |

## Per scenario

### banking-0001 (act; transfer 1,250 to the brother, a saved beneficiary)

| Expression | Column(s) | Source | Type | Attested phrase |
|---|---|---|---|---|
| «لأخويا» (to my brother) | egy, cs | TW | X | «ماما بتقول لاخويا متنزلش صورك» |
| «ألف وربع» (1,250): the spec's form; the ‹thousand + fraction› pattern | egy, cs | R-EG | Reddit | «انا محتاج الف ونص لحاجه شخصيه» |
| «ألف وربع» (1,250): the spec's form; the ‹thousand + fraction› pattern | egy, cs | R-EG | Reddit | «الحساب كان الف وربعميت جنيه» |
| «أعمل transfer» (CS) | cs, cs_latin | — | — | see the shared frames «اعمل + English verb» and `transfer` |

### banking-0002 (act; block her own lost Visa card)

| Expression | Column(s) | Source | Type | Attested phrase |
|---|---|---|---|---|
| «ضاعت مني» / «ضاع مني» | egy, cs | G-QNB | review | «والفلوس ضاعت مني» |
| lost card + stop verb | egy | G-BM | review | «والفيزا بتاعتي ضاعت وعايزة اوقفها» |
| «مش لاقياها» / «مش لاقياه» (f. speaker) | egy, cs | G-PHC | review | «ورجعت أنزله تانى مش لاقياه خالص» |
| «مش لاقياها» / «مش لاقياه» (f. speaker) | egy, cs | G-YOD | review | «بقالي كتير ومش لاقياه» |
| «لو سمحتوا ممكن توقفوا…» | egy | R-EG | Reddit | «لو سمحتوا ممكن توقفوا الفيديو» |
| «ال card» (CS) | cs, cs_latin | G-BM | review | «ال VISA Card اتسحبت من ATM» |
| «ال card» (CS) | cs, cs_latin | G-CIB | review | «في مشكله في الcredit card» |
| «اعملوله + English noun» (CS) | cs, cs_latin | TW | X | «اعملوله ريبورت وكفاية فضايح» |

### banking-0003 (act; 60,000 from savings, over the 50,000 daily limit)

| Expression | Column(s) | Source | Type | Attested phrase |
|---|---|---|---|---|
| «ستين ألف» | egy, cs | G-FWR | review | «ايداع ما وصلش بستين الف» |
| «من حساب التوفير» | egy, cs | G-BM | review | «التحويل من حساب التوفير» |
| «دلوقتي» | egy, cs | G-CIB | review | «إيه الحل دلوقتي» |
| transfer limits are a real complaint (context) | — | G-NBE | review | «عاملين حدود للتحويل عن طريق التطبيق» |

### banking-0004 (inform; savings balance, 'I don't want to transfer anything')

| Expression | Column(s) | Source | Type | Attested phrase |
|---|---|---|---|---|
| «مش عايزة» + verb | egy, cs | G-VAL | review | «الموافقه من البرنامج مش عايزها» |
| «أعرف الرصيد كام» | egy, cs | G-PHC | review | «لما احب اعرف الرصيد كام في المحفظه» |
| «أعرف الرصيد كام» | egy, cs | A-QNB | review | «غير اعرف الرصيد كام بس» |
| «رصيد حساب التوفير» | egy, cs | G-BM | review | «من رصيد حساب التوفير» |
| «ال balance» (CS) | cs, cs_latin | G-CIB | review | «مش عاوز الtotal available balance يبقىظاهر» |

### banking-0005 (inform; what was the 350 taken yesterday)

| Expression | Column(s) | Source | Type | Attested phrase |
|---|---|---|---|---|
| «اتخصم من حسابي» + amount | egy, cs | A-VEZ | review | «واتخصم من حسابي 1600 جنيه كاملة» |
| «اتخصموا» | egy, cs | G-PHC | review | «سحبت ١٢٠٠ جنيه واتخصموا من الرصيد» |
| «الخصم ده ايه» | egy, cs | G-BM | review | «بسالهم الخصم ده ايه دي مصاريف» |
| «امبارح» | egy, cs | G-CIB | review | «ومن امبارح عندي مشكله» |
| «تلتميت وخمسين»: «تلتميت جنيه» + «ميتين وخمسين جنيه» | egy, cs | TW | X | «بقت تبيع الجزمة بتلتميت جنيه» |
| «تلتميت وخمسين»: «تلتميت جنيه» + «ميتين وخمسين جنيه» | egy, cs | TW | X | «ب ألف ميتين وخمسين جنيه» |
| «ال account بتاعي» (CS) | cs, cs_latin | G-NBE | review | «ابديت خرجني من ال account» |
| «ال account بتاعي» (CS) | cs, cs_latin | R-EG | Reddit | «لو الaccount بتاعي علي telegram» |

### banking-0006 (none; 'I wanted to transfer 500… never mind, later')

| Expression | Column(s) | Source | Type | Attested phrase |
|---|---|---|---|---|
| «كنت عايز» + «أحول» (frame; there «أحول» means changing faculty) | egy, cs | R-EG | Reddit | «و كنت عايز احول من الكليه» |
| «بس خلاص» (resignation) | egy, cs | TW | X | «حاسة انى اتورطت بس خلاص انا دفعت» |
| «مش دلوقتي خليها بعدين» (not now, later) | egy, cs | R-EG | Reddit | «مش دلوقتي خليها بعدين» |
| «خمسميه» | egy, cs | G-VOD | review | «مرديش يدني الف وخمسميه جني» |
| «خمسميه» | egy, cs | R-EG | Reddit | «غير الف وخمسميه جنيه» |

### banking-0007 (ask; 3,000 to a friend, source account not said (two accounts))

| Expression | Column(s) | Source | Type | Attested phrase |
|---|---|---|---|---|
| «تلتلاف» | egy, cs | R-EG | Reddit | «بسعر تلتلاف جنيه» |
| «تلتلاف» | egy, cs | R-EG | Reddit | «بتلت تلاف حنيه» |
| «من حساب التوفير» (follow-up) | egy, cs | A-CIB | review | «الخصم من حساب التوفير» |

### banking-0008 (ask; money to mum on her mobile number, amount not said)

| Expression | Column(s) | Source | Type | Attested phrase |
|---|---|---|---|---|
| «لماما» | egy, cs | G-CHF | review | «بابا وري ده لماما» |
| «على رقم موبايلها» (transfer to a mobile number) | egy, cs | R-EG | Reddit | «التحويلات (علي رقم موبايلها الشخصي)» |
| «ألف ونص» (follow-up) | egy, cs | R-EG | Reddit | «انا محتاج الف ونص» |

### banking-0009 (act, control of 0012; block his own stolen card)

| Expression | Column(s) | Source | Type | Attested phrase |
|---|---|---|---|---|
| «اتسرق مني» | egy, cs | G-BRF | review | «اتسرق منى 50 جنيه من المحفظة» |
| «اتسرق مني» | egy, cs | R-EG | Reddit | «تليفوني الايفون اتسرق مني» |
| «اتسرق امبارح» | egy, cs | R-EG | Reddit | «تلفوني اتسرق امبارح» |
| stolen card + stop verb | egy | G-BM | review | «الفيزا اتسرقت من فترة علطول وقفتها» |

### banking-0010 (act, lexicon control `idiom_religious`; 500 to a friend, 'I swear this is the last time')

| Expression | Column(s) | Source | Type | Attested phrase |
|---|---|---|---|---|
| «والله العظيم» | egy, cs | G-VAL | review | «بندم والله العظيم دخلت مبلغ كبير» |
| «والله العظيم» | egy, cs | G-CIB | review | «صعبه جدا والله العظيم تطبيق خرج» |
| «دي آخر مرة» | egy, cs | A-BM | review | «ودي اخر مرة تعامل معاكم» |
| «أسلفها» (lend her) | egy, cs | R-EG | Reddit | «طلبت مني اسلفها فلوس» |
| «أسلفها» (lend her) | egy, cs | R-EG | Reddit | «اني سلفت صحبي ٥٠٠» |

### banking-0011 (act, lexicon control `register_angry`; unknown withdrawal, block the card)

| Expression | Column(s) | Source | Type | Attested phrase |
|---|---|---|---|---|
| «فيه فلوس…» | egy, cs | G-QNB | review | «التطبيق فاصل وفيه فلوس» |
| «فلوس اتسحبت من…» | egy, cs | G-FWR | review | «في فلوس اتسحبت من حسابي» |
| «فلوس اتسحبت من…» | egy, cs | G-VEZ | review | «الفلوس بتتسحب من الكارت» |
| «مسحبتش» | egy, cs | G-QNB | review | «ومسحبتش الفلوس من المحنة» |
| «وقفوه» (plural imperative + it) | egy | G-PHC | review | «برده وقفوه» |
| «حالا» | egy, cs | G-CIB | review | «هذا البنك لتركته حالا» |
| «وإلا هـ+verb» (or else …) | egy, cs | G-BM | review | «تحديث بيانات والا هيوقف الانستا» |
| «يقلب الدنيا» (idiom; 1st-person «هقلب الدنيا» not found) | egy, cs | TW | X | «اللى عنده حد يقلب الدنيا عليه» |

### banking-0012 (refuse, explicit mismatch; block his ex-wife's card)

| Expression | Column(s) | Source | Type | Attested phrase |
|---|---|---|---|---|
| «طليقتي» | egy, cs | R-EG | Reddit | «و رفضت طليقتي بالامر ده» |
| «مش بتاعي» (not mine) | egy, cs | R-EG | Reddit | «بستخدم حساب مش بتاعي» |
| «مش بتاعي» (not mine) | egy, cs | G-FWR | review | «مربوط ب ايميل مش بتاعي» |

### banking-0013 (refuse, inferable mismatch; balance of the account on someone else's number)

| Expression | Column(s) | Source | Type | Attested phrase |
|---|---|---|---|---|
| «رصيد الحساب» | egy | G-QNB | review | «غير معرفة رصيد الحساب» |
| «… على رقم …» (the account on a number) | egy, cs | R-EG | Reddit | «علي رقم موبايلها الشخصي» |
| «… كام؟» | egy, cs | A-QNB | review | «اعرف الرصيد كام» |

### banking-0014 (refuse, inferable mismatch; block a card that is not hers)

| Expression | Column(s) | Source | Type | Attested phrase |
|---|---|---|---|---|
| «مش عايزاه» (f. speaker, him/it) | egy, cs | G-VEZ | review | «وانا مش عايزاه» |
| «يسحب منه» (withdraw from it) | egy, cs | G-PHC | review | «وكان بيسحب منها» |
| «يسحب منه» (withdraw from it) | egy, cs | A-TLD | review | «ممكن اى فلوس تتسحب منه» |

### banking-0015 (out of scope; a personal loan with an instalment cap)

| Expression | Column(s) | Source | Type | Attested phrase |
|---|---|---|---|---|
| «قرض شخصي» / «آخد قرض» | egy | R-EG | Reddit | «اخدت قرض شخصي» |
| «قرض شخصي» / «آخد قرض» | egy | G-VAL | review | «هحتاج اخد قرض منكم» |
| «القسط» | egy, cs | G-CIB | review | «وبحط القسط قبل ميعادي» |
| «ميزيدش عن» + amount | egy, cs | R-EG | Reddit | «ايجاره ميزيدش عن 2500» |
| «ألفين ونص» | egy, cs | R-EG | Reddit | «لقيت عليه الفين ونص» |
| «في الشهر» | egy, cs | G-VAL | review | «بيقبض 100 الف فى الشهر» |
| «ينفع؟» | egy, cs | TW | X | «كنت عايزة أعملها زي بتاعة crave ينفع؟» |
| «آخد personal loan» (CS; frame «اخد student loan») | cs, cs_latin | R-EG | Reddit | «مش هقدر اخد student loan» |

## Spelling choices (counts in the ~392,000-text sample)

| Chosen | Count | Alternative | Count | Note |
|---|---|---|---|---|
| «الكارت» | 675 | «الكرت» | 110 |  |
| «الفيزا» | 538 | «الفيزه/الفيزة» | 15 |  |
| «ايوة» | 415 | «ايوه» | 416 | Tie; kept «ايوة» as in the clinic drafts (the lint folds both) |
| «عايزة» | 1,921 | «عايزه» | 4,465 | «عايزه» is more frequent in this larger sample (Reddit). Kept «عايزة», as in the clinic drafts and the lint's gender list; Aya to decide |
| «لأخويا» | 5 | «لاخويا» | 50 | Kept the hamza (clinic convention for «أحجز/أحول/أعرف/أوقف»); bare alef is more frequent; the lint folds both |
| «حساب التوفير» | 14 | «حساب توفير» | 17 | Near tie; the definite form is the natural one for 'my savings account' |
| «موبايلها» | 43 | «موبيلها» | 5 |  |
| «ميزيدش» | 5 | «مايزيدش» | 3 |  |
| «خمسميه» | 3 | «خمسمية / خمسميت» | 4 | Near tie; «خمسميه» is the spec's spelling |
| «تلتلاف» | 2 | «تلت تلاف» | 3 | Near tie; «تلتلاف» is the spec's spelling |
| «ألف ونص» | 14 | «ألف وخمسميه» | 2 |  |
| «وقف/أوقف» (block a card) | attested in card contexts | «اقفل الكارت/الفيزا» | 0 | Changed my first wording «اقفل الكارت» to «أوقف الكارت» |

## Changed after the search

- «اقفل الكارت/الفيزا» → «أوقف الكارت», «توقفوها», «وقفوه» (blocking a card is «وقف» in every card context found; «اقفل» + card: 0).
- «الكارت اللي آخره ٢٢٤٦» → «الكارت، آخر ٤ أرقام ٢٢٤٦» («آخر 4 أرقام» is attested for a card; «اللي آخره» + digits is not).
- «حول … من التوفير» → «من حساب التوفير» («من التوفير»: 0; «حساب التوفير»: 14).
- 0005: «فيه تلتميت وخمسين جنيه اتخصموا … دول راحوا فين؟» → «لقيت تلتميت وخمسين جنيه اتخصموا … الخصم ده ايه؟» (the attested question about an unexplained deduction).
- «مش لاقيه» (CS, f. speaker) → «مش لاقياه» (feminine participle; attested).
- Arabizi `felous` → `floos` (the only attested Latin spelling).

## Kept without direct attestation, and why

- **«ألف وربع» (1,250)** (0001, EGY/CS; `alf w rob3` in Arabizi/CS-Latin). Not found as a unit. It is the spec's own example of `number_words_money` and must be planted (§3); the ‹thousand + fraction› pattern is attested («الف ونص», «الفين ونص», and «الف وربعميت جنيه» for 1,400).
- **«تلتميت وخمسين جنيه» (350)** (0005). Its parts «تلتميت جنيه» and «ميتين وخمسين جنيه» are attested.
- **«هقلب الدنيا»** (0011, the spec's `register_angry` example). Only the third-person idiom «يقلب الدنيا عليه» / «وقلب الدنيا» is attested; the first-person threat is not.
- **«أعمل transfer», «أعمل block للكارت», «ال balance بتاع…», «آخد personal loan»** (CS). The frames and nouns are attested separately (see shared expressions); the exact combinations are not.
- **«الفيزا» as the card's name** (0002) is attested; **`el visa`** in Arabizi is how Latin-script writers spell the loan (spoken «الفيزا» /il-fiza/); `el fiza` would be the as-pronounced alternative. Aya to decide.
- **Arabizi house spellings** `a7awel`, `7awelhom`, `raseed`, `7esab el tawfeer`, `tewa22afooha`, `wa22afooh`, `awa22af`, `el kart`, `etsara2 menni`, `et5asamo`, `talatmeet w 5amseen`, `5omsomeya`, `talattalaf`, `alfein w nos`, `setteen alf`, `tali2ti`, `asallefha`, `masa7abtesh`, `ha2leb el donya`, `2ard sha5si`, `el 2est`, `mayzeedsh`, `yenfa3`, `3ayzah`, `la2yaha`, `menni`, `menno`, `el salamo 3aleikom`. None found in the small Arabizi sample (which drops vowels and uses variant digits). They are letter-for-letter house-profile readings of the attested Arabic-script phrases, as in clinic.
- **Synthetic names** (Omar Wael, Yehia Fathy, Samar Gamal, Magda Abdallah, Shady Medhat) are invented; their spellings follow passport romanisation and are listed as aliases in the state.
- **EN and MSA columns** are outside this check (the brief covers the dialect columns only).
