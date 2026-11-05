# Attestations for the drafted pilot clinic items

Evidence for the dialect wording in `data/clinic/clinic-0001` … `clinic-0010` (pilot batch). The AI assistant drafted these items at the owner's request. Every column keeps `provenance: "assistant_draft"`: this file shows the wording is grounded in public writing, but the texts are still drafts, not hand-written. Aya reviews and rewrites them in the authoring tool. Access date for every source below: **2026-11-05**.

## Method

I looked up each key expression in the `egy`, `arabizi`, `cs` and `cs_latin` texts (request verb and frame, spellings, specialty names, time and date forms, abort, hedge and uncertainty forms, third-party frames, code-switch patterns) in public writing by Egyptians. Where my first wording was not attested, I changed it to the attested form. Where usage varies, I took the more frequent form and note the other one.

**What could be searched.** X/Twitter and Facebook are largely login-walled to automated access, and Reddit blocks it (I did not try to get around that). General web search barely indexes exact Egyptian or Arabizi phrases: most quoted-phrase searches returned nothing relevant. So almost all the evidence comes from three public sources that can be read without logging in:

1. **App-store reviews** written by Egyptian users of Egyptian apps. These come from the Apple App Store Egypt storefront, through its public customer-reviews RSS feed (6,874 reviews of 19 apps), and from Google Play Egypt, through the store's public web review endpoint (about 59,900 reviews of 10 Egyptian apps in the Arabic and English listings, newest first plus most relevant). Vezeeta, Yodawy, Chefaa and CliniDo are health apps, so their reviews use clinic language («حجزت كشف», «معاد», «الغي الحجز»).
2. **Public tweets from 2013–2014** in the Hugging Face dataset `Elfsong/egyptian-tweets` (203,053 tweets from 96 accounts, all labelled Arabic). The dataset card gives no collection details, which is a limitation.
3. **Pages found by web search**: two public medical Q&A titles on altibbi.com, and one Egyptian doctor-directory listing.

That is about 270,000 texts in all. I matched each expression after light Arabic folding (أ/إ/آ→ا, ى→ي, ة→ه), then read every quote I cite to check that the writer is Egyptian. Vezeeta's Play listing also has Saudi reviewers, so I used only reviews with clear Egyptian markers. Each quote below is at most 8 words, with names left out. No post was copied into a scenario: the scenario texts are composed from attested expressions.

**Limits.** Arabizi is now rare in public Egyptian writing I could reach. Only 61 reviews in the whole sample are Arabizi, and they mostly drop vowels («3nd», «mn», «bgd») and use variant digits («m4», «sh8»). The headline Arabizi columns therefore follow the spec's **house profile** (§2, "cleaned Arabizi"). The sample attests the digit letters (2, 3, 5, 7), `g` for ج, the article `el`, and several words. It does not attest the full house spellings, which are listed below as kept without attestation. Code-switch evidence is mostly *pattern-level*: «عمل + English verb + لـ», «ال + English noun», «دكتورة + English specialty». Most clinic English nouns were not attested inside an Arabic-script sentence in this sample.

**Privacy.** Quotes are expression-level (8 words or fewer, names removed). Individual review and tweet identifiers are deliberately left out of this public file, so no quote links to a person's account; the author keeps the identifiers privately for verification.

## Sources

