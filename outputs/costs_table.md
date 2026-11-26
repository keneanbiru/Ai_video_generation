| stage | provider | model | calls | ok | errors | mean_latency_s | max_latency_s | cpu_min | t4_min_equiv | list_price_usd |
|---|---|---|---|---|---|---|---|---|---|---|
| keyframes | local:sd-turbo | stabilityai/sd-turbo | 22 | 22 | 0 | 34.02 | 44.87 | 12.47 | 1.56 | 0.0117 |
| music | local:musicgen-small | facebook/musicgen-small | 4 | 4 | 0 | 183.21 | 242.87 | 12.21 | 1.53 | 0.0089 |
| music | local:procedural | procedural_score.py | 6 | 6 | 0 | 1.15 | 1.18 | 0.12 | 0.01 | 0.0 |
| narration | local:mms-tts | facebook/mms-tts-amh | 24 | 24 | 0 | 1.1 | 1.65 | 0.44 | 0.06 | 0.0003 |

Total list-price equivalent: $0.0209; actual spend: $0.00
