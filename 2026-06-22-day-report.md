Finished Phase-1 fluency training — 1682 steps over a million CadQuery programs, adapter saved clean with the loss settled flat at 0.30

Stood the Phase-1 LoRA up next to the off-the-shelf base on one vLLM server and ran them head to head, single-shot — both passed 16 of 20, but the fine-tune fixed the mirror and shell cases and nudged validity from 18 to 19, while slipping on two hard out-of-distribution parts

Read that split as a healthy fluency result — Phase-1 was never meant to teach behavior, so the real verdict waits on Phase-2

Clawed back about 190 GB on a disk that had hit 100 percent — pulled deprecated and duplicate model downloads including a 57 GB second copy of Qwen3-Coder-30B, plus old training smoke-tests and Hugging Face caches

Tracked down what was quietly burning the Claude usage — the claude-mem plugin was calling Claude on every turn and every tool use through global hooks, and stripped them out

Launched Phase-2 instruction training on 39,000 prompt-to-code pairs — killed a duplicate run a detached launch had left behind, confirmed the attention-kernel speedup was a dead end since the GPU is already compute-bound, and got past a Hugging Face telemetry crash by forcing offline mode; running now at about 15 hours