| Key | Source | Type | URL |
|---|---|---|---|
| A-VEZ | Vezeeta (iOS, Egypt store) | app-store review | https://apps.apple.com/eg/app/id1010281314 (feed: https://itunes.apple.com/eg/rss/customerreviews/id=1010281314/sortby=mostrecent/json) |
| A-SWVL | Swvl (iOS, Egypt store) | app-store review | https://apps.apple.com/eg/app/id1214486024 |
| A-TLB | talabat (iOS, Egypt store) | app-store review | https://apps.apple.com/eg/app/id451001072 |
| A-CRM | Careem (iOS, Egypt store) | app-store review | https://apps.apple.com/eg/app/id592978487 |
| A-SHZ | Shezlong (iOS, Egypt store) | app-store review | https://apps.apple.com/eg/app/id1530680411 |
| A-BM | BM Online (iOS, Egypt store) | app-store review | https://apps.apple.com/eg/app/id1462899730 |
| A-WE | My WE (iOS, Egypt store) | app-store review | https://apps.apple.com/eg/app/id1413151505 |
| A-ETS | My etisalat (iOS, Egypt store) | app-store review | https://apps.apple.com/eg/app/id558287646 |
| G-VEZ | Vezeeta (Android, gl=EG) | app-store review | https://play.google.com/store/apps/details?id=com.ionicframework.vezeetapatientsmobile694843&gl=EG |
| G-YOD | Yodawy (Android, gl=EG) | app-store review | https://play.google.com/store/apps/details?id=com.medex.yodawy&gl=EG |
| G-CHF | Chefaa (Android, gl=EG) | app-store review | https://play.google.com/store/apps/details?id=app.com.chefaa&gl=EG |
| G-BRF | Breadfast (Android, gl=EG) | app-store review | https://play.google.com/store/apps/details?id=com.breadfast&gl=EG |
| G-VOD | Ana Vodafone (Android, gl=EG) | app-store review | https://play.google.com/store/apps/details?id=com.emeint.android.myservices&gl=EG |
| G-IPY | InstaPay Egypt (Android, gl=EG) | app-store review | https://play.google.com/store/apps/details?id=com.egyptianbanks.instapay&gl=EG |
| G-ELM | elmenus (Android, gl=EG) | app-store review | https://play.google.com/store/apps/details?id=com.elmenus.app&gl=EG |
| TW | `Elfsong/egyptian-tweets` | X/Twitter posts (archived corpus) | https://huggingface.co/datasets/Elfsong/egyptian-tweets |
| Q-1 | altibbi.com question title | medical Q&A site | https://altibbi.com/%D8%A7%D8%B3%D8%A6%D9%84%D8%A9-%D8%B7%D8%A8%D9%8A%D8%A9/%D8%A7%D9%85%D8%B1%D8%A7%D8%B6-%D8%A7%D9%84%D8%A7%D8%B3%D9%86%D8%A7%D9%86/%D8%B6%D8%B1%D8%B3%D9%8A-%D8%A8%D9%8A%D9%88%D8%AC%D8%B9%D9%86%D9%8A-%D8%AC%D8%AF%D8%A7-%D9%88-%D9%84%D9%85%D8%A7-%D8%A8%D8%B5%D9%8A%D8%AA-%D8%B9%D9%84%D9%8A%D9%87-%D9%84%D9%82%D9%8A%D8%AA-%D9%84%D9%88%D9%86%D9%87-%D8%A7%D8%AA%D8%BA%D9%8A%D8%B1-%D8%A7%D8%B2%D8%B1%D9%82-%D8%B4%D9%88%D9%8A%D8%A9-1407333 |
| Q-2 | altibbi.com question title | medical Q&A site | https://altibbi.com/%D8%A7%D8%B3%D8%A6%D9%84%D8%A9-%D8%B7%D8%A8%D9%8A%D8%A9/%D8%A7%D9%85%D8%B1%D8%A7%D8%B6-%D8%A7%D9%84%D8%A7%D8%B3%D9%86%D8%A7%D9%86/%D8%B6%D8%B1%D8%B3%D9%8A-%D9%85%D9%83%D8%B3%D9%88%D8%B1-%D9%88%D8%A8%D9%82%D9%8A-%D9%8A%D9%88%D8%AC%D8%B9%D9%86%D9%8A-%D9%83%D8%AF%D8%A7%D8%A7-%D9%88%D9%85%D8%B4-%D8%B9%D8%A7%D8%B1%D9%81-%D8%A8%D9%82%D9%8A-%D8%A7%D8%AE%D8%AF-%D8%A7%D9%8A-%D9%88%D8%B4%D9%83%D9%84%D9%87-1563162 |
| W-MED | Medoc doctor directory, Egypt listing | doctor directory | https://medoc.care/en/doctors/dermatology/el-shorouk |

## Shared expressions (used in several items)

