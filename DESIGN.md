# DESIGN.md: audience, intent, user tests

> **Two films live in this history.** v1, *ቀስ በቀስ / Slowly, Slowly*, was the development prototype that built and tested the studio (sections below "Prototype film"). **The submitted film is v2, *ሁሉም ለበጎ ነው / Everything Is for the Good*** (this first part). v2's brief was written on 26 Nov 2026 before any of its assets were generated.

# Film: ሁሉም ለበጎ ነው — Everything Is for the Good

## 1. Brief (written before generating anything for this film)
| | |
|---|---|
| **Source** | A personal memory of the director's. After failing an exam they had been sure they would pass, they came home close to tears, and their mother comforted them by telling a traditional Ethiopian folktale: a king, his servant, a fall from a horse, a pit, and a group that would sacrifice only a person without blemish. |
| **Why it matters** | It is not an invented motivational story. It records how a mother used oral storytelling to change her child's perspective at a hard moment, and it preserves that way of passing wisdom between generations. |
| **Primary audience** | Ethiopian students and young adults facing academic failure, disappointment or another setback. |
| **Secondary audience** | Ethiopian families who know the tradition of parents passing wisdom to children through stories. |
| **Where they watch** | On a phone, vertical, in a feed or forwarded in a family Telegram group; often muted, so the English subtitles must carry the story alone. |
| **Central message** | Do not lose hope the moment something goes wrong; we cannot yet see what it will lead to. Recurring line: **ሁሉም ለበጎ ነው**. |
| **Define (how might we…)** | How might we help a student who just failed feel, within 90 seconds, that this setback may not be the end of the story, the way a mother's folktale once did? |

### Intended emotional arc
| Beat | The viewer should feel | Carried by |
|---|---|---|
| Opening: the student comes home | sadness, empathy | slow, quiet, cool light, a held face |
| The mother begins | curiosity | warm light, music shifts, her first words |
| The king's fall; the servant in the pit | tension | low angles, fast cut, music darkens |
| Capture by the worshippers | tension at its peak | torches, shadows, no violence shown |
| Released because of his wounds | surprise | the music breaks; the king's realisation |
| The servant's answer | a second realisation | the line lands, then a silence |
| Return to the student | comfort, hope, relief | warm morning light, the line one last time |

### Design decisions (with reasons)
* **First-person narrator (the grown student remembering).** It makes the frame story personal and lets the folktale be heard the way it was first heard: through the mother's words.
* **Two visual worlds.** Present day: realistic, warm interior, contemporary clothing. Folktale: highland landscape at golden hour, earth tones, traditional dress, more painterly light. The transition happens on the mother's first words, so the viewer always knows when we are "inside the story".
* **The ritual group is invented.** Hooded earth-coloured cloaks, torches, no symbols, so it points to no existing religion or ethnic community. Danger comes from shadow and faces, never from violence or blood.
* **Fictionalised faces and a synthetic voice.** Neither the director nor their mother is depicted or voiced (see ETHICS.md).
* **Fewer shots than sentences.** The folktale has seven events. The film shows each once, lets the narration bridge the gaps, and spends the extra seconds on faces at the two realisations.

### Shot list and the reason for each shot
Generated from the final `storyboard.json` (film length 87.2 s incl. a 4 s AI end card):

