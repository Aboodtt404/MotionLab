Pointed our LoRA at its real base and got 74 out of 100 on the full backend eval

Categorized 26 failures; one fake type called ArticleId shows up in 10 of them, almost 40 percent

Pulled the V13 training methodology off disk and confirmed only attention layers got trained

Built a three-turn self-correct shim, re-ran at 73 — the real bottleneck is the weights themselves

Ran a deep research sweep — found vLLM workarounds plus Motoko on Stack v2 and Hugging Face