| Expression in the drafts | Column(s) | Source (id) | Type | Attested phrase (≤ 8 words) |
|---|---|---|---|---|
| «لو سمحت كنت عايز/ة أعرف» (polite opener) | egy, cs | TW | X | «مساء الخير.. لو سمحت كنت عايز أعرف» |
| «كنت عايزة + verb» | egy, cs | G-VEZ | review | «لوسمحت كنت عايزه اعرف التوصيل بكام» |
| «معاد» (appointment) | egy, cs | TW | X | «عندى معاد دكتور» |
| «معاد» alternative «ميعاد» | egy, cs | A-SHZ | review | «رحت حاجز ميعاد تاني» |
| «عند دكتور + specialty» | egy, cs | G-VEZ | review | «اني احجز عند دكتور عظام بسهوله» |
| «عايز/عايزة» (want) | egy, cs | G-VOD | review | «وعايز الغي الفاتوره مش عايز» |
| «بكرة» | egy, cs | TW | X | «رايحة لدكتور الأسنان بكرة» |
| «ايوة» (yes, in confirms and follow-ups) | egy, cs | TW | X | «ايوة كده اتعدل» |
| «اه تمام» / «تمام» (yes) | egy, cs | A-SWVL | review | «رد اه تمام» |
| «اعمل confirm» (CS confirm) | cs | G-VEZ | review | «معاد للطبيب و عملت confirm» |
| «عمل cancel لـ…» (CS verb frame) | cs | A-SWVL | review | «وعملوا cancel للرحلة بعد ميعادها» |
| same frame | cs | A-TLB | review | «بيعملوا cancel للاوردر وتدوخ» |
| «اعمل + English» frame | cs | G-BRF | review | «يخليني اعمل check out» |
| «ال + English noun» (article frame) | cs | A-WE | review | «و كمان ال session مدتها صغيره» |
| Arabizi `el` article, `w` (and) | arabizi, cs_latin | G-YOD | review | "Application tohfaa w el adwya" |
| Arabizi `el` + English noun (CS-Latin) | cs_latin | A-TLB | review | "gheir en el customer service" |
| Arabizi `3and`, `sa3a`, `2` for ق | arabizi, cs_latin | G-YOD; G-ELM | review | "Gabt mn 3andhom perfume"; "el order ba2alo aktar mn sa3tein" |
| Arabizi `doctor` (spelling of دكتور) and `7`/`3` | arabizi, cs_latin | G-VEZ | review | "7agzt 3nd doctor w b3toli resala" |
| Arabizi `msh` | arabizi, cs_latin | G-VOD | review | "el barnameg msh sh8 5als" |
| Arabizi `momken` | arabizi, cs_latin | G-YOD | review | "momken takshf mn 3ndhim" |
| Arabizi `lessa` | arabizi, cs_latin | G-ELM | review | "alooly eno lessa mat2abalsh" |

## Per scenario

### clinic-0001 (act; book a consultation with the dermatologist, Sunday 17:00)

| Expression | Column(s) | Source (id) | Type | Attested phrase |
|---|---|---|---|---|
| «أحجز كشف عند دكتور…» | egy, cs | G-VEZ | review | «او احجز كشف عند دكتور» |
| «دكتورة جلدية» (specialty, no article) | egy | TW | X | «جماعة عايزة دكتور جلدية يفيدني» |
| «الحد الجاي» | egy, cs | TW | X | «الحد الجاي وورك فروم هوم» |
| «الساعة ٥ العصر» (hour + period word) | egy, cs | G-VEZ | review | «من الصيدلية الساعة ٣ العصر» |
| «دكتورة derma» (CS specialty) | cs, cs_latin | TW (frame); W-MED (clipping) | X; directory | «فيه دكتورة chest»; "Specialist In Derma" |

### clinic-0002 (act; cancel tomorrow's eye-doctor appointment, "don't postpone")