| Shot | Time | Size | Reason | Motion |
|---|---|---|---|---|
| s01 | 0.0s | medium | Opens on the feeling the audience knows: coming home after failing. Sadness and empathy before any story. | **Wan 2.2** |
| s02 | 6.8s | medium | The mother notices and asks; her care turns sadness toward curiosity, and she begins the story. | Ken Burns |
| s03 | 15.2s | close-up | A five-second, music-only bridge: the mother's face as she starts to remember carries us from the living room into the tale (the cinematic transition between the two worlds). | Ken Burns; dissolves in (0.8 s) |
| s04 | 20.2s | extreme-wide | Establishes the folktale world in one wide image: highland road, golden hour, king on horseback, servant on foot. | **Wan 2.2**; dissolves in (1.5 s) |
| s05 | 26.2s | medium | The accident, shown after the fact so it stays non-graphic: dust in the air, the king on the ground holding his arm. | Ken Burns (Wan clip rejected: a glowing flame-like object materialises in the foreground from about frame 20) |
| s06 | 32.4s | medium-close-up | First time the central line is spoken, by the calm servant: the film's thesis, before anyone understands it. | Ken Burns |
| s07 | 37.2s | wide | The injustice: a high angle down into the pit makes the servant small and alone; tension rises. | Ken Burns |
| s08 | 43.0s | wide | Peak tension: the king surrounded by an invented, hooded group with torches; danger through shadow, not violence. | **Wan 2.2** |
| s09 | 49.2s | close-up | The surprise: the wound that hurt him saves him; the realisation lands on his face in torchlight. | Ken Burns |
| s10 | 56.0s | medium | Reconciliation, shown in one symbolic close-up of clasped hands over the pit (two-person staging merged the characters in a first attempt); the line is spoken a second time. | Ken Burns (Wan clip rejected: sparkle noise from about frame 20, full colour melt by frame 48) |
| s11 | 63.7s | medium-close-up | The second realisation, in one exchange: the pit saved the servant too. A quiet two-shot lets the answer land. | Ken Burns |
| s12 | 72.7s | close-up | Back to the present in morning light: the result is the same, the student is not. The line a third time, now as their own. | Ken Burns; dissolves in (1.5 s) |

## 2. User test 1 (radio cut of this film)
**Prototype tested:** `outputs/radio_cut/radio_cut.mp4`, 87 s: Amharic narration (Gemini 3.8 Flash-Lite TTS, voice Sulafat, one continuous take) over temporary music on black, with English subtitles. Run by the director on 26 Nov 2026, after the storyboard was approved.

