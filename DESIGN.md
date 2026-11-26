# DESIGN.md: audience, intent, user tests

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
| s12 | close-up | one steaming cup at sunrise | the echo "slowly, slowly"; the theme returns |
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