| Expression | Column(s) | Source (id) | Type | Attested phrase |
|---|---|---|---|---|
| «الغي + appointment» | egy | A-SHZ | review | «لخدمة العملا الغي ميعاد» |
| «الغيه» (cancel it) | egy, cs | G-CHF | review | «وازاي الغيه» |
| «دكتور عيون» | egy, cs | G-VEZ | review | «حجزت مع دكتور عيون» |
| «بتاع بكرة» | egy, cs | TW | X | «الامتحان العملي بتاع بكرة» |
| «أجله» (postpone it, first person) | egy, cs | TW | X | «عمالة أأجل كل حاجة» (see conflicts) |
| «خالص» (altogether) | egy, cs | G-VOD | review | «ما ينفعش كده خالص» |
| «اعمل cancel لمعاد» | cs, cs_latin | A-SWVL | review | «وعملوا cancel للرحلة» |

### clinic-0003 (act; toothache, earliest dentist slot, consultation)

| Expression | Column(s) | Source (id) | Type | Attested phrase |
|---|---|---|---|---|
| «ضرسي …» + pain | egy, cs | Q-1; Q-2 | Q&A | «ضرسي بيوجعني جدا و لما بصيت عليه»; «ضرسي مكسور وبقي يوجعني» |
| «هيموتني» (hyperbole) | egy, cs | TW | X | «هيموتني تقريبا» |
| same idiom, pain | egy, cs | TW | X | «هموت من الوجع» |
| «من امبارح» | egy, cs | G-IPY | review | «لا يعمل من امبارح» |
| «أقرب معاد» | egy, cs | G-YOD | review | «بلغوني ان أقرب معاد تسليم» |
| alternative «أقرب ميعاد» | egy | G-YOD | review | «الرد اقرب ميعاد للتوصيل» |
| «دكتور أسنان» | egy | G-VEZ | review | «انا روحت ل دكتور اسنان» |
| «ال dentist» (article frame) | cs | TW | X | «هيجيلي ال cardio» |

### clinic-0004 (inform; forgot the doctor's name for the appointment the day after tomorrow)

| Expression | Column(s) | Source (id) | Type | Attested phrase |
|---|---|---|---|---|
| «صباح الخير» opener | egy, cs | G-IPY | review | «صباح الخير عندى حساب» |
| «حاجز معاد / حاجز كشف» | egy | A-SHZ | review | «رحت حاجز ميعاد تاني» |
| «بعد بكرة» | egy, cs | TW | X | «بكره او بعد بكره» |
| «نسيت اسم …» | egy, cs | TW | X | «نسيت اسم شركتها» |
| «ممكن تقولي» | egy, cs | G-BRF | review | «ممكن تقولي اشتغل ازي معاكو» |
| «عندي appointment» | cs, cs_latin | TW | X | «"appointment …" يعني انا لازم اخد معاد» |

### clinic-0005 (inform; is there a female gynaecologist, what is her name)

| Expression | Column(s) | Source (id) | Type | Attested phrase |
|---|---|---|---|---|
| «مساء الخير، لو سمحت كنت عايز/ة أعرف» | egy, cs | TW | X | «مساء الخير.. لو سمحت كنت عايز أعرف» |
| «فيه دكتورة …» | egy, cs | TW | X | «فيه دكتورة chest» |
| «دكتورة نسا» | egy | G-VEZ | review | «مع دكتوره نسا وتوليد» |
| «اسمها ايه» | egy, cs | TW | X | «اسمها ايه طيب» |
| «دكتورة gynecology» (title + English specialty) | cs, cs_latin | TW | X | «فيه دكتورة chest» (frame only) |

### clinic-0006 (none; "I wanted to cancel Sunday's orthopaedist appointment, but never mind, leave it")

| Expression | Column(s) | Source (id) | Type | Attested phrase |
|---|---|---|---|---|
| «كنت عايز + verb» | egy, cs | TW | X | «لو سمحت كنت عايز أعرف» |
| «أكنسل» (loan, Arabic script) | egy | A-CRM | review | «او انا ببقي عايزة اكنسل» |
| «دكتور عظام» | egy, cs | G-VEZ | review | «احجز عند دكتور عظام» |
| «بس خلاص» (abort) | egy, cs | TW | X | «حاسة انى اتورطت بس خلاص» |
| «سيبه» (leave it) | egy, cs | G-IPY; TW | review; X | «واسيبه من غير تطبيقات»; «خلاص سيبهم» |
| «زي ما هو» | egy, cs | G-VEZ | review | «سعره زي ما هو معروض» |
| «أعمل cancel لمعاد» | cs, cs_latin | A-TLB | review | «بيعملوا cancel للاوردر» |