**What the participants said** (as reported by the director; record each person's exact words and details below):
* All three responded positively.
* One participant said the narration was **slightly slow**.

| # | Who (role, age, where) | What they said |
|---|---|---|
| P1 | _to be added by the director_ | _positive (director's summary)_ |
| P2 | _to be added by the director_ | _positive (director's summary)_ |
| P3 | _to be added by the director_ | _positive; "narration slightly slow" (director's summary)_ |

**Discussion and decision:** the director discussed the pacing comment with the participant, and they agreed that the deliberate pace suits a reflective memory of a mother's story and gives viewers time to absorb each turn (both twists land after a pause). **Decision: keep the narration unchanged.** Evidence that the pace is natural rather than slowed: the take was not time-stretched; Gemini's own delivery runs at 2.06 words/s, faster than the 1.2–1.5 words/s measured for MMS and per-line Gemini (EXPERIMENTS E02, E15, E22). The extra seconds are holds on the transition and emotional beats (s03, s09, s11, s12), not slower speech.
**What changed because of test 1:** nothing in the narration. The test confirmed the story, the order of the two reveals, and the pacing choice. Visual production (Phase 2) started from the approved radio cut. *For test 2 we will ask specifically about pace with pictures, since images change how pacing feels.*

## 3. User test 2 (near-final cut of this film)
**Prototype tested:** `outputs/cuts/wan_*.mp4` and `kenburns_v2_*.mp4` (87.2 s, both aspect ratios), run by the director with three friends on 26 Nov 2026.

**What they said** (as reported by the director; individual wording to be added):
* Two of three participants independently noticed: **(1) the mother looks like a different person in s02 and s03**; **(2) in s04 the king is not riding the horse**, which contradicts the story (he rides the white horse, the servant walks beside him).
* The director agreed with both observations.

| # | Who | What they said |
|---|---|---|
| P1 | _to be added by the director_ | _(director's summary above)_ |
| P2 | _to be added by the director_ | _(director's summary above)_ |
| P3 | _to be added by the director_ | _(director's summary above)_ |

**Insights → changes** (before/after evidence in `outputs/review/`):
1. *Consistency:* s03 is no longer generated separately. It is built **from s02's own keyframe** (`keyframe_from: "s02"`) as a slow push-in onto the mother's face, so it is the same woman by construction. It also makes the transition into the tale continuous: living room → her eyes → dissolve to the road.
2. *Story accuracy:* s04 regenerated with explicit staging (the king **mounted on a white horse**, the servant walking beside it). Its Wan clip was made from the old keyframe and is now stale, so s04 uses Ken Burns (no time for a new Wan run before the deadline).
3. *Framing (director's request):* every shot now has a **focus point** (`focus: {x, y}`), and the 9:16 and 16:9 crops are centred on the subject instead of the middle of the image.
* **Lesson:** both issues were invisible in the radio cut and were caught only when people watched pictures. One is a consistency failure across *separately generated* images, the other a prompt the model satisfied only partly (king and horse present, but not riding). Neither shows up in an automatic metric.

---

# Prototype film (v1 development): ቀስ በቀስ — Slowly, Slowly

## 1. Brief (written before anything was generated)

| | |
|---|---|
| **Film** | *ቀስ በቀስ / Slowly, Slowly*, a 60–90 s narrated short in **Amharic** with English subtitles |
| **Story** | A grandmother ("Emama") makes buna every morning. The child watching is impatient: "Emama, when will it be ready?" She answers with the proverb **ቀስ በቀስ እንቁላል በእግሩ ይሄዳል** ("slowly, slowly, an egg will walk on its own legs"). Years later, alone in a fast city, the grown child roasts coffee and hears her voice. |
| **Who watches** | Young Ethiopians aged 18–35, at home and in the diaspora, who grew up around the buna ceremony and now live fast city lives. Family members (cousins, siblings) are the first audience; the public post is the second. |
| **Where** | On a phone, vertical, in a feed (TikTok/Reels/Shorts) or forwarded in a family Telegram group. Often with sound low or off, so the English subtitles have to carry the story on their own. |
| **Feel / understand at the end** | The warmth of being made to wait as a child, and a small pull to slow down and **call an elder this week**. |
| **Define (how might we…)** | How might we help young Ethiopians who live fast city lives feel the slowness of their grandmother's buna as something they still carry? |
| **Constraints** | $0 budget; no GPU on the build machine; ~0.1–0.7 MB/s internet; one night to build. |

### Why this story and these choices
* **A composite grandmother, not a portrait of a real person.** The buna ritual and the proverb are shared across many Ethiopian families. Emama is a composite character, not a likeness of any real person, and the voice is a synthetic TTS voice that clones nobody. That keeps the consent gate simple (see ETHICS.md) and keeps private family details out of free endpoints. **If you replace Emama with a real relative, record their consent in ETHICS.md first. The pipeline refuses to run until you do (`real_person: true` requires a `consent_ref`).**
* **Reference conditioning only where the face carries the shot.** s06 (her close-up) is generated from the golden reference; wide and action shots use the same character text without the reference, because conditioning pulled every shot into a portrait (EXPERIMENTS.md E07).
* **One visible face.** Only Emama's face is shown (s02, s06, s09). The child is seen from behind (s05) and the adult only by silhouette and hands (s10, s11). Fewer faces means fewer identity-drift problems, which matters with a small image model (see EXPERIMENTS.md).
* **An illustrated, gouache look, not photoreal.** It is forgiving of small-model artefacts, it reads as memory rather than documentary, and it avoids anything that looks like a real person.
* **Narration in Amharic, subtitles in English.** Amharic is the language of the memory. English subtitles reach diaspora cousins who understand spoken Amharic only partly, and viewers watching muted.
* **A proverb as the spine.** It gives the film a motif that returns three times: the answer (s06), the three rounds of coffee (s08), the echo (s12).

### Shot list and the reason for each shot
Every shot's reason is also stored in `storyboard.json` (`shots[].reason`) so it travels with the contract.

| Shot | Size | What we see | Why it exists |
|---|---|---|---|
| s01 | extreme wide | highland hills at dawn, smoke from a house | establishes place and time before any person |
| s02 | medium | Emama spreads grass, jebena, charcoal | introduces her and the ritual space |
| s03 | extreme close-up | old hands washing green beans | care and slowness, with no face to keep consistent |
| s04 | close-up | beans roasting, smoke | the sensory core of the memory |
| s05 | medium | child from behind, fidgeting | the conflict: impatience |
| s06 | medium close-up | Emama smiles | the emotional peak and the proverb |
| s07 | insert | mortar, pestle, incense | the ritual goes on regardless; the proverb in action |
| s08 | close-up | the pour into small cups | three rounds = three lessons in patience |
| s09 | wide | neighbours gathered, laughing | the reward for waiting is togetherness; music swells |
| s10 | wide | adult alone in a city flat at night | time jump; cool and solitary against the warm room before |
| s11 | close-up | young hands roasting on a gas stove | match to s04: the habit was inherited |
| s12 | close-up | one steaming cup on a windowsill, city and hills beyond (3 attempts, E14) | the echo "slowly, slowly"; the theme returns |
| end | card | "Made with AI" + credits | required disclosure |

Shot sizes vary on purpose (wide → medium → close → insert → wide) so a phone viewer always knows where they are.

---

## 2. User test 1: the radio cut (prototype)

**Prototype:** `outputs/radio_cut/radio_cut.mp4`: Amharic narration over a placeholder drone on black, with English subtitles. Made with `make radio`.

> ⚠️ **NOT YET RUN. Kenean must do this with real people.** The coding agent that built this pipeline cannot show the cut to people, and invented feedback would be both dishonest and a zero for this criterion. Use the script below. It takes about 15 minutes over Telegram or Slack.

**Protocol (same for test 2):**
1. Send the file to at least **three** people from the audience (18–35, Ethiopian, phone). Native Amharic listeners for at least two of them.
2. Ask them to watch once without comment, then ask:
   1. In one sentence, what was the film about?
   2. Which moment did you feel most? Was there a moment you lost interest?
   3. Was any Amharic word mispronounced or unnatural? Which one? *(MMS-TTS is a small model. Expect problems with ጎዝጉዘው, ሙቀጫ, ዕጣን and the quoted speech.)*
   4. Did the proverb land? Did you know it?
   5. Is it too slow, too fast, or right?
3. Write their answers verbatim below, then write **what you will change in `storyboard.json`** and make the change. The git diff is the evidence.

| # | Who (role, age, where) | Date | What they said (verbatim) |
|---|---|---|---|
| P1 | _e.g. cousin, 24, Addis_ | | |
| P2 | | | |
| P3 | | | |

**Insights → storyboard changes:**
- _e.g. "Two of three didn't recognise the proverb in the subtitle, so I changed the s06 subtitle to …"_

### Pre-test self-review (agent, NOT a user test)
Kept separate so it is not mistaken for audience evidence. These are things the agent checked by measurement before the human test:
* Narration total and per-shot timing are in `outputs/timeline.json`. See EXPERIMENTS.md E02 for the speaking-rate decision.
* Subtitles stay at 2 lines and 40 characters or fewer (enforced by `tests/test_contract.py::test_srt_two_lines_max`).

---

## 3. User test 2: the near-final cut

**Prototype:** `outputs/film_9x16.mp4` (show the vertical one, on a phone).

> ⚠️ **NOT YET RUN. Same protocol, at least three people,** ideally including at least one person from test 1, so you can see whether the change worked.

Extra questions for test 2:
6. Did Emama look like the same person each time she appeared (s02, s06, s09)?
7. Could you read the subtitles on your phone? Did anything cover them?
8. Was the music too loud under the voice anywhere?

| # | Who | Date | What they said (verbatim) |
|---|---|---|---|
| P1 | | | |
| P2 | | | |
| P3 | | | |

**Insights → storyboard changes:**
-