### clinic-0007 (ask; book for dad, name given, phone missing)

| Expression | Column(s) | Source (id) | Type | Attested phrase |
|---|---|---|---|---|
| booking for a parent | egy, cs | A-VEZ | review | «أنا حاجز كشف لوالدي» |
| «لبابا» | egy, cs | TW | X | «وقلت لبابا واتصلت بيه» |
| «دكتور قلب» | egy | TW | X | «حد يعرف دكتور قلب شاطر» |
| «يوم ١٠/١١» (DD/MM, no year) | egy, cs | A-SWVL | review | «حجزت رحله يوم ١٢/٨» |
| «الساعة ٦ ونص» | egy, cs | G-BRF | review | «تاني يوم الساعه ٧ ونص» |
| «اسمه … / رقمه …» (name and number) | egy, cs (text, follow-up) | TW | X | «مطلوب اسم المريض ورقمه» |
| «دكتور cardio» | cs, cs_latin | TW | X | «هيجيلي ال cardio» |

### clinic-0008 (ask; postpone tomorrow's follow-up, undecided between Saturday and Sunday)

| Expression | Column(s) | Source (id) | Type | Attested phrase |
|---|---|---|---|---|
| «أجل» (postpone, first person) | egy, cs | TW | X | «هضطر أأجل الجواز» (see conflicts) |
| «لسه مش …» | egy, cs | G-BRF | review | «لسه مش عارفين يوصلو» |
| «مش متأكد/ة» about a date | egy, cs | TW | X | «مش متأكدة من معاد 25 أبريل» |
| «امتى» | egy, cs | G-VEZ | review | «الاوردر هيكون جاهز امتي» |
| «يمكن» (maybe) | egy, cs | TW | X | «يمكن يكون فى امل» |
| «نفس المعاد» (follow-up) | egy, cs | G-BRF | review | «استلام في نفس المعاد» |
| «ال follow up» | cs, cs_latin | G-CHF | review | «و اهتمام بال follow up» |

### clinic-0009 (refuse, explicit mismatch; cancel a non-relative's appointment without her number)

| Expression | Column(s) | Source (id) | Type | Attested phrase |
|---|---|---|---|---|
| «عايزة ألغي …» | egy | G-VOD | review | «وعايز الغي الفاتوره» |
| «دكتور الباطنة» | egy, cs | G-VEZ | review | «عرفت دكتور الباطنه» |
| alternative «دكتورة باطنة» | — | G-VEZ | review | «كشفت عند دكتورة باطنة» |
| «يوم 18/11» (ASCII digits) | egy, cs | G-IPY | review | «من يوم 20/8/2026» |
| «مش قريبتي» (not related) | egy, cs | TW | X | «بس لو مش قريبين» (closest form) |
| «معنديش رقمها» | egy, cs | A-ETS | review | «وانا معنديش رقم موبايل» |
| «أعمل cancel لمعاد» | cs, cs_latin | A-SWVL | review | «وعملوا cancel للرحلة» |

### clinic-0010 (act, control of 0009; cancel mother's appointment, name and phone given)

| Expression | Column(s) | Source (id) | Type | Attested phrase |
|---|---|---|---|---|
| «والدتي» / acting for her | egy, cs | A-BM | review | «حجزت مرة تانية لوالدتي» |
| same | egy, cs | G-CHF | review | «وعايز اطلب علاج لوالدتي» |
| «اسمها … ورقمها …» | egy, cs | TW | X | «مطلوب اسم المريض ورقمه» (frame) |
| «دكتور الباطنة», «يوم ١٨/١١», «أعمل cancel لمعاد» | egy, cs, cs_latin | as in clinic-0009 | review | as above |

## Spelling choices (counts in the ~270,000-text sample)

| Chosen | Count | Alternative | Count | Note |
|---|---|---|---|---|
| «معاد» | 154 | «ميعاد» | 169 | Near tie. Kept «معاد», the spec's spelling; «ميعاد» is just as common |
| «بكرة» | 838 | «بكره» | 670 | |
| «عايزة» | 1,857 | «عايزه» | 682 | |
| «عايز» | 1,636 | «عاوز» | 479 | |
| «ايه» | 8,031 | «إيه» | 1,678 | Changed from my first draft's «إيه» |
| «امتى» | 649 | «إمتى» | 93 | Changed from «إمتى» |
| «ايوة» | 416 (+110 «أيوة») | «ايوه» / «أيوه» | 276 / 50 | Changed from «أيوه»; the lint folds both to the lexicon form |
| «لسه» | 1,884 | «لسة» | 1,157 | |
| «امبارح» | 726 | «إمبارح» | 83 | |
| «معنديش» | 351 | «معيش» | 39 | Changed from «معيش» in clinic-0009 |
| «الحد» (Sunday) | 116 | «الأحد» | 51 | Standalone token counts; «يوم الحد» 36 vs «يوم الأحد» 34 |
| «الجاي» | 393 | «اللي جاي» | 163 | |
| «دكتورة» | 154 | «دكتوره» | 46 | |

Specialty after «دكتور»: the bare form is more common in indefinite use («دكتور عيون» 5 vs «دكتور العيون» 1; «دكتور باطنة» 5 vs «دكتور الباطنة» 1). I used the bare form for a new booking (0001, 0003, 0007) and the article where the doctor is a known referent ("the eye doctor of tomorrow's appointment", 0002, 0006, 0009, 0010). Both forms are attested.

## Conflicts with the spec's conventions (kept the spec; Aya to decide)

- **One-hamza rule.** The spec writes first-person «أأجّل» with one hamza («أجل», «أجله»). The attested spelling in the sample keeps two: «أأجل» (TW) and «أأجله» (TW). The drafts follow the spec.
- **Arabizi house profile.** The Arabizi I found mostly drops vowels («3nd», «mn», «bgd») and uses variant digits («m4», «sh8»). That is the spec's *variant* profile. The drafts use the house profile, as the spec requires for headline Arabizi.

## Kept without direct attestation, and why

- **Arabizi house spellings** `ma3ad`, `bokra`, `ba3d bokra`, `el 7ad el gay`, `law sama7t`, `a7gez`, `kashf`, `3ayez`/`3ayza`, `5ales`, `embare7`, `te2olli`, `ra2amha`, `waldeti`, `emta`, `sibo zay ma howa`, `mot2aked`. The sample has the vowel-less forms only (`m3ad`, `a7gz`, `5als`, `takshf`), or none. These are kept because they are the spec's house profile and the spec's own examples (`msh 3ayza`, `ma3ad`, `bokra`, `el 7ad el gay`). All are letter-for-letter readings of attested Arabic-script phrases.
- **English insertions** `derma` (0001), `dentist` (0003), `appointment` (0004, only a weakly attested quoted phrase), `gynecology` (0005), `cardio` (0007). The frames are attested («دكتورة chest», «ال cardio», «ال session»), the exact nouns mostly are not. «ال cardio» comes from a medical-student tweet, not a patient, and "Derma" from a directory, not a patient. `reschedule` and `booking`, from my first draft, were dropped: neither was attested in an Arabic-script sentence. The attested `cancel`, `confirm` and `follow up` were used instead.
- **«مش قريبتي»** (0009). Only «مش قريبين» ("not close") is attested. «قريبتي» ("my relative") is the ordinary word, but this exact negation was not found.
- **«سيبه زي ما هو»** (0006) as one phrase. Its parts «سيبه»/«سيبهم» and «زي ما هو» are each attested.
- **«ضرسي هيموتني»** (0003) as one phrase. «ضرسي … بيوجعني» and «هيموتني» / «هموت من الوجع» are attested separately. The combined phrase is the spec's own example of the hyperbole tag.
- **«أحجز لبابا»** (0007). «لبابا» and the parent-booking frame «حاجز كشف لوالدي» are attested separately.
- **EN and MSA columns** are outside this check (the brief covers the dialect columns only).
